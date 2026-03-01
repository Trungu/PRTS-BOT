from __future__ import annotations

# DATABASE IMPORTS
from utils.gcal_db import create_connect_request, get_refresh_token
from utils.gcal_db import set_selected_calendars, get_selected_calendars
import asyncio

from datetime import datetime, timedelta, timezone
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# DISCORD IMPORTS
import discord
import os
# from dotenv import load_dotenv
from discord import app_commands
from discord.ext import commands

# load_dotenv()

# CONFIG
OAUTH_BASE_URL = os.getenv("OAUTH_BASE_URL")
SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_URI = "https://oauth2.googleapis.com/token"


class GCal(commands.GroupCog, group_name="gcal"):
    """Google Calendar commands (connect only, for now)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot


    @staticmethod
    def _event_time_display(ev: dict) -> str:
        start = ev.get("start", {})
        dt = start.get("dateTime")
        if dt:
            parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            unix = int(parsed.timestamp())
            return f"<t:{unix}:f>  (<t:{unix}:R>)"

        # all-day
        d = start.get("date")
        if d:
            return f"All-day ({d})"

        return "Unknown time"

    @staticmethod
    def _parse_iso_datetime(raw: str) -> datetime:
        # Accept both "...Z" and full ISO-8601 offsets.
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Datetime must include a timezone offset, e.g. +00:00 or Z.")
        return parsed

    @staticmethod
    def _build_service(refresh_token: str):
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=TOKEN_URI,
            client_id=os.environ["CLIENT_ID"],
            client_secret=os.environ["CLIENT_SECRET"],
            scopes=SCOPES,
        )
        creds.refresh(Request())
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    async def _get_service_for_user(self, discord_user_id: int):
        rt = await asyncio.to_thread(get_refresh_token, discord_user_id)
        if not rt:
            return None, "You are not connected. Run `/gcal connect` first."
        try:
            service = await asyncio.to_thread(self._build_service, rt)
            return service, None
        except Exception as e:
            return None, f"Failed to authenticate with Google Calendar: {e}"

    async def _resolve_default_calendar(self, discord_user_id: int) -> str:
        selected = await asyncio.to_thread(get_selected_calendars, discord_user_id)
        if selected:
            return selected[0]
        return "primary"


    @app_commands.command(name="connect", description="Connect your Google Calendar")
    async def connect(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        if not OAUTH_BASE_URL:
            await interaction.followup.send("OAuth server is not configured.", ephemeral=True)
            return

        # IMPORTANT: create + store connect_id in DB
        connect_id = await asyncio.to_thread(create_connect_request, interaction.user.id)

        link = f"Please connect your Google Calendar using this link: {OAUTH_BASE_URL.rstrip('/')}/auth?connect_id={connect_id}"
        await interaction.followup.send(link, ephemeral=True)


    @app_commands.command(name="add_event", description="Add a Google Calendar event")
    @app_commands.describe(
        title="Event title",
        start_iso="Start datetime ISO-8601 (e.g. 2026-03-03T15:00:00-06:00)",
        end_iso="End datetime ISO-8601 (e.g. 2026-03-03T16:00:00-06:00)",
        description="Optional description",
        location="Optional location",
        reminder_minutes="Optional reminder minutes before start (e.g. 10,60)",
        calendar_id="Optional calendar ID (defaults to first selected or primary)",
    )
    async def add_event(
        self,
        interaction: discord.Interaction,
        title: str,
        start_iso: str,
        end_iso: str,
        description: str | None = None,
        location: str | None = None,
        reminder_minutes: str | None = None,
        calendar_id: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            start_dt = self._parse_iso_datetime(start_iso)
            end_dt = self._parse_iso_datetime(end_iso)
            if end_dt <= start_dt:
                await interaction.followup.send("`end_iso` must be after `start_iso`.", ephemeral=True)
                return
        except ValueError as e:
            await interaction.followup.send(f"Invalid datetime: {e}", ephemeral=True)
            return

        reminder_overrides: list[dict] | None = None
        if reminder_minutes:
            try:
                mins = sorted(
                    {
                        int(v.strip())
                        for v in reminder_minutes.split(",")
                        if v.strip()
                    }
                )
            except ValueError:
                await interaction.followup.send(
                    "Invalid `reminder_minutes`. Use comma-separated integers like `10,60`.",
                    ephemeral=True,
                )
                return

            if not mins or any(m < 0 for m in mins):
                await interaction.followup.send(
                    "`reminder_minutes` must contain non-negative integers.",
                    ephemeral=True,
                )
                return

            reminder_overrides = [{"method": "popup", "minutes": m} for m in mins]

        service, auth_error = await self._get_service_for_user(interaction.user.id)
        if not service:
            await interaction.followup.send(auth_error, ephemeral=True)
            return

        target_calendar = calendar_id or await self._resolve_default_calendar(interaction.user.id)

        event_body = {
            "summary": title,
            "start": {"dateTime": start_dt.isoformat()},
            "end": {"dateTime": end_dt.isoformat()},
        }
        if description:
            event_body["description"] = description
        if location:
            event_body["location"] = location
        if reminder_overrides is not None:
            event_body["reminders"] = {"useDefault": False, "overrides": reminder_overrides}

        def create_event():
            return service.events().insert(calendarId=target_calendar, body=event_body).execute()

        try:
            created = await asyncio.to_thread(create_event)
        except HttpError as e:
            status = getattr(e.resp, "status", "unknown")
            await interaction.followup.send(
                f"Google Calendar rejected the request ({status}). "
                "Reconnect with `/gcal connect` to grant write scope, then try again.",
                ephemeral=True,
            )
            return
        except Exception as e:
            await interaction.followup.send(f"Failed to create event: {e}", ephemeral=True)
            return

        event_id = created.get("id", "unknown")
        when = self._event_time_display(created)
        await interaction.followup.send(
            f"Created event ✅\nTitle: `{title}`\nWhen: {when}\nEvent ID: `{event_id}`\nCalendar: `{target_calendar}`",
            ephemeral=True,
        )


    @app_commands.command(name="remove_event", description="Delete a Google Calendar event by event ID")
    @app_commands.describe(
        event_id="Event ID to delete (shown by /gcal test or /gcal add_event)",
        calendar_id="Optional calendar ID (defaults to first selected or primary)",
    )
    async def remove_event(
        self,
        interaction: discord.Interaction,
        event_id: str,
        calendar_id: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        service, auth_error = await self._get_service_for_user(interaction.user.id)
        if not service:
            await interaction.followup.send(auth_error, ephemeral=True)
            return

        target_calendar = calendar_id or await self._resolve_default_calendar(interaction.user.id)

        def delete_event():
            return service.events().delete(calendarId=target_calendar, eventId=event_id).execute()

        try:
            await asyncio.to_thread(delete_event)
        except HttpError as e:
            status = getattr(e.resp, "status", None)
            if status == 404:
                await interaction.followup.send(
                    f"No event found with ID `{event_id}` in `{target_calendar}`.",
                    ephemeral=True,
                )
                return
            await interaction.followup.send(
                f"Google Calendar rejected the request ({status or 'unknown'}). "
                "Reconnect with `/gcal connect` to grant write scope, then try again.",
                ephemeral=True,
            )
            return
        except Exception as e:
            await interaction.followup.send(f"Failed to remove event: {e}", ephemeral=True)
            return

        await interaction.followup.send(
            f"Deleted event ✅\nEvent ID: `{event_id}`\nCalendar: `{target_calendar}`",
            ephemeral=True,
        )


    @app_commands.command(name="set_reminder", description="Set pop-up reminder minutes for an event")
    @app_commands.describe(
        event_id="Event ID to update",
        reminder_minutes="Comma-separated minutes before event start (e.g. 10,30,60)",
        calendar_id="Optional calendar ID (defaults to first selected or primary)",
    )
    async def set_reminder(
        self,
        interaction: discord.Interaction,
        event_id: str,
        reminder_minutes: str,
        calendar_id: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            mins = sorted(
                {
                    int(v.strip())
                    for v in reminder_minutes.split(",")
                    if v.strip()
                }
            )
        except ValueError:
            await interaction.followup.send(
                "Invalid `reminder_minutes`. Use comma-separated integers like `10,60`.",
                ephemeral=True,
            )
            return

        if not mins or any(m < 0 for m in mins):
            await interaction.followup.send(
                "`reminder_minutes` must contain non-negative integers.",
                ephemeral=True,
            )
            return

        service, auth_error = await self._get_service_for_user(interaction.user.id)
        if not service:
            await interaction.followup.send(auth_error, ephemeral=True)
            return

        target_calendar = calendar_id or await self._resolve_default_calendar(interaction.user.id)
        reminder_payload = {
            "reminders": {
                "useDefault": False,
                "overrides": [{"method": "popup", "minutes": m} for m in mins],
            }
        }

        def patch_event():
            return service.events().patch(
                calendarId=target_calendar,
                eventId=event_id,
                body=reminder_payload,
            ).execute()

        try:
            await asyncio.to_thread(patch_event)
        except HttpError as e:
            status = getattr(e.resp, "status", None)
            if status == 404:
                await interaction.followup.send(
                    f"No event found with ID `{event_id}` in `{target_calendar}`.",
                    ephemeral=True,
                )
                return
            await interaction.followup.send(
                f"Google Calendar rejected the request ({status or 'unknown'}). "
                "Reconnect with `/gcal connect` to grant write scope, then try again.",
                ephemeral=True,
            )
            return
        except Exception as e:
            await interaction.followup.send(f"Failed to set reminder: {e}", ephemeral=True)
            return

        mins_pretty = ", ".join(str(m) for m in mins)
        await interaction.followup.send(
            f"Reminder updated ✅\nEvent ID: `{event_id}`\nMinutes: `{mins_pretty}`\nCalendar: `{target_calendar}`",
            ephemeral=True,
        )


    @app_commands.command(name="calendars", description="Choose which calendars to use for reminders")
    async def calendars(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        rt = await asyncio.to_thread(get_refresh_token, interaction.user.id)
        if not rt:
            await interaction.followup.send("You are not connected. Run `/gcal connect` first.", ephemeral=True)
            return

        def fetch_calendar_options() -> tuple[list[discord.SelectOption], dict[str, tuple[str, str]]]:
            creds = Credentials(
                token=None,
                refresh_token=rt,
                token_uri=TOKEN_URI,
                client_id=os.environ["CLIENT_ID"],
                client_secret=os.environ["CLIENT_SECRET"],
                scopes=SCOPES,
            )
            creds.refresh(Request())
            service = build("calendar", "v3", credentials=creds, cache_discovery=False)

            items = service.calendarList().list().execute().get("items", [])

            # Prefer primary first, then owned/writer calendars.
            def score(c: dict) -> tuple[int, int]:
                # lower tuple sorts first
                primary_rank = 0 if c.get("primary") else 1
                role = c.get("accessRole") or ""
                role_rank = 0 if role in ("owner", "writer") else 1
                return (primary_rank, role_rank)

            items.sort(key=score)

            options: list[discord.SelectOption] = []
            index_to_calendar: dict[str, tuple[str, str]] = {}

            i = 0
            for c in items:
                if i >= 5:
                    break

                cal_id = c.get("id")
                name = c.get("summary") or cal_id
                if not cal_id or not name:
                    continue

                idx = str(i)
                label = name[:100]
                desc = ("Primary" if c.get("primary") else (c.get("accessRole") or ""))[:100] or None

                options.append(discord.SelectOption(label=label, value=idx, description=desc))
                index_to_calendar[idx] = (cal_id, name)
                i += 1

            return options, index_to_calendar

        try:
            options, index_to_calendar = await asyncio.to_thread(fetch_calendar_options)

        except Exception as e:
            await interaction.followup.send(f"Failed to load calendars: {e}", ephemeral=True)
            return

        if not options:
            await interaction.followup.send("No calendars found.", ephemeral=True)
            return
        
        # Show the select menu and display the options
        view = CalendarSelectView(
            owner_id=interaction.user.id,
            options=options,
            index_to_calendar=index_to_calendar,
        )

        await interaction.followup.send(
            "Pick calendars (showing up to 5):",
            view=view, 
            ephemeral=True
        )


    @app_commands.command(name="test", description="Test Google Calendar connection")
    async def test(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        rt = await asyncio.to_thread(get_refresh_token, interaction.user.id)
        if not rt:
            await interaction.followup.send("You are not connected. Run `/gcal connect` first.", ephemeral=True)
            return
        
        # Fetch selected calendars for this user (offload sync supabase call)
        # if no selection, default to ["primary"]
        selected = await asyncio.to_thread(get_selected_calendars, interaction.user.id)
        calendar_ids = selected or ["primary"]

        def fetch():
            creds = Credentials(
                token=None,
                refresh_token=rt,
                token_uri=TOKEN_URI,
                client_id=os.environ["CLIENT_ID"],
                client_secret=os.environ["CLIENT_SECRET"],
                scopes=SCOPES,
            )
            creds.refresh(Request())
            service = build("calendar", "v3", credentials=creds, cache_discovery=False)

            cal = service.calendars().get(calendarId="primary").execute()

            cals = service.calendarList().list().execute().get("items", [])
            print("[GCAL TEST] calendars:", [(c.get("summary"), c.get("id"), c.get("primary")) for c in cals])

            now = datetime.now(timezone.utc)
            time_min = now.isoformat().replace("+00:00", "Z")
            time_max = (now + timedelta(days=1)).isoformat().replace("+00:00", "Z")

            # debug
            # print("[GCAL TEST] calendar timeZone:", cal_tz)
            # print("[GCAL TEST] timeMin:", time_min)
            # print("[GCAL TEST] timeMax:", time_max)

            all_items: list[dict] = []

            for cal_id in calendar_ids:
                res = service.events().list(
                    calendarId=cal_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=10,   # per calendar
                ).execute()
                all_items.extend(res.get("items", []))

            # Sort merged events by start time (dateTime preferred, date for all-day)
            def start_key(ev: dict) -> str:
                start = ev.get("start", {})
                return start.get("dateTime") or start.get("date") or ""

            all_items.sort(key=start_key)

            return all_items[:10]  # show top 10 overall

        try:
            items = await asyncio.to_thread(fetch)
        except Exception as e:
            await interaction.followup.send(f"Failed to fetch events: {e}", ephemeral=True)
            return

        if not items:
            await interaction.followup.send("Connected ✅ No events in the next 24 hours.", ephemeral=True)
            return

       
        embed = discord.Embed(
            title="📅 Upcoming events",
            description=f"Showing up to {len(items)} events in the next 24 hours.",
        )

        for ev in items[:10]:
            title = ev.get("summary") or "Untitled"
            when = self._event_time_display(ev)
            event_id = ev.get("id", "unknown")

            # optional: show which calendar it came from if you add it later
            location = ev.get("location")
            extra = f"\n`ID: {event_id}`"
            if location:
                extra += f"\n📍 {location}"

            embed.add_field(
                name=title[:256],
                value=f"{when}{extra}",
                inline=False,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

        # await interaction.followup.send("\n".join(lines), ephemeral=True)


    @app_commands.command(name="status", description="Show Google Calendar connection/debug status")
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id
        rt = await asyncio.to_thread(get_refresh_token, user_id)
        selected = await asyncio.to_thread(get_selected_calendars, user_id)
        selected_display = ", ".join(selected) if selected else "primary (default)"

        if not rt:
            await interaction.followup.send(
                "\n".join(
                    [
                        "Google Calendar status:",
                        f"- discord_user_id: `{user_id}`",
                        "- refresh_token_in_db: `False`",
                        f"- selected_calendars: `{selected_display}`",
                        "- auth_check: `skipped (no token)`",
                    ]
                ),
                ephemeral=True,
            )
            return

        def auth_check() -> tuple[bool, str]:
            creds = Credentials(
                token=None,
                refresh_token=rt,
                token_uri=TOKEN_URI,
                client_id=os.environ["CLIENT_ID"],
                client_secret=os.environ["CLIENT_SECRET"],
                scopes=SCOPES,
            )
            creds.refresh(Request())
            service = build("calendar", "v3", credentials=creds, cache_discovery=False)
            primary = service.calendars().get(calendarId="primary").execute()
            summary = primary.get("summary", "primary")
            return True, f"ok (primary='{summary}')"

        try:
            ok, detail = await asyncio.to_thread(auth_check)
            auth_text = f"{ok} ({detail})"
        except Exception as e:
            auth_text = f"False ({e})"

        await interaction.followup.send(
            "\n".join(
                [
                    "Google Calendar status:",
                    f"- discord_user_id: `{user_id}`",
                    "- refresh_token_in_db: `True`",
                    f"- selected_calendars: `{selected_display}`",
                    f"- auth_check: `{auth_text}`",
                    f"- requested_scopes: `{', '.join(SCOPES)}`",
                ]
            ),
            ephemeral=True,
        )


class CalendarSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption], index_to_calendar: dict[str, tuple[str, str]]):
        # index_to_calendar maps "0" -> (calendar_id, calendar_name)
        self.index_to_calendar = index_to_calendar

        super().__init__(
            placeholder="Choose calendars for reminders (max 5 shown)",
            min_values=1,
            max_values=min(5, len(options)),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        # Only allow the user who opened the menu to interact
        view: CalendarSelectView = self.view  # type: ignore
        if interaction.user.id != view.owner_id:
            await interaction.response.send_message("This menu isn’t for you.", ephemeral=True)
            return

        chosen_ids: list[str] = []
        chosen_names: list[str] = []

        for idx in self.values:  # idx is "0".."4"
            cal_id, cal_name = self.index_to_calendar[idx]
            chosen_ids.append(cal_id)
            chosen_names.append(cal_name)

        # Save to DB (offload sync supabase call)
        await asyncio.to_thread(set_selected_calendars, interaction.user.id, chosen_ids)

        pretty = "\n".join(f"• {name}" for name in chosen_names)
        await interaction.response.send_message(
            f"Saved ✅ I’ll send reminders for:\n{pretty}",
            ephemeral=True,
        )

        self.disabled = True
        view.stop()

        if interaction.message:
            try:
                await interaction.message.edit(view=view)
            except discord.NotFound:
                pass


class CalendarSelectView(discord.ui.View):
    def __init__(self, owner_id: int, options: list[discord.SelectOption], index_to_calendar: dict[str, tuple[str, str]]):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        self.add_item(CalendarSelect(options, index_to_calendar))
        

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GCal(bot))
