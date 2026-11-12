from django.core.management.base import BaseCommand, CommandError
from typing import Any

from planner.services.google_auth import (
    GoogleAuthorizationError,
    authorize_google_integrations,
)


class Command(BaseCommand):
    help = "Authorize the shared Google Forms and Gmail integrations."

    def handle(self, *args: Any, **options: Any) -> None:
        """Authorize Google Forms and Gmail and report success to the terminal.

        The helper starts the local browser-based OAuth flow and writes the
        shared authorized-user token on success.

        Args:
            *args: Framework-supplied positional command arguments. Unused.
            **options: Framework-supplied parsed command options. Unused.

        Raises:
            CommandError: If Google authorization fails.
        """
        try:
            authorize_google_integrations()
        except GoogleAuthorizationError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS("Google integrations authorized successfully."))
