from __future__ import annotations

from typing import Callable
from datetime import datetime, timedelta, timezone
from calendar import monthrange
import re
import os

from tools.toolcalls.calculator import calculator, TOOL_DEFINITION as _CALC_DEF
from tools.toolcalls.code_runner import (
    run_python,           TOOL_DEFINITION                as _CODE_DEF,
    list_workspace,       LIST_WORKSPACE_TOOL_DEFINITION  as _LIST_DEF,
    get_workspace_file,   GET_WORKSPACE_FILE_TOOL_DEFINITION as _GET_FILE_DEF,
)
from tools.toolcalls.terminal_runner import run_terminal, TOOL_DEFINITION as _TERM_DEF
from tools.toolcalls.unit_converter import unit_converter, TOOL_DEFINITION as _UNIT_DEF
from tools.toolcalls.safety_responder import (
    send_crisis_response, CRISIS_TOOL_DEFINITION       as _CRISIS_DEF,
    send_pr_deflection,   PR_DEFLECTION_TOOL_DEFINITION as _PR_DEF,
)


_GCAL_SCOPES = ["https://www.googleapis.com/auth/calendar"]
_TOKEN_URI = "https://oauth2.googleapis.com/token"


def _parse_iso_datetime(raw: str) -> datetime:
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        # LLMs occasionally generate invalid month-days (e.g., 2026-02-29).
        # Clamp day to the month maximum so calendar actions can still proceed.
        if "day is out of range for month" not in str(exc).lower():
            raise

        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(T.*)$", text)
        if not m:
            raise

        year = int(m.group(1))
        month = int(m.group(2))
        day = int(m.group(3))
        rest = m.group(4)

        max_day = monthrange(year, month)[1]
        fixed_day = min(max(day, 1), max_day)
        fixed_text = f"{year:04d}-{month:02d}-{fixed_day:02d}{rest}"
        parsed = datetime.fromisoformat(fixed_text)

    if parsed.tzinfo is None:
        raise ValueError("Datetime must include timezone offset (e.g. -06:00 or Z).")
    return parsed


def _build_gcal_service(discord_user_id: int):
    from utils.gcal_db import get_refresh_token
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    refresh_token = get_refresh_token(discord_user_id)
    if not refresh_token:
        raise ValueError("Google Calendar is not connected. Run /gcal connect first.")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=_TOKEN_URI,
        client_id=os.environ["CLIENT_ID"],
        client_secret=os.environ["CLIENT_SECRET"],
        scopes=_GCAL_SCOPES,
    )
    creds.refresh(Request())
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _selected_or_primary(discord_user_id: int) -> list[str]:
    from utils.gcal_db import get_selected_calendars

    selected = get_selected_calendars(discord_user_id)
    return selected or ["primary"]


def _default_calendar(discord_user_id: int, calendar_id: str | None) -> str:
    if calendar_id:
        return calendar_id
    return _selected_or_primary(discord_user_id)[0]


def _event_start(ev: dict) -> str:
    start = ev.get("start", {})
    return start.get("dateTime") or start.get("date") or "unknown"


def _event_line(ev: dict, calendar_id: str) -> str:
    event_id = ev.get("id", "unknown")
    title = ev.get("summary") or "Untitled"
    return f"id={event_id} | title={title!r} | start={_event_start(ev)} | calendar={calendar_id}"


def _find_events(
    service,
    calendar_ids: list[str],
    *,
    query: str,
    time_min: str,
    time_max: str,
    max_results: int,
) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    q = query.strip().lower()

    for cal_id in calendar_ids:
        res = service.events().list(
            calendarId=cal_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=max_results,
        ).execute()
        for ev in res.get("items", []):
            if not q:
                out.append((cal_id, ev))
                continue

            haystack = " ".join(
                [
                    str(ev.get("summary", "")),
                    str(ev.get("description", "")),
                    str(ev.get("location", "")),
                ]
            ).lower()
            if q in haystack:
                out.append((cal_id, ev))

    out.sort(key=lambda pair: _event_start(pair[1]))
    return out


def _resolve_event_for_update(
    service,
    discord_user_id: int,
    *,
    event_id: str | None,
    calendar_id: str | None,
    query: str | None,
    search_days: int,
) -> tuple[str, str]:
    if event_id:
        from googleapiclient.errors import HttpError

        if calendar_id:
            return calendar_id, event_id

        for cal_id in _selected_or_primary(discord_user_id):
            try:
                service.events().get(calendarId=cal_id, eventId=event_id).execute()
                return cal_id, event_id
            except HttpError as e:
                status = getattr(e.resp, "status", None)
                if status != 404:
                    raise
        raise ValueError(f"Event ID {event_id!r} was not found in your selected calendars.")

    if not query:
        raise ValueError("Provide either event_id or query.")

    now = datetime.now(timezone.utc)
    matches = _find_events(
        service,
        _selected_or_primary(discord_user_id),
        query=query,
        time_min=now.isoformat().replace("+00:00", "Z"),
        time_max=(now + timedelta(days=search_days)).isoformat().replace("+00:00", "Z"),
        max_results=10,
    )
    if not matches:
        raise ValueError(f"No events matched query={query!r}.")
    if len(matches) > 1:
        lines = "\n".join(f"- {_event_line(ev, cal_id)}" for cal_id, ev in matches[:5])
        raise ValueError(
            "Query matched multiple events. Be more specific or provide event_id.\n"
            f"Candidates:\n{lines}"
        )

    cal_id, ev = matches[0]
    return cal_id, ev.get("id", "")


