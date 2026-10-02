from difflib import SequenceMatcher
from datetime import time as datetime_time
from urllib.parse import urlencode
from uuid import uuid4

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Max, Prefetch, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from planner.forms import EventForm, SendSurveyRequestForm
from planner.models import Day, Event, Form, FormRequest, FormSubmission, Game, Hour, Person, TimeSpan
from planner.services.availability import day_hour_ids, is_available_for_time_span
from planner.services.form_response_sync import (
    FormResponseSynchronizationError,
    apply_form_submission_to_person,
    normalize_submitted_name,
    synchronize_google_form_responses,
)
from planner.services.google_forms import GoogleFormsError
from planner.services.invitation_list import get_invitation_list
from planner.services.survey_updates import (
    DUE_STATUSES,
    STATUS_ORDER,
    calculate_survey_update_schedule,
    default_request_type_for_status,
)
from planner.services.survey_request_emails import (
    SurveyRequestEmailError,
    SurveyRequestRecordingError,
    request_survey_email,
)


SURVEY_REQUEST_ACTIONS_SESSION_KEY = "survey_request_actions"
SURVEY_REQUEST_CONFIRMATION_SESSION_KEY = "survey_request_confirmation"


def home(request: HttpRequest) -> HttpResponse:
    return render(request, "planner/home.html")


def availability(request: HttpRequest) -> HttpResponse:
    """Show qualified interested-person counts for each game TimeSpan."""
    days = list(Day.objects.exclude(name="Sunday").order_by("order"))
    hours = list(Hour.objects.filter(time__gte=datetime_time(7)).order_by("time"))
    games = list(
        Game.objects.filter(expected_duration_hours__isnull=False)
        .order_by("name")
        .prefetch_related(
            Prefetch(
                "interested_people",
                queryset=Person.objects.only("id", "name").prefetch_related("availability"),
            )
        )
    )
    time_spans = TimeSpan.objects.filter(end_hour__time__lte=datetime_time(18)).select_related(
        "day", "start_hour", "end_hour"
    ).prefetch_related("day_hours")
    spans_by_key = {
        (time_span.day_id, time_span.start_hour_id, time_span.duration_hours): time_span
        for time_span in time_spans
    }

    game_grids = []
    modal_cells = []
    for game in games:
        interested_people = [
            {
                "id": person.pk,
                "name": person.name,
                "availability": day_hour_ids(person.availability.all()),
            }
            for person in game.interested_people.all()
        ]
        grid_rows = []
        for hour in hours:
            cells = []
            has_valid_span = False
            for day in days:
                time_span = spans_by_key.get(
                    (day.pk, hour.pk, game.expected_duration_hours)
                )
                if time_span is None:
                    cells.append(
                        {
                            "count": 0,
                            "people": [],
                            "day": day,
                            "start_hour": hour,
                            "end_hour": None,
                        }
                    )
                    continue

                has_valid_span = True
                qualifying_people = [
                    person
                    for person in interested_people
                    if is_available_for_time_span(person["availability"], time_span)
                ]
                cells.append(
                    {
                        "count": len(qualifying_people),
                        "people": qualifying_people,
                        "day": day,
                        "start_hour": time_span.start_hour,
                        "end_hour": time_span.end_hour,
                    }
                )
            if has_valid_span:
                grid_rows.append({"hour": hour, "cells": cells})

        maximum_count = max(
            (cell["count"] for row in grid_rows for cell in row["cells"]),
            default=0,
        )
        for row_index, row in enumerate(grid_rows):
            for column_index, cell in enumerate(row["cells"]):
                cell["css_class"] = _availability_cell_class(
                    cell["count"],
                    game.min_players,
                    maximum_count,
                )
                cell_id = f"availability-{game.pk}-{row_index}-{column_index}"
                cell["modal_id"] = cell_id
                modal_cells.append(
                    {
                        "id": cell_id,
                        "game_name": game.name,
                        "day_name": cell["day"].name,
                        "start_hour": str(cell["start_hour"]),
                        "end_hour": (
                            str(cell["end_hour"])
                            if cell["end_hour"] is not None
                            else None
                        ),
                        "count": cell["count"],
                        "people": [person["name"] for person in cell["people"]],
                    }
                )
        game_grids.append({"game": game, "rows": grid_rows})

    return render(
        request,
        "planner/availability.html",
        {
            "days": days,
            "game_grids": game_grids,
            "modal_cells": modal_cells,
        },
    )


def _availability_cell_class(
    count: int,
    min_players: int | None,
    maximum_count: int,
) -> str:
    """Return a display class for a count within one game's grid."""
    if min_players is None:
        return ""
    if count < min_players:
        return "availability-low"
    if count == maximum_count:
        return "availability-best"
    return "availability-valid"


def events(request: HttpRequest) -> HttpResponse:
    return _render_events_page(request, EventForm())


@require_POST
def create_event(request: HttpRequest) -> HttpResponse:
    event_form = EventForm(request.POST)
    if event_form.is_valid():
        event = event_form.save()
        messages.success(request, "Event created.")
        return redirect(f"{reverse('events')}?{urlencode({'event_id': event.pk})}")
    return _render_events_page(request, event_form, status=400)


