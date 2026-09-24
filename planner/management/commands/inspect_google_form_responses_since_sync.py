import json

from django.core.management.base import BaseCommand, CommandError

from planner.models import Form
from planner.services.google_forms import GoogleFormsError, get_form_responses

from ._raw_data import save_json
DEFAULT_FORM_ID = "1N6QRk-OwsVANBopI11X9NOQTPcTyGP6K8Ql-ocXbayI"


class Command(BaseCommand):
    help = "Retrieve and print responses submitted after a form's last sync time."

    def add_arguments(self, parser):
        parser.add_argument(
            "form_id",
            nargs="?",
            default=DEFAULT_FORM_ID,
            help=f"The Google Form ID to inspect (default: {DEFAULT_FORM_ID}).",
        )

    def handle(self, *args, **options):
        form_id = options["form_id"]
        try:
            form = Form.objects.get(google_form_id=form_id)
        except Form.DoesNotExist as error:
            raise CommandError(
                f"No Form record exists with Google Form ID '{form_id}'."
            ) from error

        if form.last_synced_at is None:
            raise CommandError(
                f"Form '{form.name}' does not have a last_synced_at value."
            )

        try:
            data = get_form_responses(form.google_form_id, form.last_synced_at)
        except GoogleFormsError as error:
            raise CommandError(str(error)) from error

        self.stdout.write(json.dumps(data, indent=2, ensure_ascii=False))
        output_path = save_json(data, form.google_form_id, suffix="_responses_since_sync")
        self.stderr.write(f"Saved raw JSON to {output_path}")
