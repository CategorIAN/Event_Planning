"""Email and recording workflow for Event invitations."""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from django.db import IntegrityError
from django.utils import timezone

from planner.models import Event, Invitation, Person
from planner.services.gmail import GmailError, send_email
from planner.services.invitation_list import get_invitation_list


VENUE_NAME = "The Parlour"
VENUE_LOCATION = "Sidney, MT"
VENUE_FACEBOOK_URL = "https://www.facebook.com/theparlour.mt/"


class EventInvitationError(Exception):
    """Base exception for Event-invitation failures."""


class EventInvitationValidationError(EventInvitationError):
    """Raised when an Event invitation cannot be sent safely."""


class EventInvitationIneligibleError(EventInvitationError):
    """Raised when the person is not on the Event's invitation list."""


class EventInvitationAlreadyExistsError(EventInvitationError):
    """Raised when an Event already has an invitation for this person."""


class EventInvitationSendError(EventInvitationError):
    """Raised when Gmail cannot send an Event invitation."""


class EventInvitationRecordingError(EventInvitationError):
    """Raised when a sent Event invitation cannot be recorded."""


class EventInvitationUpdateError(EventInvitationError):
    """Raised when an existing Event invitation cannot be updated."""


@dataclass(frozen=True)
class EventInvitationEmail:
    recipient: str
    subject: str
    body: str
    attending_count: int
    remaining_spots: int
    offers_plus_one: bool


@dataclass(frozen=True)
class EventInvitationResult:
    email: EventInvitationEmail
    message_id: str
    invitation: Invitation


def build_event_invitation_email(event: Event, person: Person) -> EventInvitationEmail:
    """Build invitation content without sending or recording it."""
    _validate_email_recipient(person)
    if event.game.max_players is None:
        raise EventInvitationValidationError(
            f"{event.game} does not have a maximum player count configured."
        )

    attending_count = get_current_attendance(event)
    remaining_spots = max(event.game.max_players - attending_count, 0)
    offers_plus_one = remaining_spots >= 2
    local_timestamp = timezone.localtime(event.timestamp)
    event_date = local_timestamp.strftime("%A, %B %d, %Y").replace(" 0", " ")
    event_time = local_timestamp.strftime("%I:%M %p").lstrip("0")

    game_link = ""
    if event.game.boardgamegeek_url:
        game_link = (
            "\nLearn more about the game on BoardGameGeek:\n"
            f"{event.game.boardgamegeek_url}\n"
        )
    plus_one_message = ""
    if offers_plus_one:
        plus_one_message = (
            "\nYou are welcome to bring a plus one. Please say in your response "
            "if you would like to bring a plus one.\n"
        )

    body = f"""Hi {person.name},

I would like to invite you to play {event.game.name}.

Date: {event_date}
Start time: {event_time}
Location: {VENUE_NAME}, {VENUE_LOCATION}
Learn more about {VENUE_NAME}: {VENUE_FACEBOOK_URL}
{game_link}
{attending_count} people are currently going, and I am looking for {remaining_spots} more.
{plus_one_message}
Please reply to this email if you would like to attend. Receiving this invitation does not reserve a spot; your spot is only reserved after you respond.

Thank you!
Ian"""
    return EventInvitationEmail(
        recipient=person.email,
        subject=f"Invitation: {event.game.name} on {event_date}",
        body=body,
        attending_count=attending_count,
        remaining_spots=remaining_spots,
        offers_plus_one=offers_plus_one,
    )


def send_event_invitation(event: Event, person: Person) -> EventInvitationResult:
    """Send one eligible Event invitation and record it as Pending."""
    if Invitation.objects.filter(event=event, person=person).exists():
        raise EventInvitationAlreadyExistsError(
            f"{person.name} already has an invitation for this Event; no email was sent."
        )
    if not any(row.person.pk == person.pk for row in get_invitation_list(event)):
        raise EventInvitationIneligibleError(
            f"{person.name} is not currently eligible for this Event's invitation list."
        )

    email = build_event_invitation_email(event, person)
    try:
        message_id = send_email(email.recipient, email.subject, email.body)
    except GmailError as error:
        raise EventInvitationSendError(f"Event invitation was not sent: {error}") from error

    try:
        invitation = Invitation.objects.create(
            event=event,
            person=person,
            invited_at=timezone.now(),
            result=Invitation.Result.PENDING,
        )
    except IntegrityError as error:
        raise EventInvitationRecordingError(
            "The email was sent successfully "
            f"(Gmail message ID {message_id}) but the Invitation was not recorded. "
            "Do not resend automatically."
        ) from error

    return EventInvitationResult(
        email=email,
        message_id=message_id,
        invitation=invitation,
    )


def get_current_attendance(event: Event) -> int:
    """Count distinct automatic attendees and Attending invitations with plus ones."""
    owner = Person.objects.filter(role=Person.Role.OWNER).order_by("pk").first()
    automatic_attendee_ids = {event.leader_id}
    if owner is not None:
        automatic_attendee_ids.add(owner.pk)

    attendance = len(automatic_attendee_ids)
    attending_invitations = Invitation.objects.filter(
        event=event,
        result=Invitation.Result.ATTENDING,
    ).only("person_id", "plus_ones")
    for invitation in attending_invitations:
        attendance += invitation.plus_ones
        if invitation.person_id not in automatic_attendee_ids:
            attendance += 1
    return attendance


def update_invitation_result(
    event: Event, invitation_id: int, result: str
) -> Invitation:
    """Update one invitation's valid result for the specified Event."""
    if result not in Invitation.Result.values:
        raise EventInvitationUpdateError("The requested invitation result is invalid.")
    try:
        invitation = Invitation.objects.get(pk=invitation_id, event=event)
    except Invitation.DoesNotExist as error:
        raise EventInvitationUpdateError(
            "The invitation does not belong to this Event."
        ) from error
    invitation.result = result
    invitation.save(update_fields=["result"])
    return invitation


def adjust_invitation_plus_ones(
    event: Event, invitation_id: int, delta: int
) -> Invitation:
    """Adjust plus ones by one without allowing a negative value."""
    if delta not in {-1, 1}:
        raise EventInvitationUpdateError("Plus ones can only change by one at a time.")
    try:
        invitation = Invitation.objects.get(pk=invitation_id, event=event)
    except Invitation.DoesNotExist as error:
        raise EventInvitationUpdateError(
            "The invitation does not belong to this Event."
        ) from error
    new_plus_ones = invitation.plus_ones + delta
    if new_plus_ones < 0:
        raise EventInvitationUpdateError("Plus ones cannot be negative.")
    invitation.plus_ones = new_plus_ones
    invitation.save(update_fields=["plus_ones"])
    return invitation


def _validate_email_recipient(person: Person) -> None:
    if not person.email or not person.email.strip():
        raise EventInvitationValidationError("The person does not have an email address.")
    try:
        EmailValidator()(person.email)
    except ValidationError as error:
        raise EventInvitationValidationError("The person has an invalid email address.") from error
