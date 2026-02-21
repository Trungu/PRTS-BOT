# bot/cogs/admin.py — Admin-only mode commands and user ban management.
#
# Commands registered
# -------------------
#   admin only / admin on  — Enable admin-only mode (caller must be in admin.txt).
#   admin off              — Disable admin-only mode (caller must be in admin.txt).
#   ban <user>             — Ban a user from using the bot (admins only).
#   unban <user>           — Unban a previously banned user (admins only).
#   delete response        — Delete consecutive bot messages until a human message.
#   delete count <N>       — Delete the N most recent bot messages (admins only).
#   delete time <duration> — Delete bot messages from the last <duration> (admins only).
#
# All commands are gated behind the admin allowed-user list.

from __future__ import annotations

import datetime
import re
from typing import Any, cast

import discord
from discord.ext import commands

from bot.client import Bot
from utils.admin import (
    is_allowed,
    is_admin_only,
    reload_allowed_users,
    set_admin_only,
    ban_user,
    unban_user,
    is_banned,
)
from utils.logger import log, LogLevel


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------

def _parse_user_id(text: str) -> int | None:
    """Extract a Discord user ID from a raw mention or plain integer string.

    Accepts ``<@123456789>``, ``<@!123456789>`` (legacy mention), or a bare
    integer string.  Returns ``None`` if the text cannot be parsed.
    """
    text = text.strip()
    match = re.fullmatch(r"<@!?(\d+)>", text)
    if match:
        return int(match.group(1))
    try:
        return int(text)
    except ValueError:
        return None


def _parse_duration(text: str) -> int | None:
    """Parse a compact duration string into total seconds.

    Accepts any combination of ``h`` (hours), ``m`` (minutes), and ``s``
    (seconds) in any order.  Examples::

        "1h"       → 3600
        "30m"      → 1800
        "1h30m"    → 5400
        "1m1h"     → 3660
        "2h1m30s"  → 7290

    Returns the total number of seconds, or ``None`` if the string is empty,
    unparseable, or resolves to zero seconds.
    """
    text = text.strip()
    matches = re.findall(r"(\d+)([hms])", text)
    if not matches:
        return None
    # Verify the entire string was consumed — rejects formats like "5:00".
    if "".join(f"{n}{u}" for n, u in matches) != text:
        return None
    _UNIT_SECONDS: dict[str, int] = {"h": 3600, "m": 60, "s": 1}
    total = sum(int(n) * _UNIT_SECONDS[u] for n, u in matches)
    return total if total > 0 else None


async def _bulk_delete(channel: Any, messages: list[discord.Message]) -> None:
    """Delete *messages*, falling back to individual deletes for single-item batches.

    ``channel.delete_messages`` requires 2–100 items.  This helper handles
    the edge cases transparently.
    """
    if not messages:
        return
    for i in range(0, len(messages), 100):
        batch = messages[i : i + 100]
        if len(batch) == 1:
            await batch[0].delete()
        else:
            await channel.delete_messages(batch)


