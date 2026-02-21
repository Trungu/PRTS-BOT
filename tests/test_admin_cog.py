# tests/test_admin_cog.py — Unit tests for bot/cogs/admin.py and the
#                            Bot.on_message admin/ban gate integration.
#
# Coverage
# --------
#   _parse_user_id          — mention formats, plain int, edge cases
#   AdminCog registration   — all commands present on the bot
#   AdminCog._admin_only    — non-admin blocked, admin enables, reload called
#   AdminCog._admin_off     — non-admin blocked, admin disables
#   "admin on" alias        — identical to "admin only"
#   AdminCog._ban           — non-admin blocked, ban by ID / mention / legacy
#   AdminCog._unban         — non-admin blocked, unban by ID / mention
#   Bot.on_message          — admin-only gate (block / pass / off)
#   Bot.on_message          — ban gate (block / admin bypass / non-banned pass)

from __future__ import annotations

import asyncio
from typing import Any, cast

import utils.admin as admin_module
from utils.admin import (
    ban_user,
    is_admin_only,
    is_allowed,
    is_banned,
    unban_user,
)
from bot.cogs.admin import AdminCog, _parse_user_id


# ---------------------------------------------------------------------------
# Shared test doubles
# ---------------------------------------------------------------------------

class DummyBot:
    def __init__(self) -> None:
        self.registered: dict = {}

    def register_command(self, name: str, handler) -> None:
        self.registered[name] = handler


class DummyChannel:
    def __init__(self) -> None:
        self.sent: list[tuple] = []

    async def send(self, content, **kwargs):
        self.sent.append((content, kwargs))


class DummyAuthor:
    def __init__(self, user_id: int = 0, *, bot: bool = False) -> None:
        self.id = user_id
        self.bot = bot

    def __str__(self) -> str:
        return f"User({self.id})"


class DummyMessage:
    def __init__(self, user_id: int = 0) -> None:
        self.author = DummyAuthor(user_id)
        self.channel = DummyChannel()


# ---------------------------------------------------------------------------
# _parse_user_id
# ---------------------------------------------------------------------------

def test_parse_user_id_plain_integer() -> None:
    assert _parse_user_id("123456789") == 123456789


def test_parse_user_id_mention_format() -> None:
    assert _parse_user_id("<@123456789>") == 123456789


def test_parse_user_id_legacy_mention_format() -> None:
    assert _parse_user_id("<@!123456789>") == 123456789


def test_parse_user_id_with_whitespace() -> None:
    assert _parse_user_id("  42  ") == 42


def test_parse_user_id_invalid_returns_none() -> None:
    assert _parse_user_id("not_a_user") is None


def test_parse_user_id_empty_returns_none() -> None:
    assert _parse_user_id("") is None


# ---------------------------------------------------------------------------
# AdminCog — command registration
# ---------------------------------------------------------------------------

def test_admin_cog_registers_mode_commands() -> None:
    bot = DummyBot()
    AdminCog(cast(Any, bot))

    assert "admin only" in bot.registered
    assert "admin on" in bot.registered
    assert "admin off" in bot.registered


def test_admin_cog_registers_ban_and_unban() -> None:
    bot = DummyBot()
    AdminCog(cast(Any, bot))

    assert "ban" in bot.registered
    assert "unban" in bot.registered


# ---------------------------------------------------------------------------
# AdminCog._admin_only — non-admin is denied
# ---------------------------------------------------------------------------

def test_admin_only_denied_for_non_admin(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {999})
    monkeypatch.setattr(admin_module, "_admin_only", False)

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = DummyMessage(user_id=123)  # NOT in allowed list

    asyncio.run(cog._admin_only(cast(Any, msg), "admin only"))

    assert msg.channel.sent[0][0] == "⛔ You are not authorised to change admin settings."
    assert not is_admin_only()  # mode was NOT enabled


# ---------------------------------------------------------------------------
# AdminCog._admin_only — allowed user enables the mode
# ---------------------------------------------------------------------------

def test_admin_only_enabled_by_allowed_user(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})
    monkeypatch.setattr(admin_module, "_admin_only", False)
    monkeypatch.setattr(admin_module, "_save_state", lambda: None)
    # Prevent reload_allowed_users from overwriting the state we set above.
    monkeypatch.setattr("bot.cogs.admin.reload_allowed_users", lambda path=None: None)

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = DummyMessage(user_id=42)

    asyncio.run(cog._admin_only(cast(Any, msg), "admin only"))

    assert is_admin_only()
    assert "enabled" in msg.channel.sent[0][0].lower()


