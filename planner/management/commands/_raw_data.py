import json
from pathlib import Path
from typing import Any

from django.conf import settings


def save_json(data: Any, form_id: str, suffix: str = "") -> Path:
    """Save JSON inspection output under the project's ignored raw_data folder."""
    safe_form_id = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in form_id
    )
    output_directory = Path(settings.BASE_DIR) / "raw_data"
    output_directory.mkdir(exist_ok=True)
    output_path = output_directory / f"{safe_form_id}{suffix}.json"
    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output_path
