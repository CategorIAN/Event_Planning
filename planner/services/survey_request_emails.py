"""Email and recording workflow for general-survey requests."""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator, URLValidator
from django.db import DatabaseError
from django.utils import timezone

from planner.models import Form, FormRequest, Person
from planner.services.gmail import GmailError, send_email


GOOGLE_FORM_ID = "1N6QRk-OwsVANBopI11X9NOQTPcTyGP6K8Ql-ocXbayI"
INITIAL = "initial"
RENEWAL = "renewal"
REMINDER = "reminder"
REQUEST_TYPES = {INITIAL, RENEWAL, REMINDER}


class SurveyRequestEmailError(Exception):
    """Base exception for survey-request email failures."""


class SurveyRequestValidationError(SurveyRequestEmailError):
    """Raised when a person or form cannot receive a survey request."""


class SurveyRequestSendError(SurveyRequestEmailError):
    """Raised when Gmail cannot send a survey request."""


class SurveyRequestRecordingError(SurveyRequestEmailError):
    """Raised when a sent survey request cannot be recorded."""

    def __init__(self, message: str, *, email: "SurveyEmail", message_id: str):
        super().__init__(message)
        self.email = email
        self.message_id = message_id


@dataclass(frozen=True)
class SurveyEmail:
    recipient: str
    subject: str
    body: str


@dataclass(frozen=True)
class SurveyRequestResult:
    email: SurveyEmail
    message_id: str | None


def build_survey_request_email(
    person: Person, form: Form, request_type: str
) -> SurveyEmail:
    """Build a survey-request email without sending or recording it."""
    _validate_recipient(person, form, request_type)
    templates = {
        INITIAL: (
            "Complete the survey to be considered for tabletop gaming events",
            """Hi {name},

If you would like to be considered for invitations to my tabletop gaming events, please complete the {form_name}.

Your answers help me understand your availability, game interests, and preferences when planning events.

Complete the survey here:
{survey_url}

Thank you!
Ian Kessler
Kessler Gaming""",
        ),
        RENEWAL: (
            "Please update your tabletop gaming survey",
            """Hi {name},

It is time to review and update your answers to the {form_name}, even if your availability and preferences have stayed the same.

Keeping your answers current helps me plan events and decide whom to invite.

Please submit your current answers here:
{survey_url}

Thank you!
Ian Kessler
Kessler Gaming""",
        ),
        REMINDER: (
            "Reminder: please complete your tabletop gaming survey",
            """Hi {name},

This is a reminder about my previous request to complete or update the {form_name}.

If you would like to remain on my list for tabletop gaming events, please submit your current answers. If I do not receive a response, I may remove you from the invitation list.

Complete or update the survey here:
{survey_url}

Thank you!
Ian Kessler
Kessler Gaming""",
        ),
    }
    subject, body_template = templates[request_type]
    return SurveyEmail(
        recipient=person.email,
        subject=subject,
        body=body_template.format(
            name=person.name,
            form_name=form.name,
            survey_url=form.survey_url,
        ),
    )


def request_survey_email(
    person: Person, form: Form, request_type: str, *, dry_run: bool = False
) -> SurveyRequestResult:
    """Send and record a survey request, or return a preview when dry-running."""
    email = build_survey_request_email(person, form, request_type)
    if dry_run:
        return SurveyRequestResult(email=email, message_id=None)

    try:
        message_id = send_email(email.recipient, email.subject, email.body)
    except GmailError as error:
        raise SurveyRequestSendError(f"Survey request was not sent: {error}") from error

    try:
        FormRequest.objects.create(
            person=person,
            form=form,
            requested_at=timezone.now(),
        )
    except DatabaseError as error:
        raise SurveyRequestRecordingError(
            "The email was sent successfully "
            f"(Gmail message ID {message_id}) but the FormRequest was not recorded. "
            "Do not resend automatically.",
            email=email,
            message_id=message_id,
        ) from error

    return SurveyRequestResult(email=email, message_id=message_id)


def _validate_recipient(person: Person, form: Form, request_type: str) -> None:
    if request_type not in REQUEST_TYPES:
        raise SurveyRequestValidationError(f"Unknown survey request type: {request_type}.")
    if person.status == Person.Status.PLEASE_REMOVE:
        raise SurveyRequestValidationError("Survey requests cannot be sent to this person.")
    if not person.email or not person.email.strip():
        raise SurveyRequestValidationError("The person does not have an email address.")
    try:
        EmailValidator()(person.email)
    except ValidationError as error:
        raise SurveyRequestValidationError("The person has an invalid email address.") from error
    if not form.survey_url or not form.survey_url.strip():
        raise SurveyRequestValidationError("The form does not have a public respondent URL.")
    try:
        URLValidator(schemes=["http", "https"])(form.survey_url)
    except ValidationError as error:
        raise SurveyRequestValidationError(
            "The form does not have a valid public respondent URL."
        ) from error
