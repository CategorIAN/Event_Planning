import json

from django.core.management.base import BaseCommand, CommandError

from planner.services.google_forms import (
    GoogleFormsError,
    _extract_questions,
    get_form,
)

from ._raw_data import save_json


DEFAULT_FORM_ID = "1N6QRk-OwsVANBopI11X9NOQTPcTyGP6K8Ql-ocXbayI"


class Command(BaseCommand):
    help = "Retrieve and print a Google Form's questions and question IDs."

    def add_arguments(self, parser):
        parser.add_argument(
            "form_id",
            nargs="?",
            default=DEFAULT_FORM_ID,
            help=f"The Google Form ID to inspect (default: {DEFAULT_FORM_ID}).",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print the complete raw Google Forms API response as JSON.",
        )

    def handle(self, *args, **options):
        try:
            form = get_form(options["form_id"])
            output_path = save_json(form, options["form_id"])
            if options["json"]:
                self.stdout.write(json.dumps(form, indent=2, ensure_ascii=False))
                self.stderr.write(f"Saved raw JSON to {output_path}")
                return

            questions = _extract_questions(form)
            title = form.get("info", {}).get("title")
            if not isinstance(title, str) or not title:
                raise GoogleFormsError("Google Forms API returned a form without a title.")
        except GoogleFormsError as error:
            raise CommandError(str(error)) from error

        self.stdout.write(f"Saved raw JSON to {output_path}")
        self.stdout.write(self.style.SUCCESS(f"Form: {title}"))
        if not questions:
            self.stdout.write("No questions found.")
            return

        for question in questions:
            self.stdout.write(f"- {question['title'] or '(untitled question)'}")
            self.stdout.write(f"  Question ID: {question['google_question_id']}")
            if question["google_item_id"]:
                self.stdout.write(f"  Item ID: {question['google_item_id']}")
            if question["question_type"]:
                self.stdout.write(f"  Type: {question['question_type']}")
