"""Derived normal invitation-list data for an Event."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as datetime_timezone

from django.db.models import Prefetch

from planner.models import Event, Invitation, Person
from planner.services.availability import (
    day_hour_ids,
    includes_required_day_hours,
)


ATTENDANCE_RESULTS = {Invitation.Result.ATTENDING, Invitation.Result.ATTENDED}


@dataclass(frozen=True)
class InvitationListRow:
    person: Person
    invited: bool
    redeem: bool
    new: bool
    expected_attendance: datetime | None
    expected_invite: datetime | None


def get_invitation_list(event: Event) -> list[InvitationListRow]:
    """Return eligible people satisfying the normal invitation priority rule."""
    required_day_hour_ids = day_hour_ids(event.time_span.day_hours.all())

    people = (
        Person.objects.filter(
            games=event.game,
            status=Person.Status.ACTIVE,
        )
        .exclude(role=Person.Role.OWNER)
        .exclude(pk=event.leader_id)
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
        event_due = latest_attendance is None or (
            expected_attendance is not None
            and expected_attendance <= event.timestamp
        )
        redeem = latest_wait is not None and (
            latest_invite is not None and latest_wait >= latest_invite
        )

        if not (redeem or event_due):
            continue

        rows.append(
            InvitationListRow(
                person=person,
                invited=any(invitation.event_id == event.pk for invitation in invitations),
                redeem=redeem,
                new=is_new,
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
        row.expected_attendance is None,
        row.expected_attendance or datetime.max.replace(tzinfo=datetime_timezone.utc),
        row.expected_invite is None,
        row.expected_invite or datetime.max.replace(tzinfo=datetime_timezone.utc),
        row.person.name.casefold(),
    )
