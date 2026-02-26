import uuid
from datetime import datetime, timedelta, timezone
from supabase import create_client
import os

# load_dotenv()
_supabase = None

def _client():
    global _supabase
    if _supabase is None:
        _supabase = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        )
    return _supabase


def create_connect_request(discord_user_id: int) -> str:
    """
    Create a short-lived OAuth connect ticket.
    Returns connect_id.
    """
    connect_id = str(uuid.uuid4())
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()

    _client().table("oauth_connect_requests").insert(
        {
            "connect_id": connect_id,
            "discord_user_id": discord_user_id,
            "expires_at": expires_at,
        }
    ).execute()

    return connect_id

def get_refresh_token(discord_user_id: int) -> str | None:
    res = (
        _client()
        .table("google_connections")
        .select("refresh_token")
        .eq("discord_user_id", discord_user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    return str(res.data[0]["refresh_token"])

def set_selected_calendars(discord_user_id: int, calendar_ids: list[str]) -> None:
    # Clear existing selections
    _client().table("google_calendar_selections").delete().eq(
        "discord_user_id", discord_user_id
    ).execute()

    if not calendar_ids:
        return

    rows = [{"discord_user_id": discord_user_id, "calendar_id": cid} for cid in calendar_ids]
    _client().table("google_calendar_selections").insert(rows).execute()


def get_selected_calendars(discord_user_id: int) -> list[str]:
    res = (
        _client()
        .table("google_calendar_selections")
        .select("calendar_id")
        .eq("discord_user_id", discord_user_id)
        .execute()
    )
    return [r["calendar_id"] for r in (res.data or [])]