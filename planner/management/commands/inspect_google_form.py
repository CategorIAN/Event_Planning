from django.core.management.base import BaseCommand, CommandError

from planner.services.google_forms import (
    GoogleFormsError,
    _extract_questions,
    get_form,
)


class Command(BaseCommand):
    help = "Retrieve and print a Google Form's questions and question IDs."

    def add_arguments(self, parser):
        parser.add_argument("form_id", help="The Google Form ID to inspect.")

    def handle(self, *args, **options):
        try:
            form = get_form(options["form_id"])
            questions = _extract_questions(form)
            title = form.get("info", {}).get("title")
            if not isinstance(title, str) or not title:
                raise GoogleFormsError("Google Forms API returned a form without a title.")
        except GoogleFormsError as error:
            raise CommandError(str(error)) from error

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
