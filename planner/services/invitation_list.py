"""Derived normal invitation-list data for an Event."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as datetime_timezone

from django.conf import settings
from django.db.models import Prefetch
from django.utils import timezone

from planner.models import Event, Form, FormSubmission, Invitation, Person
from planner.services.availability import (
    day_hour_ids,
    includes_required_day_hours,
)


EVENT_DUE_LOOKAHEAD = timedelta(days=14)
ATTENDANCE_RESULTS = {Invitation.Result.ATTENDING, Invitation.Result.ATTENDED}


@dataclass(frozen=True)
class InvitationListRow:
    person: Person
    invited: bool
    redeem: bool
    new: bool
    completed_survey: bool
    expected_attendance: datetime | None
    expected_invite: datetime | None


def get_invitation_list(event: Event) -> list[InvitationListRow]:
    """Return eligible people satisfying the normal invitation priority rule."""
    now = timezone.now()
    general_survey = Form.objects.filter(
        google_form_id=settings.GENERAL_SURVEY_FORM_ID
    ).first()
    submission_prefetch = []
    if general_survey is not None:
        submission_prefetch.append(
            Prefetch(
                "form_submissions",
                queryset=FormSubmission.objects.filter(form=general_survey).only(
                    "id", "person_id"
                ),
                to_attr="general_survey_submissions",
            )
        )

    required_day_hour_ids = day_hour_ids(event.time_span.day_hours.all())

    people = (
        Person.objects.filter(games=event.game)
        .only("id", "name", "event_cooldown")
        .prefetch_related(
            "availability",
            Prefetch(
                "invitations",
                queryset=Invitation.objects.select_related("event").only(
                    "id", "person_id", "event_id", "invited_at", "result",
                    "event__id", "event__timestamp",
                ),
                to_attr="invitation_history",
            ),
            *submission_prefetch,
        )
        .distinct()
    )

    rows = []
    for person in people:
        if not includes_required_day_hours(
            day_hour_ids(person.availability.all()), required_day_hour_ids
        ):
            continue

        invitations = person.invitation_history
        latest_invite = _latest_invite(invitations)
        latest_attendance = _latest_attendance(invitations)
        latest_wait = _latest_wait(invitations)
        expected_invite = _expected_datetime(latest_invite, person.event_cooldown)
        expected_attendance = _expected_datetime(
            latest_attendance, person.event_cooldown
        )
        is_new = latest_invite is None
        invite_due = is_new or (
            expected_invite is not None and expected_invite <= now
        )
        event_due = latest_attendance is None or (
            expected_attendance is not None
            and expected_attendance <= now + EVENT_DUE_LOOKAHEAD
        )
        redeem = latest_wait is not None and (
            latest_invite is not None and latest_wait >= latest_invite
        )

        # Eligibility is already explicitly required for this selected Event.
        # Survey completion remains a priority signal rather than a second join rule.
        if not (redeem or (event_due and invite_due)):
            continue

        rows.append(
            InvitationListRow(
                person=person,
                invited=any(invitation.event_id == event.pk for invitation in invitations),
                redeem=redeem,
                new=is_new,
                completed_survey=(
                    bool(person.general_survey_submissions)
                    if general_survey is not None
                    else False
                ),
                expected_attendance=expected_attendance,
                expected_invite=expected_invite,
            )
        )

    return sorted(rows, key=_invitation_list_sort_key)


def _latest_invite(invitations: list[Invitation]) -> datetime | None:
    return max((invitation.invited_at for invitation in invitations), default=None)


def _latest_attendance(invitations: list[Invitation]) -> datetime | None:
    return max(
        (
            invitation.event.timestamp
            for invitation in invitations
            if invitation.result in ATTENDANCE_RESULTS
        ),
        default=None,
    )


def _latest_wait(invitations: list[Invitation]) -> datetime | None:
    return max(
        (
            invitation.invited_at
            for invitation in invitations
            if invitation.result == Invitation.Result.WAITING
        ),
        default=None,
    )


def _expected_datetime(
    latest: datetime | None, cooldown: timedelta | None
) -> datetime | None:
    if latest is None or cooldown is None:
        return None
    return latest + cooldown


def _invitation_list_sort_key(row: InvitationListRow) -> tuple:
    return (
        row.invited,
        not row.redeem,
        not row.new,
        not row.completed_survey,
        row.expected_attendance is None,
        row.expected_attendance or datetime.max.replace(tzinfo=datetime_timezone.utc),
        row.expected_invite is None,
        row.expected_invite or datetime.max.replace(tzinfo=datetime_timezone.utc),
        row.person.name.casefold(),
    )