class AdminCog(commands.Cog):
    """Commands for managing admin-only mode."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        bot.register_command("admin only",      self._admin_only)
        bot.register_command("admin on",         self._admin_only)  # alias
        bot.register_command("admin off",        self._admin_off)
        bot.register_command("ban",              self._ban)
        bot.register_command("unban",            self._unban)
        bot.register_command("delete response",  self._delete_response)
        bot.register_command("delete count",     self._delete_count)
        bot.register_command("delete time",      self._delete_time)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _deny(self, message: discord.Message) -> None:
        """Send a standardised 'not authorised' reply."""
        await message.channel.send("⛔ You are not authorised to change admin settings.")

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _admin_only(self, message: discord.Message, _command: str) -> None:
        """Enable admin-only mode.

        The caller must be listed in admin.txt.  The allowed-user list is
        reloaded from disk before locking down so any recent edits are picked
        up immediately.
        """
        if not is_allowed(message.author.id):
            await self._deny(message)
            return

        reload_allowed_users()   # Refresh the list before locking down.
        set_admin_only(True)
        await message.channel.send(
            "🔒 Admin-only mode **enabled**. Only admins may use the bot."
        )
        log(
            f"[Admin] Admin-only mode enabled by {message.author} (id={message.author.id})",
            LogLevel.INFO,
        )

    async def _admin_off(self, message: discord.Message, _command: str) -> None:
        """Disable admin-only mode.

        The caller must be listed in admin.txt.
        """
        if not is_allowed(message.author.id):
            await self._deny(message)
            return

        set_admin_only(False)
        await message.channel.send(
            "🔓 Admin-only mode **disabled**. All users may use the bot."
        )
        log(
            f"[Admin] Admin-only mode disabled by {message.author} (id={message.author.id})",
            LogLevel.INFO,
        )


    async def _ban(self, message: discord.Message, command: str) -> None:
        """Ban a user from using the bot.

        Only users listed in admin.txt may issue this command.  Accepts a
        Discord mention (``<@123456789>``) or a raw user-ID integer.
        """
        if not is_allowed(message.author.id):
            await self._deny(message)
            return

        parts = command.strip().split(None, 1)
        if len(parts) < 2:
            await message.channel.send("Usage: `ban <@user>` or `ban <user_id>`")
            return

        user_id = _parse_user_id(parts[1])
        if user_id is None:
            await message.channel.send("⚠️ Could not parse a user ID from that input.")
            return

        ban_user(user_id)
        await message.channel.send(
            f"🔨 User `{user_id}` has been banned from using the bot."
        )
        log(
            f"[Admin] User {user_id} banned by {message.author} (id={message.author.id})",
            LogLevel.INFO,
        )

    async def _unban(self, message: discord.Message, command: str) -> None:
        """Unban a previously banned user.

        Only users listed in admin.txt may issue this command.  Accepts a
        Discord mention (``<@123456789>``) or a raw user-ID integer.
        """
        if not is_allowed(message.author.id):
            await self._deny(message)
            return

        parts = command.strip().split(None, 1)
        if len(parts) < 2:
            await message.channel.send("Usage: `unban <@user>` or `unban <user_id>`")
            return

        user_id = _parse_user_id(parts[1])
        if user_id is None:
            await message.channel.send("⚠️ Could not parse a user ID from that input.")
            return

        unban_user(user_id)
        await message.channel.send(f"✅ User `{user_id}` has been unbanned.")
        log(
            f"[Admin] User {user_id} unbanned by {message.author} (id={message.author.id})",
            LogLevel.INFO,
        )

    async def _delete_response(
        self, message: discord.Message, _command: str
    ) -> None:
        """Delete the most recent consecutive bot messages.

        Scans channel history backwards.  Every message authored by *this bot*
        found before the first non-bot message is collected for deletion.
        The user's command message is never deleted.
        """
        if not is_allowed(message.author.id):
            await self._deny(message)
            return

        to_delete: list[discord.Message] = []
        async for msg in message.channel.history(limit=100, before=message):
            if msg.author.id == self.bot.user.id:
                to_delete.append(msg)
            else:
                break

        if not to_delete:
            await message.channel.send("ℹ️ No bot messages found to delete.")
            return

        try:
            await _bulk_delete(message.channel, to_delete)
        except discord.Forbidden:
            await message.channel.send(
                "⛔ I don't have **Manage Messages** permission in this channel."
            )
            return
        log(
            f"[Admin] delete response: {len(to_delete)} message(s) deleted"
            f" by {message.author} (id={message.author.id})",
            LogLevel.INFO,
        )

    async def _delete_count(
        self, message: discord.Message, command: str
    ) -> None:
        """Delete up to N recent bot messages.

        Usage: ``delete count <N>``  (N must be a positive integer)

        Only messages authored by this bot are deleted.  The user's
        command message and all other users' messages are left untouched.
        """
        if not is_allowed(message.author.id):
            await self._deny(message)
            return

        parts = command.strip().split(None, 2)
        if len(parts) < 3:
            await message.channel.send(
                "Usage: `delete count <N>` — e.g. `delete count 10`"
            )
            return

        try:
            n = int(parts[2])
        except ValueError:
            await message.channel.send(
                "⚠️ `N` must be a whole number, e.g. `delete count 10`."
            )
            return

        if n < 1:
            await message.channel.send("⚠️ Count must be at least 1.")
            return

        # Scan history and collect only bot-authored messages.
        to_delete: list[discord.Message] = []
        async for msg in message.channel.history(limit=200, before=message):
            if msg.author.id == self.bot.user.id:
                to_delete.append(msg)
                if len(to_delete) >= n:
                    break

        if not to_delete:
            await message.channel.send("ℹ️ No bot messages found to delete.")
            return

        try:
            await _bulk_delete(message.channel, to_delete)
        except discord.Forbidden:
            await message.channel.send(
                "⛔ I don't have **Manage Messages** permission in this channel."
            )
            return
        log(
            f"[Admin] delete count {n}: {len(to_delete)} message(s) deleted"
            f" by {message.author} (id={message.author.id})",
            LogLevel.INFO,
        )

    async def _delete_time(
        self, message: discord.Message, command: str
    ) -> None:
        """Delete bot messages sent within the last <duration>.

        Usage: ``delete time <duration>``
        Duration examples: ``1h``, ``30m``, ``1h30m``, ``2h1m30s``, ``1m1h``.
        Supports any combination of ``h`` (hours), ``m`` (minutes),
        ``s`` (seconds) in any order.

        Only messages authored by this bot are deleted.  User messages
        are left untouched.
        """
        if not is_allowed(message.author.id):
            await self._deny(message)
            return

        parts = command.strip().split(None, 2)
        if len(parts) < 3:
            await message.channel.send(
                "Usage: `delete time <duration>` — e.g. `delete time 1h`,"
                " `delete time 30m`, `delete time 1h30m`"
            )
            return

        duration_str = parts[2].strip()
        seconds = _parse_duration(duration_str)
        if seconds is None:
            await message.channel.send(
                "⚠️ Invalid duration. Use combinations of `h`, `m`, `s`"
                " — e.g. `1h`, `30m`, `1h30m`, `2h1m30s`."
            )
            return

        cutoff = discord.utils.utcnow() - datetime.timedelta(seconds=seconds)
        bot_id = self.bot.user.id
        try:
            deleted = await message.channel.purge(
                limit=500, after=cutoff,
                check=lambda msg: msg.author.id == bot_id,
            )
        except discord.Forbidden:
            await message.channel.send(
                "⛔ I don't have **Manage Messages** permission in this channel."
            )
            return
        log(
            f"[Admin] delete time {duration_str}: {len(deleted)} message(s) deleted"
            f" by {message.author} (id={message.author.id})",
            LogLevel.INFO,
        )


async def setup(bot: commands.Bot) -> None:
    """Entry point called by Bot.load_extension."""
    await bot.add_cog(AdminCog(cast(Bot, bot)))
