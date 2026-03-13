import asyncio
from typing import Any, cast

import pytest

from bot.client import Bot


class DummyChannel:
    def __init__(self) -> None:
        self.sent = []

    async def send(self, content, **kwargs):
        self.sent.append((content, kwargs))


class DummyAuthor:
    def __init__(self, bot: bool = False) -> None:
        self.bot = bot
        self.id: int = 0


class DummyMessage:
    def __init__(self, content: str, *, author_bot: bool = False) -> None:
        self.content = content
        self.author = DummyAuthor(bot=author_bot)
        self.channel = DummyChannel()
        self.reference = None


class DummyRef:
    def __init__(self, resolved) -> None:
        self.resolved = resolved
        self.message_id = None


class DummyBotAuthoredMessage:
    def __init__(self, author_id: int) -> None:
        author = DummyAuthor(bot=True)
        author.id = author_id
        self.author = author


def test_register_command_lowercases_and_strips() -> None:
    bot = Bot()

    async def handler(message, command):
        return None

    bot.register_command("  HeLLo  ", handler)

    assert "hello" in bot._command_handlers


def test_on_message_ignores_bot_author(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = Bot()
    msg = DummyMessage("bot hello", author_bot=True)

    called = {"processed": False}

    async def fake_process_commands(message):
        called["processed"] = True

    bot.process_commands = fake_process_commands  # type: ignore[assignment]

    asyncio.run(bot.on_message(cast(Any, msg)))

    assert called["processed"] is False


def test_on_message_records_bot_authored_messages_in_channel_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = Bot()
    msg = DummyMessage("bot hello", author_bot=True)
    remembered = []

    monkeypatch.setattr(
        "bot.client.remember_message",
        lambda **kwargs: remembered.append(kwargs),
    )

    asyncio.run(bot.on_message(cast(Any, msg)))

    assert remembered == [
        {
            "channel_id": 0,
            "author_name": str(msg.author),
            "content": "bot hello",
            "author_is_bot": True,
            "created_at": None,
        }
    ]


def test_on_message_skips_delete_count_command_in_channel_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = Bot()
    msg = DummyMessage("delete count 3")
    remembered = []

    monkeypatch.setattr(
        "bot.client.remember_message",
        lambda **kwargs: remembered.append(kwargs),
    )
    monkeypatch.setattr("bot.client.get_command", lambda _: "delete count 3")
    monkeypatch.setattr("bot.client.detect_crisis", lambda text: False)

    asyncio.run(bot.on_message(cast(Any, msg)))

    assert remembered == []


def test_on_message_keeps_normal_message_in_channel_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = Bot()
    msg = DummyMessage("hello")
    remembered = []

    monkeypatch.setattr(
        "bot.client.remember_message",
        lambda **kwargs: remembered.append(kwargs),
    )
    monkeypatch.setattr("bot.client.get_command", lambda _: "hello")
    monkeypatch.setattr("bot.client.detect_crisis", lambda text: False)
    monkeypatch.setattr("bot.client.is_admin_only", lambda: False)
    monkeypatch.setattr("bot.client.is_banned", lambda uid: False)

    asyncio.run(bot.on_message(cast(Any, msg)))

    assert len(remembered) == 1
    assert remembered[0]["content"] == "hello"


def test_on_message_dispatches_longest_match(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = Bot()
    msg = DummyMessage("ignored")

    order = []

    async def clear_handler(message, command):
        order.append("clear")

    async def clear_history_handler(message, command):
        order.append("clear history")

    bot.register_command("clear", clear_handler)
    bot.register_command("clear history", clear_history_handler)

    monkeypatch.setattr("bot.client.get_command", lambda _: "clear history all")
    monkeypatch.setattr("bot.client.detect_crisis", lambda text: False)
    monkeypatch.setattr("bot.client.is_admin_only", lambda: False)
    monkeypatch.setattr("bot.client.is_banned", lambda uid: False)

    asyncio.run(bot.on_message(cast(Any, msg)))

    assert order == ["clear history"]


def test_on_message_falls_back_to_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = Bot()
    msg = DummyMessage("ignored")

    received = []
    processed = []

    async def llm_handler(message, command):
        received.append(command)

    async def fake_process_commands(message):
        processed.append(True)

    bot.set_llm_handler(llm_handler)
    bot.process_commands = fake_process_commands  # type: ignore[assignment]
    monkeypatch.setattr("bot.client.get_command", lambda _: "ask something")
    monkeypatch.setattr("bot.client.detect_crisis", lambda text: False)
    monkeypatch.setattr("bot.client.is_admin_only", lambda: False)
    monkeypatch.setattr("bot.client.is_banned", lambda uid: False)

    asyncio.run(bot.on_message(cast(Any, msg)))

    assert received == ["ask something"]
    assert processed == [True]


def test_on_message_reply_to_bot_without_prefix_calls_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = Bot()
    msg = DummyMessage("can you help with this?")
    bot._connection.user = cast(Any, type("U", (), {"id": 999})())  # discord.py user cache
    msg.reference = DummyRef(DummyBotAuthoredMessage(author_id=999))

    received = []
    processed = []

    async def llm_handler(message, command):
        received.append(command)

    async def fake_process_commands(message):
        processed.append(True)

    bot.set_llm_handler(llm_handler)
    bot.process_commands = fake_process_commands  # type: ignore[assignment]

    monkeypatch.setattr("bot.client.get_command", lambda _: None)
    monkeypatch.setattr("bot.client.detect_crisis", lambda text: False)
    monkeypatch.setattr("bot.client.is_admin_only", lambda: False)
    monkeypatch.setattr("bot.client.is_banned", lambda uid: False)
    monkeypatch.setattr("bot.client.is_allowed", lambda uid: True)
    monkeypatch.setattr("bot.client.settings.REPLY_TRIGGER_ENABLED", True)

    asyncio.run(bot.on_message(cast(Any, msg)))

    assert received == ["can you help with this?"]
    assert processed == [True]


def test_on_message_reply_to_bot_without_prefix_ignored_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = Bot()
    msg = DummyMessage("can you help with this?")
    bot._connection.user = cast(Any, type("U", (), {"id": 999})())
    msg.reference = DummyRef(DummyBotAuthoredMessage(author_id=999))

    received = []
    processed = []

    async def llm_handler(message, command):
        received.append(command)

    async def fake_process_commands(message):
        processed.append(True)

    bot.set_llm_handler(llm_handler)
    bot.process_commands = fake_process_commands  # type: ignore[assignment]

    monkeypatch.setattr("bot.client.get_command", lambda _: None)
    monkeypatch.setattr("bot.client.detect_crisis", lambda text: False)
    monkeypatch.setattr("bot.client.settings.REPLY_TRIGGER_ENABLED", False)

    asyncio.run(bot.on_message(cast(Any, msg)))

    assert received == []
    assert processed == []


def test_load_cogs_loads_py_extensions(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = Bot()
    loaded = []

    async def fake_load_extension(name: str):
        loaded.append(name)

    bot.load_extension = fake_load_extension  # type: ignore[assignment]
    monkeypatch.setattr("bot.client.os.listdir", lambda _: ["_ignore.py", "general.py", "llm.py", "notes.txt"])

    asyncio.run(bot._load_cogs())

    assert loaded == ["bot.cogs.general", "bot.cogs.llm"]


# ---------------------------------------------------------------------------
# Crisis detector integration
# ---------------------------------------------------------------------------

def test_crisis_message_without_prefix_sends_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    """A distress message that has no bot prefix still receives the crisis response."""
    bot = Bot()
    # Message has no bot prefix — get_command returns None — but crisis must
    # still be detected and responded to before the prefix check.
    msg = DummyMessage("I want to kill myself")

    monkeypatch.setattr("bot.client.get_command", lambda _: None)
    monkeypatch.setattr("bot.client.detect_crisis", lambda text: True)

    asyncio.run(bot.on_message(cast(Any, msg)))

    assert len(msg.channel.sent) == 1
    content, _ = msg.channel.sent[0]
    assert "988" in content or "741741" in content or "iasp.info" in content


def test_crisis_message_with_prefix_sends_resources_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A distress message that also has a bot prefix receives crisis resources
    AND has the command dispatched normally."""
    bot = Bot()
    msg = DummyMessage("gemma, kill myself please help")

    dispatched = []

    async def handler(message, command):
        dispatched.append(command)

    bot.register_command("kill", handler)

    monkeypatch.setattr("bot.client.get_command", lambda _: "kill")
    monkeypatch.setattr("bot.client.detect_crisis", lambda text: True)
    monkeypatch.setattr("bot.client.is_admin_only", lambda: False)
    monkeypatch.setattr("bot.client.is_banned", lambda uid: False)

    async def fake_process_commands(message):
        pass

    bot.process_commands = fake_process_commands  # type: ignore[assignment]

    asyncio.run(bot.on_message(cast(Any, msg)))

    # Crisis response was sent
    assert len(msg.channel.sent) >= 1
    content, _ = msg.channel.sent[0]
    assert "988" in content or "741741" in content or "iasp.info" in content
    # Command was also dispatched
    assert dispatched == ["kill"]


def test_no_crisis_response_for_normal_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """Normal messages do not trigger the crisis response."""
    bot = Bot()
    msg = DummyMessage("gemma, hello")

    monkeypatch.setattr("bot.client.get_command", lambda _: "hello")
    monkeypatch.setattr("bot.client.detect_crisis", lambda text: False)
    monkeypatch.setattr("bot.client.is_admin_only", lambda: False)
    monkeypatch.setattr("bot.client.is_banned", lambda uid: False)

    async def fake_process_commands(message):
        pass

    bot.process_commands = fake_process_commands  # type: ignore[assignment]

    asyncio.run(bot.on_message(cast(Any, msg)))

    assert msg.channel.sent == []

# ---------------------------------------------------------------------------
# Rate limiter integration
# ---------------------------------------------------------------------------

def test_rate_limit_warning_still_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the rate limiter returns WARNING, the warning is sent but the
    command is still dispatched."""
    from utils.rate_limiter import RateLimitResult

    bot = Bot()
    msg = DummyMessage("gemma, hello")
    dispatched = []

    async def handler(message, command):
        dispatched.append(command)

    bot.register_command("hello", handler)

    monkeypatch.setattr("bot.client.get_command", lambda _: "hello")
    monkeypatch.setattr("bot.client.detect_crisis", lambda text: False)
    monkeypatch.setattr("bot.client.is_admin_only", lambda: False)
    monkeypatch.setattr("bot.client.is_banned", lambda uid: False)
    monkeypatch.setattr("bot.client.is_allowed", lambda uid: False)
    monkeypatch.setattr("bot.client.check_rate_limit", lambda uid: RateLimitResult.WARNING)

    async def fake_process_commands(message):
        pass

    bot.process_commands = fake_process_commands  # type: ignore[assignment]

    asyncio.run(bot.on_message(cast(Any, msg)))

    # Warning was sent.
    assert any("slow down" in c[0].lower() for c in msg.channel.sent if c[0])
    # Command was still dispatched.
    assert dispatched == ["hello"]


def test_rate_limit_rejects_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the rate limiter returns RATE_LIMITED, the message is rejected."""
    from utils.rate_limiter import RateLimitResult

    bot = Bot()
    msg = DummyMessage("gemma, hello")
    dispatched = []

    async def handler(message, command):
        dispatched.append(command)

    bot.register_command("hello", handler)

    monkeypatch.setattr("bot.client.get_command", lambda _: "hello")
    monkeypatch.setattr("bot.client.detect_crisis", lambda text: False)
    monkeypatch.setattr("bot.client.is_admin_only", lambda: False)
    monkeypatch.setattr("bot.client.is_banned", lambda uid: False)
    monkeypatch.setattr("bot.client.is_allowed", lambda uid: False)
    monkeypatch.setattr("bot.client.check_rate_limit", lambda uid: RateLimitResult.RATE_LIMITED)

    asyncio.run(bot.on_message(cast(Any, msg)))

    # Rejection message was sent.
    assert any("rate limit" in c[0].lower() for c in msg.channel.sent if c[0])
    # Command was NOT dispatched.
    assert dispatched == []


def test_rate_limit_cooldown_rejects_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the rate limiter returns COOLDOWN, the message is rejected."""
    from utils.rate_limiter import RateLimitResult

    bot = Bot()
    msg = DummyMessage("gemma, hello")
    dispatched = []

    async def handler(message, command):
        dispatched.append(command)

    bot.register_command("hello", handler)

    monkeypatch.setattr("bot.client.get_command", lambda _: "hello")
    monkeypatch.setattr("bot.client.detect_crisis", lambda text: False)
    monkeypatch.setattr("bot.client.is_admin_only", lambda: False)
    monkeypatch.setattr("bot.client.is_banned", lambda uid: False)
    monkeypatch.setattr("bot.client.is_allowed", lambda uid: False)
    monkeypatch.setattr("bot.client.check_rate_limit", lambda uid: RateLimitResult.COOLDOWN)

    asyncio.run(bot.on_message(cast(Any, msg)))

    # Cooldown message was sent.
    assert any("rate-limited" in c[0].lower() for c in msg.channel.sent if c[0])
    # Command was NOT dispatched.
    assert dispatched == []


def test_admins_bypass_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Admins (is_allowed=True) bypass the rate limiter entirely."""
    bot = Bot()
    msg = DummyMessage("gemma, hello")
    msg.author.id = 42
    dispatched = []

    async def handler(message, command):
        dispatched.append(command)

    bot.register_command("hello", handler)

    monkeypatch.setattr("bot.client.get_command", lambda _: "hello")
    monkeypatch.setattr("bot.client.detect_crisis", lambda text: False)
    monkeypatch.setattr("bot.client.is_admin_only", lambda: False)
    monkeypatch.setattr("bot.client.is_banned", lambda uid: False)
    monkeypatch.setattr("bot.client.is_allowed", lambda uid: uid == 42)
    # Even if check_rate_limit would reject, admins skip it.
    monkeypatch.setattr("bot.client.check_rate_limit", lambda uid: (_ for _ in ()).throw(
        AssertionError("check_rate_limit should not be called for admins")
    ))

    async def fake_process_commands(message):
        pass

    bot.process_commands = fake_process_commands  # type: ignore[assignment]

    asyncio.run(bot.on_message(cast(Any, msg)))

    assert dispatched == ["hello"]


def test_rate_limit_allowed_processes_normally(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the rate limiter returns ALLOWED, no extra messages are sent."""
    from utils.rate_limiter import RateLimitResult

    bot = Bot()
    msg = DummyMessage("gemma, hello")
    dispatched = []

    async def handler(message, command):
        dispatched.append(command)

    bot.register_command("hello", handler)

    monkeypatch.setattr("bot.client.get_command", lambda _: "hello")
    monkeypatch.setattr("bot.client.detect_crisis", lambda text: False)
    monkeypatch.setattr("bot.client.is_admin_only", lambda: False)
    monkeypatch.setattr("bot.client.is_banned", lambda uid: False)
    monkeypatch.setattr("bot.client.is_allowed", lambda uid: False)
    monkeypatch.setattr("bot.client.check_rate_limit", lambda uid: RateLimitResult.ALLOWED)

    async def fake_process_commands(message):
        pass

    bot.process_commands = fake_process_commands  # type: ignore[assignment]

    asyncio.run(bot.on_message(cast(Any, msg)))

    # No rate-limit messages sent.
    assert msg.channel.sent == []
    # Command was dispatched.
    assert dispatched == ["hello"]
