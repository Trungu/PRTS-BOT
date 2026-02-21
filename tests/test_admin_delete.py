# tests/test_admin_delete.py — Unit tests for the delete-message admin commands.
#
# Coverage
# --------
#   _parse_duration       — seconds/minutes/hours, combined, edge cases, rejection
#   AdminCog registration — delete response / count / time present on the bot
#   _delete_response      — auth denial, consecutive bot messages, human barrier,
#                           empty / no-prior-bot history, Forbidden permission error
#   _delete_count         — auth denial, missing arg, non-integer, zero/negative,
#                           valid scan (only bot msgs), no bot msgs, Forbidden
#   _delete_time          — auth denial, missing arg, invalid duration,
#                           valid minutes/hours/combined, zero duration rejected,
#                           check filter (only bot msgs), Forbidden permission error

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any, cast
from unittest.mock import MagicMock

import discord

import utils.admin as admin_module
from bot.cogs.admin import AdminCog, _parse_duration


# ---------------------------------------------------------------------------
# Shared test doubles
# ---------------------------------------------------------------------------

BOT_USER_ID = 111  # Fake bot user ID used across all delete tests.


class _BotUser:
    """Minimal stub for the bot's own user identity."""

    def __init__(self, user_id: int = BOT_USER_ID) -> None:
        self.id = user_id


class DummyBot:
    def __init__(self) -> None:
        self.registered: dict = {}
        self.user = _BotUser()

    def register_command(self, name: str, handler) -> None:
        self.registered[name] = handler


class _DelAuthor:
    """Minimal author stub with configurable bot flag."""

    def __init__(self, user_id: int = 0, *, bot: bool = False) -> None:
        self.id = user_id
        self.bot = bot

    def __str__(self) -> str:
        return f"User({self.id})"


class _DelMsg:
    """Minimal message stub that supports .delete() and tracks deletion."""

    def __init__(self, user_id: int = 0, *, is_bot: bool = False) -> None:
        self.author = _DelAuthor(user_id, bot=is_bot)
        self.channel: _DelChannel = _DelChannel()
        self._deleted: bool = False

    async def delete(self) -> None:
        self._deleted = True


class _DelChannel:
    """Channel stub with history(), delete_messages(), and purge() support."""

    def __init__(self) -> None:
        self.sent: list[tuple] = []
        self.deleted_batches: list[list] = []
        self.purge_calls: list[dict] = []
        self._history_msgs: list = []

    async def send(self, content, **kwargs):
        self.sent.append((content, kwargs))

    def history(self, *, limit: int = 100, before=None, **kwargs):
        msgs = self._history_msgs

        async def _gen():
            for m in msgs:
                yield m

        return _gen()

    async def delete_messages(self, messages) -> None:
        self.deleted_batches.append(list(messages))

    async def purge(self, *, limit: int = 100, after=None, check=None, **kwargs) -> list:
        self.purge_calls.append({"limit": limit, "after": after, "check": check})
        return []


def _make_forbidden() -> discord.Forbidden:
    """Build a discord.Forbidden instance without a real HTTP response."""
    response = MagicMock()
    response.status = 403
    response.reason = "Forbidden"
    return discord.Forbidden(response, {"message": "Missing Permissions", "code": 50013})


class _ForbiddenChannel(_DelChannel):
    """Channel stub that raises discord.Forbidden on every destructive call."""

    async def delete_messages(self, messages) -> None:  # type: ignore[override]
        raise _make_forbidden()

    async def purge(self, *, limit: int = 100, after=None, check=None, **kwargs) -> list:  # type: ignore[override]
        raise _make_forbidden()



def test_parse_duration_seconds() -> None:
    assert _parse_duration("30s") == 30


def test_parse_duration_minutes() -> None:
    assert _parse_duration("5m") == 300


def test_parse_duration_hours() -> None:
    assert _parse_duration("2h") == 7200


def test_parse_duration_combined_hm() -> None:
    assert _parse_duration("1h30m") == 5400


def test_parse_duration_reversed_order_mh() -> None:
    """Units can appear in any order — 1m1h = 61 minutes = 3660 s."""
    assert _parse_duration("1m1h") == 3660


def test_parse_duration_all_three_units() -> None:
    assert _parse_duration("1h1m1s") == 3661


def test_parse_duration_large_unit_value() -> None:
    """60m is a valid way to express one hour."""
    assert _parse_duration("60m") == 3600


def test_parse_duration_zero_total_returns_none() -> None:
    assert _parse_duration("0h0m0s") is None


