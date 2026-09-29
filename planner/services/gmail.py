"""Gmail API access for future event-planner email workflows."""

import base64
from email.message import EmailMessage

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from planner.services.google_auth import GoogleAuthorizationError, get_authorized_credentials


class GmailError(Exception):
    """Base exception for Gmail service failures."""


class GmailAuthorizationError(GmailError):
    """Raised when the shared Google token cannot authorize Gmail."""


class GmailSendError(GmailError):
    """Raised when Gmail cannot send a message."""


def get_gmail_service():
    """Return an authorized Gmail API v1 client without interactive OAuth."""
    try:
        credentials = get_authorized_credentials()
    except GoogleAuthorizationError as error:
        raise GmailAuthorizationError(str(error)) from error
    return build("gmail", "v1", credentials=credentials)


def send_email(to_email: str, subject: str, body: str) -> str:
    """Send a plain-text email and return the Gmail message ID."""
    message = EmailMessage()
    message.set_content(body)
    message["To"] = to_email
    message["Subject"] = subject
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

    try:
        response = (
            get_gmail_service()
            .users()
            .messages()
            .send(userId="me", body={"raw": encoded_message})
            .execute()
        )
    except HttpError as error:
        raise GmailSendError(
            f"Gmail API send request failed with status {error.resp.status}."
        ) from error

    message_id = response.get("id") if isinstance(response, dict) else None
    if not isinstance(message_id, str) or not message_id:
        raise GmailSendError("Gmail API returned a response without a message ID.")
    return message_id
