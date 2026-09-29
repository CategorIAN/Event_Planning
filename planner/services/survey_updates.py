"""Scheduling logic for general-survey update requests."""

from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime

from planner.models import Person
from planner.services.survey_request_emails import INITIAL, REMINDER, RENEWAL


INITIAL_REQUEST_DUE = "Initial request due"
RENEWAL_DUE = "Renewal due"
REMINDER_DUE = "Reminder due"
AWAITING_RESPONSE = "Awaiting response"
CURRENT = "Current"

STATUS_ORDER = {
    INITIAL_REQUEST_DUE: 0,
    RENEWAL_DUE: 1,
    REMINDER_DUE: 2,
    AWAITING_RESPONSE: 3,
    CURRENT: 4,
}
DUE_STATUSES = {INITIAL_REQUEST_DUE, RENEWAL_DUE, REMINDER_DUE}


def default_request_type_for_status(status: str) -> str:
    """Return the suggested email template for a survey-update status."""
    return {
        INITIAL_REQUEST_DUE: INITIAL,
        RENEWAL_DUE: RENEWAL,
        REMINDER_DUE: REMINDER,
        AWAITING_RESPONSE: REMINDER,
        CURRENT: RENEWAL,
    }[status]


@dataclass(frozen=True)
class SurveyUpdateSchedule:
    status: str
    next_contact_due: datetime


def add_calendar_months(value: datetime, months: int) -> datetime:
    """Return a datetime shifted by calendar months, preserving its timezone."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def calculate_survey_update_schedule(
    *,
    person_status: str,
    last_requested_at: datetime | None,
    last_submitted_at: datetime | None,
    now: datetime,
) -> SurveyUpdateSchedule:
    """Calculate one person's survey-update state at a supplied point in time."""
    if last_requested_at is None and last_submitted_at is None:
        return SurveyUpdateSchedule(INITIAL_REQUEST_DUE, now)

    unanswered_request = last_requested_at is not None and (
        last_submitted_at is None or last_submitted_at < last_requested_at
    )
    if unanswered_request:
        reminder_due = add_calendar_months(last_requested_at, 1)
        status = REMINDER_DUE if reminder_due < now else AWAITING_RESPONSE
        return SurveyUpdateSchedule(status, reminder_due)

    if last_submitted_at is None:
        # A request must be unanswered when no submission exists, so this is defensive.
        return SurveyUpdateSchedule(INITIAL_REQUEST_DUE, now)

    renewal_months = 6 if person_status == Person.Status.ACTIVE else 3
    renewal_due = add_calendar_months(last_submitted_at, renewal_months)
    status = RENEWAL_DUE if renewal_due < now else CURRENT
    return SurveyUpdateSchedule(status, renewal_due)
