
"""Shared OAuth credentials for Google Workspace integrations."""

import os
from pathlib import Path

from django.conf import settings
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


FORMS_READONLY_SCOPE = "https://www.googleapis.com/auth/forms.body.readonly"
FORMS_RESPONSES_READONLY_SCOPE = "https://www.googleapis.com/auth/forms.responses.readonly"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"

SCOPES = [
    FORMS_READONLY_SCOPE,
    FORMS_RESPONSES_READONLY_SCOPE,
    GMAIL_SEND_SCOPE,
]

AUTHORIZATION_COMMAND = "python manage.py authorize_google_integrations"


class GoogleAuthorizationError(Exception):
    """Raised when the shared Google OAuth token cannot authorize an integration."""


def get_authorized_credentials() -> Credentials:
    """Load valid shared OAuth credentials without starting an OAuth browser flow.

    Loads the authorized-user token from ``token.json`` (or its configured
    override). If the token is expired and has a refresh token, refreshes it.
    Refreshed credentials are written back only when the token path is
    writable and is not a Render Secret File. If persistence is skipped, the
    refreshed credentials are still returned for the current process. If the
    token write raises ``OSError``, the function raises
    ``GoogleAuthorizationError`` instead.

    Returns:
        Valid credentials containing every configured integration scope.

    Raises:
        GoogleAuthorizationError: If the token is missing, unreadable, lacks a
            required scope, cannot be refreshed, or is not valid after refresh.
    """
    token_path = _token_path()

    if not token_path.is_file():
        raise GoogleAuthorizationError(
            f"No authorized Google token was found. Run '{AUTHORIZATION_COMMAND}'."
        )

    try:
        credentials = Credentials.from_authorized_user_file(str(token_path))
    except (OSError, ValueError) as error:
        raise GoogleAuthorizationError(
            "The authorized Google token could not be read."
        ) from error

    if not set(SCOPES).issubset(credentials.scopes or []):
        raise GoogleAuthorizationError(
            "The authorized Google token is missing required integration scopes. "
            f"Run '{AUTHORIZATION_COMMAND}' to re-authorize it."
        )

    try:
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())

            # Render Secret Files are read-only.
            # Persist refreshed credentials only for local development.
            if os.access(token_path, os.W_OK) and not str(token_path).startswith(
                "/etc/secrets/"
            ):
                token_path.write_text(
                    credentials.to_json(),
                    encoding="utf-8",
                )

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
    """Authorize Google integrations through the local installed-app OAuth flow.

    Loads OAuth client credentials from ``credentials.json`` (or its
    configured override), opens a local browser-based consent flow, and writes
    one authorized-user token containing every configured integration scope.

    Raises:
        GoogleAuthorizationError: If client credentials are missing or the
            OAuth flow or token write fails.
    """
    credentials_path = _credentials_path()

    if not credentials_path.is_file():
        raise GoogleAuthorizationError(
            f"OAuth client credentials were not found at {credentials_path}."
        )

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(credentials_path),
            SCOPES,
        )
        credentials = flow.run_local_server(port=0)
        _token_path().write_text(
            credentials.to_json(),
            encoding="utf-8",
        )
    except (OSError, ValueError) as error:
        raise GoogleAuthorizationError("Google OAuth authorization failed.") from error


def _credentials_path() -> Path:
    """Return the configured OAuth client-credentials file path.

    Returns:
        ``GOOGLE_CREDENTIALS_PATH`` when configured; otherwise the
        repository-root ``credentials.json`` path.
    """
    return Path(
        os.environ.get(
            "GOOGLE_CREDENTIALS_PATH",
            str(Path(settings.BASE_DIR) / "credentials.json"),
        )
    )


def _token_path() -> Path:
    """Return the configured authorized-user token file path.

    Returns:
        ``GOOGLE_TOKEN_PATH`` when configured; otherwise the repository-root
        ``token.json`` path.
    """
    return Path(
        os.environ.get(
            "GOOGLE_TOKEN_PATH",
            str(Path(settings.BASE_DIR) / "token.json"),
        )
    )