def _render_events_page(
    request: HttpRequest,
    event_form: EventForm,
    *,
    status: int = 200,
) -> HttpResponse:
    event_choices = list(
        Event.objects.select_related(
            "game",
            "leader",
            "time_span__day",
            "time_span__start_hour",
            "time_span__end_hour",
        )
        .order_by("-timestamp")
    )
    selected_event = None
    if event_choices:
        selected_event_id = request.GET.get("event_id")
        if selected_event_id:
            selected_event = get_object_or_404(
                Event.objects.select_related(
                    "game",
                    "leader",
                    "time_span__day",
                    "time_span__start_hour",
                    "time_span__end_hour",
                ),
                pk=selected_event_id,
            )
        else:
            selected_event = event_choices[0]

    return render(
        request,
        "planner/events.html",
        {
            "events": event_choices,
            "selected_event": selected_event,
            "event_form": event_form,
            "invitation_rows": (
                get_invitation_list(selected_event) if selected_event is not None else []
            ),
        },
        status=status,
    )


def form_submissions(request: HttpRequest) -> HttpResponse:
    unmatched_submissions = list(
        FormSubmission.objects.filter(person__isnull=True).order_by("submitted_at")
    )
    people = list(Person.objects.all())

    for submission in unmatched_submissions:
        submitted_name = normalize_submitted_name(submission.submitted_name)
        submission.candidates = sorted(
            people,
            key=lambda person: SequenceMatcher(
                None,
                submitted_name,
                normalize_submitted_name(person.name),
            ).ratio(),
            reverse=True,
        )

    return render(
        request,
        "planner/form_submissions.html",
        {"unmatched_submissions": unmatched_submissions},
    )


@require_POST
def sync_google_form_responses(request: HttpRequest) -> HttpResponse:
    try:
        summary = synchronize_google_form_responses()
    except (FormResponseSynchronizationError, GoogleFormsError) as error:
        messages.error(request, f"Google Forms synchronization failed: {error}")
    else:
        messages.success(
            request,
            "Google Forms synchronization completed: "
            f"{summary['submissions_created']} new submission(s) created.",
        )
    return redirect("form_submissions")


@require_POST
def create_person_from_submission(
    request: HttpRequest, submission_id: int
) -> HttpResponse:
    try:
        with transaction.atomic():
            submission = get_object_or_404(
                FormSubmission.objects.select_for_update(), pk=submission_id
            )
            if submission.person_id is not None:
                messages.info(request, "This Form Submission has already been resolved.")
                return redirect("form_submissions")

            person = Person.objects.create(
                name=submission.submitted_name,
                email=submission.submitted_email,
            )
            apply_form_submission_to_person(submission, person)
    except FormResponseSynchronizationError as error:
        messages.error(request, f"Could not apply the Form Submission: {error}")
        return redirect("form_submissions")

    messages.success(request, "Created a Person and applied the Form Submission.")
    return redirect("form_submissions")


@require_POST
def update_person_from_submission(
    request: HttpRequest, submission_id: int, person_id: int
) -> HttpResponse:
    try:
        with transaction.atomic():
            submission = get_object_or_404(
                FormSubmission.objects.select_for_update(), pk=submission_id
            )
            if submission.person_id is not None:
                messages.info(request, "This Form Submission has already been resolved.")
                return redirect("form_submissions")

            person = get_object_or_404(Person, pk=person_id)
            person.name = submission.submitted_name
            person.email = submission.submitted_email
            person.save(update_fields=["name", "email"])
            apply_form_submission_to_person(submission, person)
    except FormResponseSynchronizationError as error:
        messages.error(request, f"Could not apply the Form Submission: {error}")
        return redirect("form_submissions")

    messages.success(request, "Updated the selected Person from the Form Submission.")
    return redirect("form_submissions")


def survey_updates(request: HttpRequest) -> HttpResponse:
    selected_form, form_error = _select_survey_form()
    due_only = request.GET.get("due_only") == "1"
    context = _survey_update_context(request, selected_form, form_error, due_only)
    context["email_confirmation"] = request.session.pop(
        SURVEY_REQUEST_CONFIRMATION_SESSION_KEY, None
    )
    return render(request, "planner/survey_updates.html", context)


