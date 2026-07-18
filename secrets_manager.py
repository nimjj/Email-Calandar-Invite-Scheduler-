"""
secrets_manager.py
──────────────────
Utility module for retrieving Google OAuth credentials from AWS Secrets Manager.

The secret is expected to be a JSON string stored under a configurable secret
name (defaults to "herbert/google-oauth"). The JSON must contain exactly three
keys: client_id, client_secret, and refresh_token.

When running locally with the LOCAL_DEV environment variable set to "true",
the module falls back to reading the same three values from environment
variables instead of calling AWS.
"""

import json
import os
from typing import TypedDict

import boto3
from botocore.exceptions import ClientError


class OAuthCredentials(TypedDict):
    """Typed dictionary describing the expected credential shape."""

    client_id: str
    client_secret: str
    refresh_token: str


# ── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_SECRET_NAME = "herbert/google-oauth"
_DEFAULT_REGION = "us-east-1"

_REQUIRED_KEYS = {"client_id", "client_secret", "refresh_token"}


# ── Public API ───────────────────────────────────────────────────────────────


def get_google_oauth_credentials(
    secret_name: str | None = None,
    region_name: str | None = None,
) -> OAuthCredentials:
    """Return Google OAuth credentials from the appropriate source.

    Parameters
    ----------
    secret_name:
        Override the Secrets Manager secret name.  Ignored in local mode.
    region_name:
        Override the AWS region.  Ignored in local mode.

    Returns
    -------
    OAuthCredentials
        A dictionary with ``client_id``, ``client_secret``, and
        ``refresh_token``.

    Raises
    ------
    EnvironmentError
        If a required environment variable is missing in local mode.
    RuntimeError
        If the secret cannot be retrieved or is malformed.
    """
    if os.getenv("LOCAL_DEV", "").lower() == "true":
        return _load_from_environment()

    return _load_from_secrets_manager(
        secret_name=secret_name or os.getenv("SECRET_NAME", _DEFAULT_SECRET_NAME),
        region_name=region_name or os.getenv("AWS_REGION", _DEFAULT_REGION),
    )


# ── Private helpers ──────────────────────────────────────────────────────────


def _load_from_environment() -> OAuthCredentials:
    """Read credentials from environment variables (local development)."""
    missing = [
        key.upper()
        for key in _REQUIRED_KEYS
        if not os.getenv(key.upper())
    ]
    if missing:
        raise EnvironmentError(
            f"LOCAL_DEV mode: missing environment variable(s): {', '.join(sorted(missing))}"
        )

    return OAuthCredentials(
        client_id=os.environ["CLIENT_ID"],
        client_secret=os.environ["CLIENT_SECRET"],
        refresh_token=os.environ["REFRESH_TOKEN"],
    )


def _load_from_secrets_manager(
    secret_name: str,
    region_name: str,
) -> OAuthCredentials:
    """Fetch and parse the secret from AWS Secrets Manager."""
    client = boto3.client("secretsmanager", region_name=region_name)

    try:
        response = client.get_secret_value(SecretId=secret_name)
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        raise RuntimeError(
            f"Failed to retrieve secret '{secret_name}': {error_code} – {exc}"
        ) from exc

    secret_string = response.get("SecretString")
    if not secret_string:
        raise RuntimeError(
            f"Secret '{secret_name}' exists but contains no SecretString."
        )

    try:
        payload: dict = json.loads(secret_string)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Secret '{secret_name}' is not valid JSON: {exc}"
        ) from exc

    missing_keys = _REQUIRED_KEYS - payload.keys()
    if missing_keys:
        raise RuntimeError(
            f"Secret '{secret_name}' is missing required key(s): "
            f"{', '.join(sorted(missing_keys))}"
        )

    return OAuthCredentials(
        client_id=payload["client_id"],
        client_secret=payload["client_secret"],
        refresh_token=payload["refresh_token"],
    )
