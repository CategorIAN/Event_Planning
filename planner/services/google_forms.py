"""Local-development access to Google Forms definitions."""

from pathlib import Path
from typing import Any

from django.conf import settings
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


FORMS_READONLY_SCOPE = "https://www.googleapis.com/auth/forms.body.readonly"
SCOPES = [FORMS_READONLY_SCOPE]


class GoogleFormsError(Exception):
    """Base exception for Google Forms service failures."""


class GoogleFormsCredentialsError(GoogleFormsError):
    """Raised when OAuth client credentials cannot be found or read."""


class GoogleFormsAuthenticationError(GoogleFormsError):
    """Raised when OAuth authorization cannot be completed."""


class GoogleFormsRetrievalError(GoogleFormsError):
    """Raised when a form cannot be retrieved or its response is invalid."""


def _credentials_path() -> Path:
    return Path(settings.BASE_DIR) / "credentials.json"


def _token_path() -> Path:
    return Path(settings.BASE_DIR) / "token.json"


def get_forms_service():
    """Return an authenticated Google Forms API v1 service client."""
    credentials_path = _credentials_path()
    token_path = _token_path()

    if not credentials_path.is_file():
        raise GoogleFormsCredentialsError(
            f"OAuth client credentials were not found at {credentials_path}. "
            "Download a Desktop app OAuth client JSON file and save it there."
        )

    credentials = None
    if token_path.is_file():
        try:
            credentials = Credentials.from_authorized_user_file(token_path, SCOPES)
        except (OSError, ValueError) as error:
            raise GoogleFormsAuthenticationError(
                f"Could not read the saved OAuth token at {token_path}. "
                "Delete it and authenticate again."
            ) from error

    try:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())

        if not credentials or not credentials.valid:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            credentials = flow.run_local_server(port=0)
            token_path.write_text(credentials.to_json(), encoding="utf-8")

        return build("forms", "v1", credentials=credentials, cache_discovery=False)
    except (OSError, ValueError, RefreshError) as error:
        raise GoogleFormsAuthenticationError(
            "Google OAuth authentication failed. Verify credentials.json, then try again."
        ) from error


def get_form(form_id: str) -> dict[str, Any]:
    """Retrieve a Google Form definition by its Google Forms ID."""
    if not form_id:
        raise GoogleFormsRetrievalError("A Google Form ID is required.")

    try:
        form = get_forms_service().forms().get(formId=form_id).execute()
    except HttpError as error:
        if error.resp.status in {403, 404}:
            raise GoogleFormsRetrievalError(
                "The Google Form was not found or the authorized account cannot access it."
            ) from error
        raise GoogleFormsRetrievalError(
            f"Google Forms API request failed with status {error.resp.status}."
        ) from error

    if not isinstance(form, dict):
        raise GoogleFormsRetrievalError("Google Forms API returned an unexpected form response.")
    return form


def get_form_questions(form_id: str) -> list[dict[str, str | None]]:
    """Return the normal and grid-row questions in a Google Form."""
    return _extract_questions(get_form(form_id))


def _extract_questions(form: dict[str, Any]) -> list[dict[str, str | None]]:
    items = form.get("items", [])
    if not isinstance(items, list):
        raise GoogleFormsRetrievalError("Google Forms API returned invalid form items.")

    questions: list[dict[str, str | None]] = []
    for item in items:
        if not isinstance(item, dict):
            raise GoogleFormsRetrievalError("Google Forms API returned an invalid form item.")

        item_id = item.get("itemId")
        if item_id is not None and not isinstance(item_id, str):
            raise GoogleFormsRetrievalError("Google Forms API returned an invalid item ID.")

        question_item = item.get("questionItem")
        if question_item is not None:
            if not isinstance(question_item, dict):
                raise GoogleFormsRetrievalError("Google Forms API returned an invalid question item.")
            question = question_item.get("question")
            if question is None:
                raise GoogleFormsRetrievalError(
                    "Google Forms API returned a question item without a question."
                )
            questions.append(_question_data(question, item.get("title"), item_id))
            continue

        question_group = item.get("questionGroupItem")
        if question_group is None:
            continue
        if not isinstance(question_group, dict):
            raise GoogleFormsRetrievalError("Google Forms API returned an invalid question group.")

        group_questions = question_group.get("questions")
        if not isinstance(group_questions, list):
            raise GoogleFormsRetrievalError("Google Forms API returned invalid grid questions.")
        for question in group_questions:
            row_title = question.get("rowQuestion", {}).get("title") if isinstance(question, dict) else None
            questions.append(_question_data(question, row_title or item.get("title"), item_id))

    return questions


def _question_data(
    question: Any, title: Any, item_id: str | None
) -> dict[str, str | None]:
    if not isinstance(question, dict):
        raise GoogleFormsRetrievalError("Google Forms API returned an invalid question.")

    question_id = question.get("questionId")
    if not isinstance(question_id, str) or not question_id:
        raise GoogleFormsRetrievalError("Google Forms API returned a question without an ID.")
    if title is not None and not isinstance(title, str):
        raise GoogleFormsRetrievalError("Google Forms API returned a question with an invalid title.")

    return {
        "google_question_id": question_id,
        "title": title,
        "google_item_id": item_id,
        "question_type": _question_type(question),
    }


def _question_type(question: dict[str, Any]) -> str | None:
    question_types = {
        "choiceQuestion": "choice",
        "textQuestion": "text",
        "scaleQuestion": "scale",
        "dateQuestion": "date",
        "timeQuestion": "time",
        "fileUploadQuestion": "file_upload",
        "rowQuestion": "grid_row",
        "ratingQuestion": "rating",
    }
    for field_name, label in question_types.items():
        if field_name in question:
            return label
    return None
