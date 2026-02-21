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

    asyncio.run(bot.on_message(cast(Any, msg)))

    assert received == ["ask something"]
    assert processed == [True]


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
