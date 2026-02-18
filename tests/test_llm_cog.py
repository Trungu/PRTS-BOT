import asyncio
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest

from bot.cogs import llm as llm_cog


class DummyChannel:
    def __init__(self) -> None:
        self.sent = []

    async def send(self, content, **kwargs):
        self.sent.append((content, kwargs))

    @asynccontextmanager
    async def typing(self):
        yield


class DummyMessage:
    def __init__(self) -> None:
        self.author = "user"
        self.channel = DummyChannel()


class DummyBot:
    def __init__(self) -> None:
        self.handler = None

    def set_llm_handler(self, handler):
        self.handler = handler


def test_send_uses_silent_flag_when_forced() -> None:
    channel = DummyChannel()

    asyncio.run(llm_cog._send(cast(Any, channel), "hello", force_silent=True))

    assert channel.sent == [("hello", {"silent": True})]


def test_llm_registers_fallback_handler() -> None:
    bot = DummyBot()
    cog = llm_cog.LLM(cast(Any, bot))

    assert bot.handler == cog._ask


def test_ask_success_sends_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = DummyBot()
    cog = llm_cog.LLM(cast(Any, bot))
    msg = DummyMessage()

    monkeypatch.setattr(llm_cog, "chat", lambda *args, **kwargs: "ok")

    asyncio.run(cog._ask(cast(Any, msg), "hello"))

    assert msg.channel.sent == [("ok", {})]


def test_ask_error_sends_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = DummyBot()
    cog = llm_cog.LLM(cast(Any, bot))
    msg = DummyMessage()

    def raise_error(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(llm_cog, "chat", raise_error)

    asyncio.run(cog._ask(cast(Any, msg), "hello"))

    assert len(msg.channel.sent) == 1
    assert "⚠️ The LLM returned an error" in msg.channel.sent[0][0]


def test_ask_splits_long_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = DummyBot()
    cog = llm_cog.LLM(cast(Any, bot))
    msg = DummyMessage()

    monkeypatch.setattr(llm_cog, "chat", lambda *args, **kwargs: "x" * 4001)

    asyncio.run(cog._ask(cast(Any, msg), "hello"))

    assert len(msg.channel.sent) == 3
    assert len(msg.channel.sent[0][0]) == 2000
    assert len(msg.channel.sent[1][0]) == 2000
    assert len(msg.channel.sent[2][0]) == 1