# ---------------------------------------------------------------------------
# AdminCog._admin_only — reload_allowed_users is called before locking down
# ---------------------------------------------------------------------------

def test_admin_only_calls_reload(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {7})
    monkeypatch.setattr(admin_module, "_admin_only", False)
    monkeypatch.setattr(admin_module, "_save_state", lambda: None)

    reload_called: list[bool] = []
    monkeypatch.setattr(
        "bot.cogs.admin.reload_allowed_users",
        lambda path=None: reload_called.append(True),
    )

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = DummyMessage(user_id=7)

    asyncio.run(cog._admin_only(cast(Any, msg), "admin only"))

    assert reload_called == [True]


# ---------------------------------------------------------------------------
# AdminCog._admin_off — non-admin is denied
# ---------------------------------------------------------------------------

def test_admin_off_denied_for_non_admin(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {999})
    monkeypatch.setattr(admin_module, "_admin_only", True)

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = DummyMessage(user_id=123)  # NOT in allowed list

    asyncio.run(cog._admin_off(cast(Any, msg), "admin off"))

    assert msg.channel.sent[0][0] == "⛔ You are not authorised to change admin settings."
    assert is_admin_only()  # mode remains ON


# ---------------------------------------------------------------------------
# AdminCog._admin_off — allowed user disables the mode
# ---------------------------------------------------------------------------

def test_admin_off_disabled_by_allowed_user(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})
    monkeypatch.setattr(admin_module, "_admin_only", True)
    monkeypatch.setattr(admin_module, "_save_state", lambda: None)

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = DummyMessage(user_id=42)

    asyncio.run(cog._admin_off(cast(Any, msg), "admin off"))

    assert not is_admin_only()
    assert "disabled" in msg.channel.sent[0][0].lower()


# ---------------------------------------------------------------------------
# "admin on" alias
# ---------------------------------------------------------------------------

def test_admin_on_alias_registered() -> None:
    """Both 'admin only' and 'admin on' must be registered and point to the same handler."""
    bot = DummyBot()
    AdminCog(cast(Any, bot))

    assert "admin on" in bot.registered
    # Both keys are bound methods of the same underlying function.
    assert bot.registered["admin on"].__func__ is bot.registered["admin only"].__func__


def test_admin_on_alias_enables_mode(monkeypatch) -> None:
    """'admin on' must enable admin-only mode identically to 'admin only'."""
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})
    monkeypatch.setattr(admin_module, "_admin_only", False)
    monkeypatch.setattr(admin_module, "_save_state", lambda: None)
    monkeypatch.setattr("bot.cogs.admin.reload_allowed_users", lambda path=None: None)

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = DummyMessage(user_id=42)

    # Call through the alias handler directly.
    asyncio.run(bot.registered["admin on"](cast(Any, msg), "admin on"))

    assert is_admin_only()
    assert "enabled" in msg.channel.sent[0][0].lower()


def test_admin_on_alias_denied_for_non_admin(monkeypatch) -> None:
    """'admin on' must deny a non-admin user the same way 'admin only' does."""
    monkeypatch.setattr(admin_module, "_allowed_ids", {999})
    monkeypatch.setattr(admin_module, "_admin_only", False)
    monkeypatch.setattr(admin_module, "_save_state", lambda: None)

    bot = DummyBot()
    AdminCog(cast(Any, bot))
    msg = DummyMessage(user_id=123)  # NOT in allowed list

    asyncio.run(bot.registered["admin on"](cast(Any, msg), "admin on"))

    assert msg.channel.sent[0][0] == "⛔ You are not authorised to change admin settings."
    assert not is_admin_only()


# ---------------------------------------------------------------------------
# AdminCog._ban — non-admin is denied
# ---------------------------------------------------------------------------

def test_ban_denied_for_non_admin(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {999})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = DummyMessage(user_id=123)  # NOT in allowed list

    asyncio.run(cog._ban(cast(Any, msg), "ban 456"))

    assert msg.channel.sent[0][0] == "⛔ You are not authorised to change admin settings."


# ---------------------------------------------------------------------------
# AdminCog._ban — admin bans a user
# ---------------------------------------------------------------------------

def test_ban_by_user_id(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})
    monkeypatch.setattr(admin_module, "_banned_ids", set())
    monkeypatch.setattr(admin_module, "_save_state", lambda: None)

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = DummyMessage(user_id=42)

    asyncio.run(cog._ban(cast(Any, msg), "ban 555"))

    assert is_banned(555)
    assert "555" in msg.channel.sent[0][0]


def test_ban_by_mention(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})
    monkeypatch.setattr(admin_module, "_banned_ids", set())
    monkeypatch.setattr(admin_module, "_save_state", lambda: None)

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = DummyMessage(user_id=42)

    asyncio.run(cog._ban(cast(Any, msg), "ban <@555>"))

    assert is_banned(555)


