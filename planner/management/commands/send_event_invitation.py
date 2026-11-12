from django.core.management.base import BaseCommand, CommandError
from argparse import ArgumentParser
from typing import Any

from planner.models import Event, Person
from planner.services.event_invitations import (
    EventInvitationError,
    send_event_invitation,
)


class Command(BaseCommand):
    help = "Send an invitation email for one Event and Person."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Add required Event and Person identifiers.

        Args:
            parser: Django's command-line argument parser.
        """
        parser.add_argument("--event", required=True, type=int, dest="event_id")
        parser.add_argument("--person", required=True, type=int, dest="person_id")

    def handle(self, *args: Any, **options: Any) -> None:
        """Send one validated Event invitation and print its Gmail message ID.

        Args:
            *args: Framework-supplied positional command arguments. Unused.
            **options: Parsed Event and Person identifiers.

        Raises:
            CommandError: If either record is absent or the invitation fails.
        """
        try:
            event = Event.objects.get(pk=options["event_id"])
        except Event.DoesNotExist as error:
            raise CommandError(f"No Event exists with ID {options['event_id']}.") from error
        try:
            person = Person.objects.get(pk=options["person_id"])
        except Person.DoesNotExist as error:
            raise CommandError(f"No Person exists with ID {options['person_id']}.") from error

        try:
            result = send_event_invitation(event, person)
        except EventInvitationError as error:
            raise CommandError(str(error)) from error

        self.stdout.write(
            self.style.SUCCESS(
                f"Sent Event invitation to {person.name} "
                f"(Gmail message ID {result.message_id})."
            )
        )