@require_POST
def mark_survey_requested(request: HttpRequest) -> HttpResponse:
    request_form = SendSurveyRequestForm(request.POST)
    due_only = request.POST.get("due_only") == "1"

    if not request_form.is_valid():
        return _render_survey_request_error(request, request_form, due_only)

    person = request_form.cleaned_data["person"]
    form = request_form.cleaned_data["form"]
    action_token = request_form.cleaned_data["action_token"]
    actions = request.session.get(SURVEY_REQUEST_ACTIONS_SESSION_KEY, {})
    action = actions.pop(action_token, None)
    request.session[SURVEY_REQUEST_ACTIONS_SESSION_KEY] = actions
    request.session.modified = True
    if action != {"person_id": person.pk, "form_id": form.pk}:
        request_form.add_error(
            None,
            "This request action is no longer valid. Refresh the page and try again.",
        )
        return _render_survey_request_error(request, request_form, due_only)

    try:
        result = request_survey_email(
            person,
            form,
            request_form.cleaned_data["request_type"],
        )
    except SurveyRequestRecordingError as error:
        _store_email_confirmation(
            request,
            email=error.email,
            message_id=error.message_id,
            recorded=False,
            error=str(error),
        )
        messages.error(request, str(error))
    except SurveyRequestEmailError as error:
        messages.error(request, f"The survey request could not be sent: {error}")
    else:
        _store_email_confirmation(
            request,
            email=result.email,
            message_id=result.message_id,
            recorded=True,
        )
        messages.success(request, f"Sent a survey request to {person.name}.")

    return redirect(_survey_updates_url(due_only))


def _select_survey_form() -> tuple[Form | None, str | None]:
    if not settings.GENERAL_SURVEY_FORM_ID:
        return None, "GENERAL_SURVEY_FORM_ID is not configured."
    try:
        return Form.objects.get(google_form_id=settings.GENERAL_SURVEY_FORM_ID), None
    except Form.DoesNotExist:
        return (
            None,
            "No Form exists with the configured GENERAL_SURVEY_FORM_ID.",
        )


def _survey_update_context(
    request: HttpRequest,
    selected_form: Form | None,
    form_error: str | None,
    due_only: bool,
    *,
    form_errors: dict[int, SendSurveyRequestForm] | None = None,
) -> dict[str, object]:
    rows = []
    now = timezone.now()
    if selected_form is not None:
        people = Person.objects.filter(
            status__in=[Person.Status.ACTIVE, Person.Status.NOT_NOW]
        ).annotate(
            last_requested_at=Max(
                "form_requests__requested_at",
                filter=Q(form_requests__form=selected_form),
            ),
            last_submitted_at=Max(
                "form_submissions__submitted_at",
                filter=Q(form_submissions__form=selected_form),
            ),
        ).prefetch_related(
            Prefetch(
                "form_requests",
                queryset=FormRequest.objects.filter(form=selected_form).only(
                    "person_id", "requested_at"
                ),
                to_attr="selected_form_requests",
            )
        )
        for person in people:
            schedule = calculate_survey_update_schedule(
                person_status=person.status,
                last_requested_at=person.last_requested_at,
                last_submitted_at=person.last_submitted_at,
                now=now,
            )
            if due_only and schedule.status not in DUE_STATUSES:
                continue
            person.schedule = schedule
            person.request_count = sum(
                person.last_submitted_at is None
                or form_request.requested_at > person.last_submitted_at
                for form_request in person.selected_form_requests
            )
            action_token = uuid4().hex
            person.request_form = (form_errors or {}).get(
                person.pk,
                SendSurveyRequestForm(
                    initial={
                        "person": person.pk,
                        "form": selected_form.pk,
                        "action_token": action_token,
                        "request_type": default_request_type_for_status(
                            schedule.status
                        ),
                    }
                ),
            )
            if person.pk not in (form_errors or {}):
                actions = request.session.get(SURVEY_REQUEST_ACTIONS_SESSION_KEY, {})
                actions[action_token] = {
                    "person_id": person.pk,
                    "form_id": selected_form.pk,
                }
                request.session[SURVEY_REQUEST_ACTIONS_SESSION_KEY] = actions
            rows.append(person)
        rows.sort(
            key=lambda person: (
                STATUS_ORDER[person.schedule.status],
                person.schedule.next_contact_due,
                person.name.casefold(),
            )
        )

    return {
        "selected_form": selected_form,
        "form_error": form_error,
        "due_only": due_only,
        "rows": rows,
    }


def _render_survey_request_error(
    request: HttpRequest,
    request_form: SendSurveyRequestForm,
    due_only: bool,
) -> HttpResponse:
    messages.error(request, "The survey request could not be sent.")
    selected_form, form_error = _select_survey_form()
    form_errors = {}
    person_id = request.POST.get("person")
    if person_id and person_id.isdigit():
        form_errors[int(person_id)] = request_form
    context = _survey_update_context(
        request,
        selected_form,
        form_error,
        due_only,
        form_errors=form_errors,
    )
    return render(request, "planner/survey_updates.html", context, status=400)


def _store_email_confirmation(
    request: HttpRequest,
    *,
    email,
    message_id: str | None,
    recorded: bool,
    error: str | None = None,
) -> None:
    """Save the actual sent message for one post-redirect-get confirmation modal."""
    request.session[SURVEY_REQUEST_CONFIRMATION_SESSION_KEY] = {
        "recipient": email.recipient,
        "subject": email.subject,
        "body": email.body,
        "message_id": message_id,
        "recorded": recorded,
        "error": error,
    }


def _survey_updates_url(due_only: bool) -> str:
    parameters = {}
    if due_only:
        parameters["due_only"] = "1"
    return f"{reverse('survey_updates')}?{urlencode(parameters)}"
