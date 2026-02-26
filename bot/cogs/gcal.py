from __future__ import annotations

# DATABASE IMPORTS
from utils.gcal_db import create_connect_request, get_refresh_token
from utils.gcal_db import set_selected_calendars, get_selected_calendars
import asyncio

from datetime import datetime, timedelta, timezone
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# DISCORD IMPORTS
import discord
import os
# from dotenv import load_dotenv
from discord import app_commands
from discord.ext import commands

# load_dotenv()

# CONFIG
OAUTH_BASE_URL = os.getenv("OAUTH_BASE_URL")
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
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

            # optional: show which calendar it came from if you add it later
            location = ev.get("location")
            extra = f"\n📍 {location}" if location else ""

            embed.add_field(
                name=title[:256],
                value=f"{when}{extra}",
                inline=False,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

        # await interaction.followup.send("\n".join(lines), ephemeral=True)


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