def gcal_add_event(
    discord_user_id: int,
    title: str,
    start_iso: str,
    end_iso: str | None = None,
    duration_minutes: int = 60,
    description: str | None = None,
    location: str | None = None,
    reminder_minutes: list[int] | None = None,
    calendar_id: str | None = None,
) -> str:
    service = _build_gcal_service(discord_user_id)
    start_dt = _parse_iso_datetime(start_iso)

    if end_iso:
        end_dt = _parse_iso_datetime(end_iso)
    else:
        end_dt = start_dt + timedelta(minutes=max(duration_minutes, 1))

    if end_dt <= start_dt:
        raise ValueError("end_iso must be later than start_iso.")

    target_calendar = _default_calendar(discord_user_id, calendar_id)
    event_body: dict = {
        "summary": title,
        "start": {"dateTime": start_dt.isoformat()},
        "end": {"dateTime": end_dt.isoformat()},
    }

    if description:
        event_body["description"] = description
    if location:
        event_body["location"] = location
    if reminder_minutes is not None:
        clean = sorted({int(m) for m in reminder_minutes if int(m) >= 0})
        event_body["reminders"] = {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": m} for m in clean],
        }

    created = service.events().insert(calendarId=target_calendar, body=event_body).execute()
    return (
        "Created event successfully. "
        f"{_event_line(created, target_calendar)}"
    )


def gcal_find_events(
    discord_user_id: int,
    query: str = "",
    start_iso: str | None = None,
    end_iso: str | None = None,
    days_ahead: int = 7,
    max_results: int = 10,
    calendar_id: str | None = None,
) -> str:
    service = _build_gcal_service(discord_user_id)

    if start_iso:
        start_dt = _parse_iso_datetime(start_iso)
    else:
        start_dt = datetime.now(timezone.utc)

    if end_iso:
        end_dt = _parse_iso_datetime(end_iso)
    else:
        end_dt = start_dt + timedelta(days=max(days_ahead, 1))

    calendars = [calendar_id] if calendar_id else _selected_or_primary(discord_user_id)
    matches = _find_events(
        service,
        calendars,
        query=query,
        time_min=start_dt.isoformat().replace("+00:00", "Z"),
        time_max=end_dt.isoformat().replace("+00:00", "Z"),
        max_results=max(1, min(max_results, 25)),
    )

    if not matches:
        return "No matching calendar events found."

    lines = "\n".join(f"- {_event_line(ev, cal_id)}" for cal_id, ev in matches[: max_results])
    return f"Found {len(matches[: max_results])} event(s):\n{lines}"


def gcal_remove_event(
    discord_user_id: int,
    event_id: str | None = None,
    query: str | None = None,
    calendar_id: str | None = None,
    search_days: int = 30,
) -> str:
    service = _build_gcal_service(discord_user_id)
    target_calendar, resolved_event_id = _resolve_event_for_update(
        service,
        discord_user_id,
        event_id=event_id,
        calendar_id=calendar_id,
        query=query,
        search_days=search_days,
    )

    service.events().delete(calendarId=target_calendar, eventId=resolved_event_id).execute()
    return (
        "Deleted event successfully. "
        f"id={resolved_event_id} | calendar={target_calendar}"
    )


def gcal_set_reminder(
    discord_user_id: int,
    reminder_minutes: list[int],
    event_id: str | None = None,
    query: str | None = None,
    calendar_id: str | None = None,
    search_days: int = 30,
) -> str:
    service = _build_gcal_service(discord_user_id)
    if not reminder_minutes:
        raise ValueError("reminder_minutes cannot be empty.")

    target_calendar, resolved_event_id = _resolve_event_for_update(
        service,
        discord_user_id,
        event_id=event_id,
        calendar_id=calendar_id,
        query=query,
        search_days=search_days,
    )

    clean = sorted({int(m) for m in reminder_minutes if int(m) >= 0})
    if not clean:
        raise ValueError("reminder_minutes must contain at least one non-negative integer.")

    service.events().patch(
        calendarId=target_calendar,
        eventId=resolved_event_id,
        body={
            "reminders": {
                "useDefault": False,
                "overrides": [{"method": "popup", "minutes": m} for m in clean],
            }
        },
    ).execute()

    mins = ", ".join(str(m) for m in clean)
    return (
        "Updated reminder successfully. "
        f"id={resolved_event_id} | minutes={mins} | calendar={target_calendar}"
    )


