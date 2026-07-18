"""
lambda_function.py
──────────────────
AWS Lambda handler that receives a Nutrient workflow webhook via API Gateway
(HTTP POST), parses meeting parameters from the JSON body, authenticates with
the Google Calendar API using dynamically-fetched OAuth credentials, and
creates a calendar event with email invitations sent to all attendees.

Designed for container-based Lambda deployment (Python 3.11 base image).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from secrets_manager import get_google_oauth_credentials

# ── Logging ──────────────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ── Constants ────────────────────────────────────────────────────────────────

GOOGLE_CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
CALENDAR_ID = "primary"
EVENT_TIMEZONE = "America/New_York"  # Default; override via payload if needed.


# ── Lambda entry point ───────────────────────────────────────────────────────


def lambda_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """AWS Lambda handler — API Gateway proxy integration.

    Parameters
    ----------
    event:
        API Gateway proxy event containing a JSON-encoded ``body``.
    context:
        Lambda runtime context (unused but required by the interface).

    Returns
    -------
    dict
        API Gateway proxy response with ``statusCode`` and ``body``.
    """
    try:
        # ── 1. Parse & validate incoming payload ─────────────────────────
        payload = _parse_body(event)
        meetings = _extract_meetings(payload)

        # ── 2. Authenticate with Google Calendar API ─────────────────────
        service = _build_calendar_service()

        # ── 3. Create calendar events ────────────────────────────────────
        created_events: list[dict[str, str]] = []
        for meeting in meetings:
            calendar_event = _build_event_resource(meeting)
            result = (
                service.events()
                .insert(
                    calendarId=CALENDAR_ID,
                    body=calendar_event,
                    sendUpdates="all",
                )
                .execute()
            )
            created_events.append(
                {
                    "event_id": result["id"],
                    "html_link": result.get("htmlLink", ""),
                    "start": meeting["start_iso"],
                    "end": meeting["end_iso"],
                }
            )
            logger.info("Created event %s → %s", result["id"], result.get("htmlLink"))

        return _success_response(
            {
                "message": f"Successfully created {len(created_events)} event(s).",
                "events": created_events,
            }
        )

    except (ValueError, KeyError, TypeError) as exc:
        logger.warning("Client error: %s", exc, exc_info=True)
        return _error_response(400, f"Bad request: {exc}")

    except HttpError as exc:
        logger.error("Google API error: %s", exc, exc_info=True)
        return _error_response(502, f"Google Calendar API error: {exc}")

    except Exception as exc:  # noqa: BLE001
        logger.error("Unhandled error: %s", exc, exc_info=True)
        return _error_response(500, f"Internal server error: {exc}")


# ── Payload parsing ─────────────────────────────────────────────────────────


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    """Extract and deserialize the JSON body from the API Gateway event."""
    raw_body = event.get("body")
    if raw_body is None:
        raise ValueError("Event is missing 'body'.")

    if isinstance(raw_body, str):
        try:
            return json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Body is not valid JSON: {exc}") from exc

    if isinstance(raw_body, dict):
        return raw_body

    raise ValueError(f"Unexpected body type: {type(raw_body).__name__}")


def _extract_meetings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize payload into a list of individual meeting descriptors.

    If ``suggested_times`` is present and non-empty, one event is created per
    suggestion, each inheriting the shared attendees / location / description.
    Otherwise a single event is produced from the top-level fields.
    """
    # ── Shared fields (required) ─────────────────────────────────────────
    attendees = payload.get("attendees")
    if not attendees or not isinstance(attendees, list):
        raise ValueError("'attendees' must be a non-empty list of email strings.")

    duration_minutes = payload.get("duration_minutes")
    if duration_minutes is None:
        raise ValueError("'duration_minutes' is required.")
    duration_minutes = int(duration_minutes)

    location = payload.get("location", "")
    description = payload.get("description", "")
    timezone = payload.get("timezone", EVENT_TIMEZONE)

    # ── Build time slots ─────────────────────────────────────────────────
    suggested_times: list[dict[str, str]] = payload.get("suggested_times") or []

    if suggested_times:
        slots = [
            {
                "date": slot["date"],
                "start_time": slot["start_time"],
            }
            for slot in suggested_times
        ]
    else:
        # Fall back to the single top-level date/start_time.
        date = payload.get("date")
        start_time = payload.get("start_time")
        if not date or not start_time:
            raise ValueError(
                "'date' and 'start_time' are required when 'suggested_times' "
                "is absent."
            )
        slots = [{"date": date, "start_time": start_time}]

    # ── Assemble meeting descriptors ─────────────────────────────────────
    meetings: list[dict[str, Any]] = []
    for slot in slots:
        start_iso, end_iso = _compute_iso_times(
            slot["date"], slot["start_time"], duration_minutes
        )
        meetings.append(
            {
                "attendees": attendees,
                "start_iso": start_iso,
                "end_iso": end_iso,
                "timezone": timezone,
                "location": location,
                "description": description,
            }
        )

    return meetings


def _compute_iso_times(
    date_str: str,
    time_str: str,
    duration_minutes: int,
) -> tuple[str, str]:
    """Return (start_iso, end_iso) datetime strings in ISO-8601 format."""
    start_dt = datetime.fromisoformat(f"{date_str}T{time_str}:00")
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    return start_dt.isoformat(), end_dt.isoformat()


# ── Google Calendar helpers ──────────────────────────────────────────────────


def _build_calendar_service():
    """Authenticate and return a Google Calendar API service instance."""
    creds_data = get_google_oauth_credentials()

    credentials = Credentials(
        token=None,  # Force a refresh on first call.
        refresh_token=creds_data["refresh_token"],
        token_uri=GOOGLE_TOKEN_URI,
        client_id=creds_data["client_id"],
        client_secret=creds_data["client_secret"],
        scopes=GOOGLE_CALENDAR_SCOPES,
    )

    return build("calendar", "v3", credentials=credentials)


def _build_event_resource(meeting: dict[str, Any]) -> dict[str, Any]:
    """Construct a Google Calendar Event resource object."""
    return {
        "summary": "Scheduled Meeting",
        "location": meeting["location"],
        "description": meeting["description"],
        "start": {
            "dateTime": meeting["start_iso"],
            "timeZone": meeting["timezone"],
        },
        "end": {
            "dateTime": meeting["end_iso"],
            "timeZone": meeting["timezone"],
        },
        "attendees": [{"email": email} for email in meeting["attendees"]],
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email", "minutes": 60},
                {"method": "popup", "minutes": 15},
            ],
        },
        "guestsCanModify": False,
        "guestsCanInviteOthers": True,
        "guestsCanSeeOtherGuests": True,
    }


# ── Response builders ────────────────────────────────────────────────────────


def _success_response(body: dict[str, Any]) -> dict[str, Any]:
    """Build a 200 API Gateway proxy response."""
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _error_response(status_code: int, message: str) -> dict[str, Any]:
    """Build an error API Gateway proxy response."""
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": message}),
    }
