from django.core.management.base import BaseCommand, CommandError

from planner.services.form_response_sync import (
    FormResponseSynchronizationError,
    synchronize_google_form_responses,
)
from planner.services.google_forms import GoogleFormsError


class Command(BaseCommand):
    help = "Synchronize new responses from the configured Google Form."

    def handle(self, *args, **options):
        try:
            summary = synchronize_google_form_responses()
        except (FormResponseSynchronizationError, GoogleFormsError) as error:
            raise CommandError(str(error)) from error

        self.stdout.write(
            self.style.SUCCESS(
                "Synchronized "
                f"{summary['submissions_created']} new submission(s) from "
                f"{summary['responses_retrieved']} retrieved response(s); "
                f"{summary['submissions_already_existing']} already existed."
            )
        )