GCAL_ADD_EVENT_TOOL_DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "gcal_add_event",
        "description": (
            "Create a Google Calendar event for a Discord user. "
            "Use for requests like 'add an event' or 'put this on my calendar'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "discord_user_id": {"type": "integer"},
                "title": {"type": "string"},
                "start_iso": {"type": "string"},
                "end_iso": {"type": "string"},
                "duration_minutes": {"type": "integer"},
                "description": {"type": "string"},
                "location": {"type": "string"},
                "reminder_minutes": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
                "calendar_id": {"type": "string"},
            },
            "required": ["discord_user_id", "title", "start_iso"],
            "additionalProperties": False,
        },
    },
}


GCAL_FIND_EVENTS_TOOL_DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "gcal_find_events",
        "description": (
            "Find calendar events by free-text query and/or date window, and return event IDs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "discord_user_id": {"type": "integer"},
                "query": {"type": "string"},
                "start_iso": {"type": "string"},
                "end_iso": {"type": "string"},
                "days_ahead": {"type": "integer"},
                "max_results": {"type": "integer"},
                "calendar_id": {"type": "string"},
            },
            "required": ["discord_user_id"],
            "additionalProperties": False,
        },
    },
}


GCAL_REMOVE_EVENT_TOOL_DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "gcal_remove_event",
        "description": (
            "Delete a Google Calendar event. Prefer event_id; can also resolve from query."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "discord_user_id": {"type": "integer"},
                "event_id": {"type": "string"},
                "query": {"type": "string"},
                "calendar_id": {"type": "string"},
                "search_days": {"type": "integer"},
            },
            "required": ["discord_user_id"],
            "additionalProperties": False,
        },
    },
}


GCAL_SET_REMINDER_TOOL_DEFINITION: dict = {
    "type": "function",
    "function": {
        "name": "gcal_set_reminder",
        "description": (
            "Set Google Calendar popup reminder minutes for an event."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "discord_user_id": {"type": "integer"},
                "reminder_minutes": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
                "event_id": {"type": "string"},
                "query": {"type": "string"},
                "calendar_id": {"type": "string"},
                "search_days": {"type": "integer"},
            },
            "required": ["discord_user_id", "reminder_minutes"],
            "additionalProperties": False,
        },
    },
}

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# Maps tool name → callable(arguments_dict) → str
TOOLS: dict[str, Callable[[dict], str]] = {
    "calculator":           lambda args: calculator(args["expression"]),
    "run_python":           lambda args: run_python(args["code"]),
    "list_workspace":       lambda args: list_workspace(),
    "get_workspace_file":   lambda args: get_workspace_file(args["filename"]),
    "run_terminal":         lambda args: run_terminal(args["command"]),
    "unit_converter":       lambda args: unit_converter(
                                args["value"], args["from_unit"], args["to_unit"]
                            ),
    "send_crisis_response": lambda args: send_crisis_response(),
    "send_pr_deflection":   lambda args: send_pr_deflection(args["topic"]),
    "gcal_add_event":       lambda args: gcal_add_event(
                                discord_user_id=int(args["discord_user_id"]),
                                title=args["title"],
                                start_iso=args["start_iso"],
                                end_iso=args.get("end_iso"),
                                duration_minutes=int(args.get("duration_minutes", 60)),
                                description=args.get("description"),
                                location=args.get("location"),
                                reminder_minutes=args.get("reminder_minutes"),
                                calendar_id=args.get("calendar_id"),
                            ),
    "gcal_find_events":     lambda args: gcal_find_events(
                                discord_user_id=int(args["discord_user_id"]),
                                query=args.get("query", ""),
                                start_iso=args.get("start_iso"),
                                end_iso=args.get("end_iso"),
                                days_ahead=int(args.get("days_ahead", 7)),
                                max_results=int(args.get("max_results", 10)),
                                calendar_id=args.get("calendar_id"),
                            ),
    "gcal_remove_event":    lambda args: gcal_remove_event(
                                discord_user_id=int(args["discord_user_id"]),
                                event_id=args.get("event_id"),
                                query=args.get("query"),
                                calendar_id=args.get("calendar_id"),
                                search_days=int(args.get("search_days", 30)),
                            ),
    "gcal_set_reminder":    lambda args: gcal_set_reminder(
                                discord_user_id=int(args["discord_user_id"]),
                                reminder_minutes=[int(v) for v in args["reminder_minutes"]],
                                event_id=args.get("event_id"),
                                query=args.get("query"),
                                calendar_id=args.get("calendar_id"),
                                search_days=int(args.get("search_days", 30)),
                            ),
}

# List of OpenAI-style tool definitions sent with every API request.
TOOL_DEFINITIONS: list[dict] = [
    _CALC_DEF,
    _CODE_DEF,
    _LIST_DEF,
    _GET_FILE_DEF,
    _TERM_DEF,
    _UNIT_DEF,
    _CRISIS_DEF,
    _PR_DEF,
    GCAL_ADD_EVENT_TOOL_DEFINITION,
    GCAL_FIND_EVENTS_TOOL_DEFINITION,
    GCAL_REMOVE_EVENT_TOOL_DEFINITION,
    GCAL_SET_REMINDER_TOOL_DEFINITION,
]
