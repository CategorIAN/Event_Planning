from django.core.management.base import BaseCommand, CommandError

from planner.models import Form, Person
from planner.services.survey_request_emails import (
    GOOGLE_FORM_ID,
    SurveyRequestEmailError,
    request_survey_email,
)


class SurveyRequestEmailCommand(BaseCommand):
    request_type = ""

    def add_arguments(self, parser):
        parser.add_argument("--person-id", required=True, type=int)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview the email without sending or recording a request.",
        )

    def handle(self, *args, **options):
        try:
            person = Person.objects.get(pk=options["person_id"])
        except Person.DoesNotExist as error:
            raise CommandError(f"No Person exists with ID {options['person_id']}.") from error
        try:
            form = Form.objects.get(google_form_id=GOOGLE_FORM_ID)
        except Form.DoesNotExist as error:
            raise CommandError(
                f"No Form exists with Google Form ID {GOOGLE_FORM_ID}."
            ) from error

        try:
            result = request_survey_email(
                person,
                form,
                self.request_type,
                dry_run=options["dry_run"],
            )
        except SurveyRequestEmailError as error:
            raise CommandError(str(error)) from error

        if options["dry_run"]:
            self.stdout.write(f"To: {result.email.recipient}")
            self.stdout.write(f"Subject: {result.email.subject}")
            self.stdout.write(result.email.body)
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Sent {self.request_type} survey request to {person.name} "
                f"(Gmail message ID {result.message_id})."
            )
        )
