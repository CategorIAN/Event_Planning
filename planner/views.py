from difflib import SequenceMatcher

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from planner.models import FormSubmission, Person
from planner.services.form_response_sync import (
    FormResponseSynchronizationError,
    apply_form_submission_to_person,
    normalize_submitted_name,
    synchronize_google_form_responses,
)
from planner.services.google_forms import GoogleFormsError


def home(request: HttpRequest) -> HttpResponse:
    return render(request, "planner/home.html")


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
