from dotenv import load_dotenv
load_dotenv()

import os
from supabase import create_client

from datetime import datetime, timezone
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse

from google_auth_oauthlib.flow import Flow
from fastapi.responses import RedirectResponse

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

GOOGLE_CLIENT_ID = os.getenv("CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("CLIENT_SECRET")
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI")

app = FastAPI()

def supabase_client():
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )

@app.get("/health")
def health():
    missing = []
    for k in [
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "CLIENT_ID",
        "CLIENT_SECRET",
        "OAUTH_REDIRECT_URI",
    ]:
        if not os.getenv(k):
            missing.append(k)
    return {"ok": len(missing) == 0, "missing": missing}


@app.get("/callback")
def callback(code: str, state: str):
    s = supabase_client()

    # 1) Validate connect ticket (state == connect_id)
    ticket = (
        s.table("oauth_connect_requests")
        .select("discord_user_id, expires_at")
        .eq("connect_id", state)
        .limit(1)
        .execute()
    )
    if not ticket.data:
        return HTMLResponse("<h3>Invalid connect link.</h3>", status_code=400)

    row = ticket.data[0]
    expires_at = row["expires_at"]
    exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    if exp < datetime.now(timezone.utc):
        return HTMLResponse("<h3>Connect link expired. Re-run /gcal connect.</h3>", status_code=400)

    discord_user_id = int(row["discord_user_id"])

    # 2) Exchange code for tokens
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [OAUTH_REDIRECT_URI],
            }
        },
        scopes=SCOPES,
        redirect_uri=OAUTH_REDIRECT_URI,
    )
    flow.fetch_token(code=code)
    creds = flow.credentials

    refresh_token = creds.refresh_token
    if not refresh_token:
        return HTMLResponse(
            "<h3>No refresh_token returned.</h3>"
            "<p>Fix: revoke the app in your Google Account (Security → Third-party access), then reconnect.</p>",
            status_code=400,
        )

    # 3) Store refresh_token in your existing table
    s.table("google_connections").upsert(
        {"discord_user_id": discord_user_id, "refresh_token": refresh_token},
        on_conflict="discord_user_id",
    ).execute()

    # 4) (Recommended) Delete the one-time ticket
    s.table("oauth_connect_requests").delete().eq("connect_id", state).execute()

    return HTMLResponse("<h2>Google Calendar connected ✅</h2><p>You can close this tab.</p>")


@app.get("/auth")
def auth(connect_id: str = Query(...)):
    s = supabase_client()

    print("OAUTH_REDIRECT_URI =", OAUTH_REDIRECT_URI)

    res = (
        s.table("oauth_connect_requests")
        .select("discord_user_id, expires_at")
        .eq("connect_id", connect_id)
        .limit(1)
        .execute()
    )

    # res.data will be [] if nothing found
    if not res.data:
        return HTMLResponse("<h3>Invalid connect link.</h3>", status_code=400)

    row = res.data[0]
    # discord_user_id = row["discord_user_id"]
    expires_at = row["expires_at"] 

    exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    if exp < datetime.now(timezone.utc):
        return HTMLResponse("<h3>Connect link expired. Re-run /gcal connect.</h3>", status_code=400)
    
    # safety check for env vars
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or not OAUTH_REDIRECT_URI:
        return HTMLResponse("Missing Google OAuth env vars.", status_code=500)

    # Create the OAuth flow using the connect_id as state
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [OAUTH_REDIRECT_URI],
            }
        },
        scopes=SCOPES,
        redirect_uri=OAUTH_REDIRECT_URI,
    )

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=connect_id,  # IMPORTANT: reuse connect_id as OAuth state
    )

    return RedirectResponse(auth_url)