def test_parse_duration_single_zero_unit_returns_none() -> None:
    assert _parse_duration("0s") is None


def test_parse_duration_empty_string_returns_none() -> None:
    assert _parse_duration("") is None


def test_parse_duration_colon_format_rejected() -> None:
    """'5:00' style timestamps must not be parsed."""
    assert _parse_duration("5:00") is None


def test_parse_duration_plain_text_rejected() -> None:
    assert _parse_duration("hello") is None


def test_parse_duration_bare_integer_rejected() -> None:
    assert _parse_duration("5") is None


def test_parse_duration_internal_spaces_rejected() -> None:
    """Spaces between unit tokens are not allowed."""
    assert _parse_duration("1h 30m") is None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_admin_cog_registers_delete_commands() -> None:
    bot = DummyBot()
    AdminCog(cast(Any, bot))

    assert "delete response" in bot.registered
    assert "delete count" in bot.registered
    assert "delete time" in bot.registered


# ---------------------------------------------------------------------------
# _delete_response — auth
# ---------------------------------------------------------------------------

def test_delete_response_denied_for_non_admin(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", set())

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = _DelMsg(user_id=999)

    asyncio.run(cog._delete_response(cast(Any, msg), "delete response"))

    assert any("not authorised" in str(s[0]).lower() for s in msg.channel.sent)


# ---------------------------------------------------------------------------
# _delete_response — behaviour
# ---------------------------------------------------------------------------

def test_delete_response_deletes_consecutive_bot_messages(monkeypatch) -> None:
    """Bot messages before the command are collected and deleted."""
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    cmd_msg = _DelMsg(user_id=42)

    bot_msg1 = _DelMsg(user_id=BOT_USER_ID, is_bot=True)
    bot_msg2 = _DelMsg(user_id=BOT_USER_ID, is_bot=True)
    human_msg = _DelMsg(user_id=7)  # non-bot — stops iteration
    cmd_msg.channel._history_msgs = [bot_msg1, bot_msg2, human_msg]

    asyncio.run(cog._delete_response(cast(Any, cmd_msg), "delete response"))

    # Two messages: bot_msg1 + bot_msg2 (command message NOT included).
    assert len(cmd_msg.channel.deleted_batches) == 1
    batch = cmd_msg.channel.deleted_batches[0]
    assert cmd_msg not in batch  # User's command must NEVER be deleted.
    assert bot_msg1 in batch
    assert bot_msg2 in batch
    # The human message must NOT be deleted.
    assert human_msg not in batch


def test_delete_response_stops_at_first_human_message(monkeypatch) -> None:
    """Bot messages after the first human message are NOT deleted."""
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    cmd_msg = _DelMsg(user_id=42)

    bot_before = _DelMsg(user_id=BOT_USER_ID, is_bot=True)
    human_barrier = _DelMsg(user_id=5)
    bot_after = _DelMsg(user_id=BOT_USER_ID, is_bot=True)  # older — must not be touched
    cmd_msg.channel._history_msgs = [bot_before, human_barrier, bot_after]

    asyncio.run(cog._delete_response(cast(Any, cmd_msg), "delete response"))

    assert bot_before._deleted is True
    assert bot_after._deleted is False


def test_delete_response_no_prior_bot_messages_sends_info(
    monkeypatch,
) -> None:
    """When history starts with a human message, no deletion occurs."""
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    cmd_msg = _DelMsg(user_id=42)
    cmd_msg.channel._history_msgs = [_DelMsg(user_id=9)]  # human immediately

    asyncio.run(cog._delete_response(cast(Any, cmd_msg), "delete response"))

    # No messages should be deleted; user gets an info reply.
    assert cmd_msg._deleted is False
    assert cmd_msg.channel.deleted_batches == []
    assert any("no bot messages" in str(s[0]).lower() for s in cmd_msg.channel.sent)


def test_delete_response_empty_history_sends_info(monkeypatch) -> None:
    """Empty channel history: no deletion, info message sent."""
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    cmd_msg = _DelMsg(user_id=42)
    cmd_msg.channel._history_msgs = []

    asyncio.run(cog._delete_response(cast(Any, cmd_msg), "delete response"))

    assert cmd_msg._deleted is False
    assert cmd_msg.channel.deleted_batches == []
    assert any("no bot messages" in str(s[0]).lower() for s in cmd_msg.channel.sent)


# ---------------------------------------------------------------------------
# _delete_count — auth + input validation + behaviour
# ---------------------------------------------------------------------------

def test_delete_count_denied_for_non_admin(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", set())

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = _DelMsg(user_id=999)

    asyncio.run(cog._delete_count(cast(Any, msg), "delete count 5"))

    assert any("not authorised" in str(s[0]).lower() for s in msg.channel.sent)
    assert msg.channel.purge_calls == []


def test_delete_count_missing_argument(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = _DelMsg(user_id=42)

    asyncio.run(cog._delete_count(cast(Any, msg), "delete count"))

    assert any("usage" in str(s[0]).lower() for s in msg.channel.sent)
    assert msg.channel.purge_calls == []


def test_delete_count_invalid_non_integer(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = _DelMsg(user_id=42)

    asyncio.run(cog._delete_count(cast(Any, msg), "delete count abc"))

    assert any("whole number" in str(s[0]).lower() for s in msg.channel.sent)
    assert msg.channel.purge_calls == []


def test_delete_count_zero_rejected(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = _DelMsg(user_id=42)

    asyncio.run(cog._delete_count(cast(Any, msg), "delete count 0"))

    assert any("at least 1" in str(s[0]).lower() for s in msg.channel.sent)
    assert msg.channel.purge_calls == []


def test_delete_count_negative_rejected(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = _DelMsg(user_id=42)

    asyncio.run(cog._delete_count(cast(Any, msg), "delete count -3"))

    assert any("at least 1" in str(s[0]).lower() for s in msg.channel.sent)
    assert msg.channel.purge_calls == []


def test_delete_count_valid_deletes_only_bot_messages(monkeypatch) -> None:
    """delete count N scans history and only deletes bot-authored messages."""
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = _DelMsg(user_id=42)

    bot_msg1 = _DelMsg(user_id=BOT_USER_ID, is_bot=True)
    human_msg = _DelMsg(user_id=7)
    bot_msg2 = _DelMsg(user_id=BOT_USER_ID, is_bot=True)
    msg.channel._history_msgs = [bot_msg1, human_msg, bot_msg2]

    asyncio.run(cog._delete_count(cast(Any, msg), "delete count 10"))

    # Both bot messages collected; human message untouched.
    assert len(msg.channel.deleted_batches) == 1
    batch = msg.channel.deleted_batches[0]
    assert bot_msg1 in batch
    assert bot_msg2 in batch
    assert human_msg not in batch
    assert msg not in batch  # command message never deleted


def test_delete_count_value_one_deletes_one_bot_message(monkeypatch) -> None:
    """delete count 1 — only the most recent bot message is deleted."""
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = _DelMsg(user_id=42)

    bot_msg1 = _DelMsg(user_id=BOT_USER_ID, is_bot=True)
    bot_msg2 = _DelMsg(user_id=BOT_USER_ID, is_bot=True)
    msg.channel._history_msgs = [bot_msg1, bot_msg2]

    asyncio.run(cog._delete_count(cast(Any, msg), "delete count 1"))

    # Only one bot message should be deleted.
    assert bot_msg1._deleted is True
    assert bot_msg2._deleted is False


def test_delete_count_skips_user_messages(monkeypatch) -> None:
    """User messages are never deleted, even when mixed in with bot messages."""
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = _DelMsg(user_id=42)

    human_msg = _DelMsg(user_id=7)
    bot_msg = _DelMsg(user_id=BOT_USER_ID, is_bot=True)
    msg.channel._history_msgs = [human_msg, bot_msg]

    asyncio.run(cog._delete_count(cast(Any, msg), "delete count 5"))

    assert bot_msg._deleted is True
    assert human_msg._deleted is False


def test_delete_count_no_bot_messages_sends_info(monkeypatch) -> None:
    """When no bot messages exist, an info message is sent."""
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = _DelMsg(user_id=42)
    msg.channel._history_msgs = [_DelMsg(user_id=7), _DelMsg(user_id=8)]

    asyncio.run(cog._delete_count(cast(Any, msg), "delete count 3"))

    assert any("no bot messages" in str(s[0]).lower() for s in msg.channel.sent)


# ---------------------------------------------------------------------------
# _delete_time — auth + input validation + behaviour
# ---------------------------------------------------------------------------

def test_delete_time_denied_for_non_admin(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", set())

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = _DelMsg(user_id=999)

    asyncio.run(cog._delete_time(cast(Any, msg), "delete time 1h"))

    assert any("not authorised" in str(s[0]).lower() for s in msg.channel.sent)
    assert msg.channel.purge_calls == []


def test_delete_time_missing_argument(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = _DelMsg(user_id=42)

    asyncio.run(cog._delete_time(cast(Any, msg), "delete time"))

    assert any("usage" in str(s[0]).lower() for s in msg.channel.sent)
    assert msg.channel.purge_calls == []


def test_delete_time_invalid_duration(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = _DelMsg(user_id=42)

    asyncio.run(cog._delete_time(cast(Any, msg), "delete time 5:00"))

    assert any("invalid duration" in str(s[0]).lower() for s in msg.channel.sent)
    assert msg.channel.purge_calls == []


def test_delete_time_valid_minutes_calls_purge(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = _DelMsg(user_id=42)

    before = dt.datetime.now(dt.timezone.utc)
    asyncio.run(cog._delete_time(cast(Any, msg), "delete time 30m"))

    assert len(msg.channel.purge_calls) == 1
    call = msg.channel.purge_calls[0]
    assert call["limit"] == 500
    expected_cutoff = before - dt.timedelta(minutes=30)
    assert abs((call["after"] - expected_cutoff).total_seconds()) < 3
    # Must pass a check filter so only bot messages are deleted.
    assert call["check"] is not None


def test_delete_time_check_filter_accepts_bot_rejects_user(monkeypatch) -> None:
    """The check callable passed to purge only accepts bot-authored messages."""
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = _DelMsg(user_id=42)

    asyncio.run(cog._delete_time(cast(Any, msg), "delete time 1h"))

    check_fn = msg.channel.purge_calls[0]["check"]
    bot_msg = _DelMsg(user_id=BOT_USER_ID, is_bot=True)
    user_msg = _DelMsg(user_id=99)
    assert check_fn(bot_msg) is True
    assert check_fn(user_msg) is False


def test_delete_time_valid_hours_calls_purge(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = _DelMsg(user_id=42)

    asyncio.run(cog._delete_time(cast(Any, msg), "delete time 1h"))

    call = msg.channel.purge_calls[0]
    assert call["limit"] == 500
    expected = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    assert abs((call["after"] - expected).total_seconds()) < 3


def test_delete_time_valid_combined_duration(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = _DelMsg(user_id=42)

    asyncio.run(cog._delete_time(cast(Any, msg), "delete time 1h30m"))

    call = msg.channel.purge_calls[0]
    expected = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=5400)
    assert abs((call["after"] - expected).total_seconds()) < 3


def test_delete_time_zero_duration_rejected(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = _DelMsg(user_id=42)

    asyncio.run(cog._delete_time(cast(Any, msg), "delete time 0s"))

    assert any("invalid duration" in str(s[0]).lower() for s in msg.channel.sent)
    assert msg.channel.purge_calls == []


# ---------------------------------------------------------------------------
# Missing-permissions (discord.Forbidden) error handling
# ---------------------------------------------------------------------------

def test_delete_response_forbidden_sends_error(monkeypatch) -> None:
    """When the bot lacks Manage Messages, _delete_response sends a clear error."""
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    cmd_msg = _DelMsg(user_id=42)
    cmd_msg.channel = _ForbiddenChannel()  # type: ignore[assignment]
    cmd_msg.channel._history_msgs = [
        _DelMsg(user_id=BOT_USER_ID, is_bot=True),
        _DelMsg(user_id=BOT_USER_ID, is_bot=True),
    ]

    asyncio.run(cog._delete_response(cast(Any, cmd_msg), "delete response"))

    assert any("manage messages" in str(s[0]).lower() for s in cmd_msg.channel.sent)


def test_delete_count_forbidden_sends_error(monkeypatch) -> None:
    """When the bot lacks Manage Messages, _delete_count sends a clear error."""
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = _DelMsg(user_id=42)
    msg.channel = _ForbiddenChannel()  # type: ignore[assignment]
    msg.channel._history_msgs = [
        _DelMsg(user_id=BOT_USER_ID, is_bot=True),
        _DelMsg(user_id=BOT_USER_ID, is_bot=True),
    ]

    asyncio.run(cog._delete_count(cast(Any, msg), "delete count 5"))

    assert any("manage messages" in str(s[0]).lower() for s in msg.channel.sent)


def test_delete_time_forbidden_sends_error(monkeypatch) -> None:
    """When the bot lacks Manage Messages, _delete_time sends a clear error."""
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = _DelMsg(user_id=42)
    msg.channel = _ForbiddenChannel()  # type: ignore[assignment]

    asyncio.run(cog._delete_time(cast(Any, msg), "delete time 30m"))

    assert any("manage messages" in str(s[0]).lower() for s in msg.channel.sent)
