from django.core.management.base import BaseCommand, CommandError

from planner.services.google_auth import (
    GoogleAuthorizationError,
    authorize_google_integrations,
)


class Command(BaseCommand):
    help = "Authorize the shared Google Forms and Gmail integrations."

    def handle(self, *args, **options):
        try:
            authorize_google_integrations()
        except GoogleAuthorizationError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS("Google integrations authorized successfully."))
