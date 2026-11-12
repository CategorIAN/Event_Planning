import json
from pathlib import Path
from typing import Any

from django.conf import settings


def save_json(data: Any, form_id: str, suffix: str = "") -> Path:
    """Write formatted JSON to the project's raw_data directory.

    Creates the directory if needed and overwrites the destination if it
    already exists.

    Args:
        data: Value that can be serialized by json.dumps.
        form_id: Google Form ID used in the filename. Characters other
            than letters, digits, hyphens, and underscores become underscores.
        suffix: Optional text appended before ".json". Use filename-safe text.

    Returns:
        The path to the written JSON file.

    Raises:
        TypeError: If data contains an unsupported JSON value.
        OSError: If the directory cannot be created or the file cannot be written.
    """
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
