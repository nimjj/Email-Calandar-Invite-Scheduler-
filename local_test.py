"""
local_test.py
─────────────
Interactive CLI harness for testing the Lambda handler locally.

Accepts meeting parameters as command-line arguments or interactive prompts,
builds the API Gateway proxy event dynamically, and invokes lambda_handler.

Usage (arguments)
-----------------
    python local_test.py --attendees nimithra@adept-tech.us alice@example.com \
                         --date 2026-07-20 --time 14:00 --duration 30 \
                         --location "Google Meet" --description "Sync-up call"

Usage (interactive)
-------------------
    python local_test.py

    The script will prompt for each field.
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def main() -> None:
    """Entry point for the local test harness."""

    # ── Force UTF-8 output on Windows consoles ───────────────────────────
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    # ── Force local-dev credential path ──────────────────────────────────
    os.environ.setdefault("LOCAL_DEV", "true")

    # ── Validate that credential env vars are present ────────────────────
    required_vars = ["CLIENT_ID", "CLIENT_SECRET", "REFRESH_TOKEN"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        print(
            "ERROR: The following environment variables must be set for "
            "local testing:\n"
        )
        for var in missing:
            print(f"  - {var}")
        print(
            "\nSet them in your shell or in a .env file sourced before "
            "running this script."
        )
        sys.exit(1)

    # ── Gather meeting parameters ────────────────────────────────────────
    meeting = _parse_args_or_prompt()

    # ── Build the API Gateway proxy event ────────────────────────────────
    payload = {
        "attendees": meeting["attendees"],
        "date": meeting["date"],
        "start_time": meeting["start_time"],
        "duration_minutes": meeting["duration_minutes"],
        "location": meeting["location"],
        "description": meeting["description"],
    }

    event = {"body": json.dumps(payload)}

    print()
    print("+------------------------------------------------------+")
    print("|  Herbert AWS - Local Test Harness                     |")
    print("+------------------------------------------------------+")
    print(f"|  Attendees  : {', '.join(meeting['attendees'])}")
    print(f"|  Date       : {meeting['date']}")
    print(f"|  Time       : {meeting['start_time']}")
    print(f"|  Duration   : {meeting['duration_minutes']} minutes")
    print(f"|  Location   : {meeting['location']}")
    print(f"|  Description: {meeting['description']}")
    print("+------------------------------------------------------+")
    print()

    # ── Import handler *after* setting LOCAL_DEV ─────────────────────────
    from lambda_function import lambda_handler

    # ── Invoke ───────────────────────────────────────────────────────────
    print(">> Invoking lambda_handler ...\n")
    response = lambda_handler(event, None)

    # ── Pretty-print the response ────────────────────────────────────────
    status = response.get("statusCode", "???")
    body_raw = response.get("body", "{}")

    try:
        body = json.loads(body_raw) if isinstance(body_raw, str) else body_raw
    except json.JSONDecodeError:
        body = body_raw

    status_icon = "[OK]" if status == 200 else "[FAIL]"
    print(f"  {status_icon}  Status Code : {status}")
    print("  Response Body:")
    print(json.dumps(body, indent=2, ensure_ascii=False))
    print()


def _parse_args_or_prompt() -> dict:
    """Parse CLI arguments if provided, otherwise prompt interactively."""

    parser = argparse.ArgumentParser(
        description="Schedule a Google Calendar meeting via Herbert.",
        add_help=True,
    )
    parser.add_argument(
        "--attendees", nargs="+",
        help="Email addresses of attendees (space-separated).",
    )
    parser.add_argument("--date", help="Meeting date (YYYY-MM-DD).")
    parser.add_argument("--time", help="Start time (HH:MM, 24-hour).")
    parser.add_argument("--duration", type=int, help="Duration in minutes.")
    parser.add_argument("--location", help="Meeting location or link.")
    parser.add_argument("--description", help="Meeting description.")

    args = parser.parse_args()

    # If any argument was provided, use argument mode (prompt for missing).
    # If none were provided, go fully interactive.
    has_any_arg = any([
        args.attendees, args.date, args.time,
        args.duration, args.location, args.description,
    ])

    if has_any_arg:
        # Fill in missing args with prompts
        attendees = args.attendees or _prompt_list("Attendee email(s), comma-separated")
        date = args.date or input("  Date (YYYY-MM-DD): ").strip()
        start_time = args.time or input("  Start time (HH:MM): ").strip()
        duration = args.duration or int(input("  Duration (minutes): ").strip())
        location = args.location or input("  Location: ").strip()
        description = args.description or input("  Description: ").strip()
    else:
        # Fully interactive
        print()
        print("  No arguments provided -- entering interactive mode.")
        print("  ------------------------------------------------")
        attendees = _prompt_list("  Attendee email(s), comma-separated")
        date = input("  Date (YYYY-MM-DD): ").strip()
        start_time = input("  Start time (HH:MM): ").strip()
        duration = int(input("  Duration (minutes): ").strip())
        location = input("  Location: ").strip()
        description = input("  Description: ").strip()

    return {
        "attendees": attendees,
        "date": date,
        "start_time": start_time,
        "duration_minutes": duration,
        "location": location,
        "description": description,
    }


def _prompt_list(label: str) -> list[str]:
    """Prompt for a comma-separated list and return cleaned items."""
    raw = input(f"  {label}: ").strip()
    return [email.strip() for email in raw.split(",") if email.strip()]


if __name__ == "__main__":
    main()