def test_ban_legacy_mention(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})
    monkeypatch.setattr(admin_module, "_banned_ids", set())
    monkeypatch.setattr(admin_module, "_save_state", lambda: None)

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = DummyMessage(user_id=42)

    asyncio.run(cog._ban(cast(Any, msg), "ban <@!555>"))

    assert is_banned(555)


def test_ban_missing_target_sends_usage(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = DummyMessage(user_id=42)

    asyncio.run(cog._ban(cast(Any, msg), "ban"))

    assert "usage" in msg.channel.sent[0][0].lower()


def test_ban_invalid_target_sends_error(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = DummyMessage(user_id=42)

    asyncio.run(cog._ban(cast(Any, msg), "ban not_valid"))

    assert (
        "parse" in msg.channel.sent[0][0].lower()
        or "id" in msg.channel.sent[0][0].lower()
    )


# ---------------------------------------------------------------------------
# AdminCog._unban — non-admin is denied
# ---------------------------------------------------------------------------

def test_unban_denied_for_non_admin(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {999})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = DummyMessage(user_id=123)  # NOT in allowed list

    asyncio.run(cog._unban(cast(Any, msg), "unban 456"))

    assert msg.channel.sent[0][0] == "⛔ You are not authorised to change admin settings."


# ---------------------------------------------------------------------------
# AdminCog._unban — admin unbans a user
# ---------------------------------------------------------------------------

def test_unban_by_user_id(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})
    monkeypatch.setattr(admin_module, "_banned_ids", {555})
    monkeypatch.setattr(admin_module, "_save_state", lambda: None)

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = DummyMessage(user_id=42)

    asyncio.run(cog._unban(cast(Any, msg), "unban 555"))

    assert not is_banned(555)
    assert "555" in msg.channel.sent[0][0]


def test_unban_by_mention(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})
    monkeypatch.setattr(admin_module, "_banned_ids", {555})
    monkeypatch.setattr(admin_module, "_save_state", lambda: None)

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = DummyMessage(user_id=42)

    asyncio.run(cog._unban(cast(Any, msg), "unban <@555>"))

    assert not is_banned(555)


