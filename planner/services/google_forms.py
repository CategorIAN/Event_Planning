"""Local-development access to Google Forms definitions."""

from datetime import datetime, timezone
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from planner.services.google_auth import (
    FORMS_READONLY_SCOPE,
    FORMS_RESPONSES_READONLY_SCOPE,
    GoogleAuthorizationError,
    SCOPES,
    get_authorized_credentials,
)


class GoogleFormsError(Exception):
    """Base exception for Google Forms service failures."""


class GoogleFormsCredentialsError(GoogleFormsError):
    """Raised when OAuth client credentials cannot be found or read."""


class GoogleFormsAuthenticationError(GoogleFormsError):
    """Raised when OAuth authorization cannot be completed."""


class GoogleFormsRetrievalError(GoogleFormsError):
    """Raised when a form cannot be retrieved or its response is invalid."""


def get_forms_service():
    """Return an authenticated Google Forms API v1 service client."""
    try:
        credentials = get_authorized_credentials()
    except GoogleAuthorizationError as error:
        raise GoogleFormsAuthenticationError(
            str(error)
        ) from error
    return build("forms", "v1", credentials=credentials, cache_discovery=False)


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


def get_form_responses(
    form_id: str, submitted_after: datetime | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Retrieve every submitted response for a Google Form without altering answers."""
    if not form_id:
        raise GoogleFormsRetrievalError("A Google Form ID is required.")

    response_filter = _response_filter(submitted_after) if submitted_after else None
    service = get_forms_service()
    responses: list[dict[str, Any]] = []
    page_token = None

    try:
        while True:
            request_arguments = {"formId": form_id}
            if response_filter:
                request_arguments["filter"] = response_filter
            if page_token:
                request_arguments["pageToken"] = page_token

            page = service.forms().responses().list(**request_arguments).execute()
            if not isinstance(page, dict):
                raise GoogleFormsRetrievalError(
                    "Google Forms API returned an unexpected responses response."
                )

            page_responses = page.get("responses", [])
            if not isinstance(page_responses, list) or not all(
                isinstance(response, dict) for response in page_responses
            ):
                raise GoogleFormsRetrievalError(
                    "Google Forms API returned invalid form responses."
                )
            responses.extend(page_responses)

            page_token = page.get("nextPageToken")
            if page_token is None:
                break
            if not isinstance(page_token, str) or not page_token:
                raise GoogleFormsRetrievalError(
                    "Google Forms API returned an invalid next page token."
                )
    except HttpError as error:
        if error.resp.status in {403, 404}:
            raise GoogleFormsRetrievalError(
                "The Google Form was not found or the authorized account cannot access its responses."
            ) from error
        raise GoogleFormsRetrievalError(
            f"Google Forms API response request failed with status {error.resp.status}."
        ) from error

    return {"responses": responses}


def _response_filter(submitted_after: datetime) -> str:
    if submitted_after.tzinfo is None:
        raise GoogleFormsRetrievalError(
            "The submitted-after timestamp must include timezone information."
        )

    timestamp = submitted_after.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return f"timestamp > {timestamp}"


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
