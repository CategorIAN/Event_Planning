"""Shared OAuth credentials for Google Workspace integrations."""

from pathlib import Path

from django.conf import settings
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


FORMS_READONLY_SCOPE = "https://www.googleapis.com/auth/forms.body.readonly"
FORMS_RESPONSES_READONLY_SCOPE = "https://www.googleapis.com/auth/forms.responses.readonly"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
SCOPES = [FORMS_READONLY_SCOPE, FORMS_RESPONSES_READONLY_SCOPE, GMAIL_SEND_SCOPE]
AUTHORIZATION_COMMAND = "python manage.py authorize_google_integrations"


class GoogleAuthorizationError(Exception):
    """Raised when the shared Google OAuth token cannot authorize an integration."""


def get_authorized_credentials() -> Credentials:
    """Load and refresh the shared token without starting interactive OAuth."""
    token_path = _token_path()
    if not token_path.is_file():
        raise GoogleAuthorizationError(
            f"No authorized Google token was found. Run '{AUTHORIZATION_COMMAND}'."
        )

    try:
        credentials = Credentials.from_authorized_user_file(token_path)
    except (OSError, ValueError) as error:
        raise GoogleAuthorizationError(
            f"The authorized Google token could not be read. Run '{AUTHORIZATION_COMMAND}'."
        ) from error

    if not set(SCOPES).issubset(credentials.scopes or []):
        raise GoogleAuthorizationError(
            "The authorized Google token is missing required integration scopes. "
            f"Run '{AUTHORIZATION_COMMAND}' to re-authorize it."
        )

    try:
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            token_path.write_text(credentials.to_json(), encoding="utf-8")
    except (OSError, RefreshError, ValueError) as error:
        raise GoogleAuthorizationError(
            f"Google token refresh failed. Run '{AUTHORIZATION_COMMAND}' to re-authorize."
        ) from error

    if not credentials.valid:
        raise GoogleAuthorizationError(
            f"The Google token is no longer valid. Run '{AUTHORIZATION_COMMAND}'."
        )
    return credentials


def authorize_google_integrations() -> None:
    """Run the installed-app flow and save one token with every integration scope."""
    credentials_path = _credentials_path()
    if not credentials_path.is_file():
        raise GoogleAuthorizationError(
            f"OAuth client credentials were not found at {credentials_path}."
        )

    try:
        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
        credentials = flow.run_local_server(port=0)
        _token_path().write_text(credentials.to_json(), encoding="utf-8")
    except (OSError, ValueError) as error:
        raise GoogleAuthorizationError("Google OAuth authorization failed.") from error


def _credentials_path() -> Path:
    return Path(settings.BASE_DIR) / "credentials.json"


def _token_path() -> Path:
    return Path(settings.BASE_DIR) / "token.json"