def test_unban_missing_target_sends_usage(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = DummyMessage(user_id=42)

    asyncio.run(cog._unban(cast(Any, msg), "unban"))

    assert "usage" in msg.channel.sent[0][0].lower()


def test_unban_invalid_target_sends_error(monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_allowed_ids", {42})

    bot = DummyBot()
    cog = AdminCog(cast(Any, bot))
    msg = DummyMessage(user_id=42)

    asyncio.run(cog._unban(cast(Any, msg), "unban not_valid"))

    assert (
        "parse" in msg.channel.sent[0][0].lower()
        or "id" in msg.channel.sent[0][0].lower()
    )


# ---------------------------------------------------------------------------
# Bot.on_message — admin-only gate blocks non-admin commands
# ---------------------------------------------------------------------------

def test_on_message_blocked_when_admin_only(monkeypatch) -> None:
    from bot.client import Bot

    bot = Bot()
    handled: list[str] = []

    async def handler(message, command):
        handled.append(command)

    bot.register_command("hello", handler)

    channel = DummyChannel()

    monkeypatch.setattr("bot.client.get_command", lambda _: "hello")
    monkeypatch.setattr("bot.client.is_admin_only", lambda: True)
    monkeypatch.setattr("bot.client.is_allowed", lambda uid: False)

    class _Author:
        bot = False
        id = 123

    class _Msg:
        content = "gemma hello"
        author = _Author()

    msg = _Msg()
    msg.channel = channel  # type: ignore[attr-defined]

    asyncio.run(bot.on_message(cast(Any, msg)))

    assert handled == []
    assert len(channel.sent) == 1
    assert "admin" in channel.sent[0][0].lower()


# ---------------------------------------------------------------------------
# Bot.on_message — allowed user passes the admin-only gate
# ---------------------------------------------------------------------------

def test_on_message_passes_for_allowed_user_when_admin_only(monkeypatch) -> None:
    from bot.client import Bot

    bot = Bot()
    handled: list[str] = []

    async def handler(message, command):
        handled.append(command)

    bot.register_command("hello", handler)

    monkeypatch.setattr("bot.client.get_command", lambda _: "hello")
    monkeypatch.setattr("bot.client.is_admin_only", lambda: True)
    monkeypatch.setattr("bot.client.is_allowed", lambda uid: True)

    class _Author:
        bot = False
        id = 42

    class _Msg:
        content = "gemma hello"
        author = _Author()
        channel = DummyChannel()

    async def fake_process(m):
        pass

    bot.process_commands = fake_process  # type: ignore[assignment]

    asyncio.run(bot.on_message(cast(Any, _Msg())))

    assert handled == ["hello"]


# ---------------------------------------------------------------------------
# Bot.on_message — gate is skipped entirely when mode is off
# ---------------------------------------------------------------------------

def test_on_message_no_gate_when_admin_only_off(monkeypatch) -> None:
    from bot.client import Bot

    bot = Bot()
    handled: list[str] = []

    async def handler(message, command):
        handled.append(command)

    bot.register_command("hello", handler)

    monkeypatch.setattr("bot.client.get_command", lambda _: "hello")
    monkeypatch.setattr("bot.client.is_admin_only", lambda: False)
    # is_allowed would return False for this user — but should not matter.
    monkeypatch.setattr("bot.client.is_allowed", lambda uid: False)

    class _Author:
        bot = False
        id = 999  # NOT in any admin list

    class _Msg:
        content = "gemma hello"
        author = _Author()
        channel = DummyChannel()

    async def fake_process(m):
        pass

    bot.process_commands = fake_process  # type: ignore[assignment]

    asyncio.run(bot.on_message(cast(Any, _Msg())))

    assert handled == ["hello"]


# ---------------------------------------------------------------------------
# Bot.on_message — ban gate blocks banned non-admin user
# ---------------------------------------------------------------------------

def test_on_message_blocked_when_banned(monkeypatch) -> None:
    from bot.client import Bot

    bot = Bot()
    handled: list[str] = []

    async def handler(message, command):
        handled.append(command)

    bot.register_command("hello", handler)

    channel = DummyChannel()

    monkeypatch.setattr("bot.client.get_command", lambda _: "hello")
    monkeypatch.setattr("bot.client.is_admin_only", lambda: False)
    monkeypatch.setattr("bot.client.is_allowed", lambda uid: False)
    monkeypatch.setattr("bot.client.is_banned", lambda uid: True)

    class _Author:
        bot = False
        id = 456

    class _Msg:
        content = "gemma hello"
        author = _Author()

    msg = _Msg()
    msg.channel = channel  # type: ignore[attr-defined]

    asyncio.run(bot.on_message(cast(Any, msg)))

    assert handled == []
    assert len(channel.sent) == 1
    assert "banned" in channel.sent[0][0].lower()


# ---------------------------------------------------------------------------
# Bot.on_message — admin bypasses the ban gate even if technically banned
# ---------------------------------------------------------------------------

def test_on_message_ban_gate_bypassed_for_admin(monkeypatch) -> None:
    from bot.client import Bot

    bot = Bot()
    handled: list[str] = []

    async def handler(message, command):
        handled.append(command)

    bot.register_command("hello", handler)

    monkeypatch.setattr("bot.client.get_command", lambda _: "hello")
    monkeypatch.setattr("bot.client.is_admin_only", lambda: False)
    monkeypatch.setattr("bot.client.is_allowed", lambda uid: True)   # admin
    monkeypatch.setattr("bot.client.is_banned", lambda uid: True)    # also banned

    class _Author:
        bot = False
        id = 42

    class _Msg:
        content = "gemma hello"
        author = _Author()
        channel = DummyChannel()

    async def fake_process(m):
        pass

    bot.process_commands = fake_process  # type: ignore[assignment]

    asyncio.run(bot.on_message(cast(Any, _Msg())))

    assert handled == ["hello"]


# ---------------------------------------------------------------------------
# Bot.on_message — non-banned user passes the ban gate
# ---------------------------------------------------------------------------

def test_on_message_non_banned_user_passes_ban_gate(monkeypatch) -> None:
    from bot.client import Bot

    bot = Bot()
    handled: list[str] = []

    async def handler(message, command):
        handled.append(command)

    bot.register_command("hello", handler)

    monkeypatch.setattr("bot.client.get_command", lambda _: "hello")
    monkeypatch.setattr("bot.client.is_admin_only", lambda: False)
    monkeypatch.setattr("bot.client.is_allowed", lambda uid: False)
    monkeypatch.setattr("bot.client.is_banned", lambda uid: False)

    class _Author:
        bot = False
        id = 789

    class _Msg:
        content = "gemma hello"
        author = _Author()
        channel = DummyChannel()

    async def fake_process(m):
        pass

    bot.process_commands = fake_process  # type: ignore[assignment]

    asyncio.run(bot.on_message(cast(Any, _Msg())))

    assert handled == ["hello"]
