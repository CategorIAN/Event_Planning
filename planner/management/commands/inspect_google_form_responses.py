import json

from django.core.management.base import BaseCommand, CommandError

from planner.services.google_forms import GoogleFormsError, get_form_responses

from ._raw_data import save_json


DEFAULT_FORM_ID = "1N6QRk-OwsVANBopI11X9NOQTPcTyGP6K8Ql-ocXbayI"


class Command(BaseCommand):
    help = "Retrieve and print all Google Form responses as raw JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "form_id",
            nargs="?",
            default=DEFAULT_FORM_ID,
            help=f"The Google Form ID to inspect (default: {DEFAULT_FORM_ID}).",
        )

    def handle(self, *args, **options):
        try:
            data = get_form_responses(options["form_id"])
        except GoogleFormsError as error:
            raise CommandError(str(error)) from error

        self.stdout.write(json.dumps(data, indent=2, ensure_ascii=False))
        output_path = save_json(data, options["form_id"], suffix="_responses")
        self.stderr.write(f"Saved raw JSON to {output_path}")
