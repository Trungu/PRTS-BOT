import asyncio
from typing import Any, cast

from bot.cogs.general import General


class DummyBot:
    def __init__(self) -> None:
        self.registered = {}

    def register_command(self, name, handler):
        self.registered[name] = handler


class DummyChannel:
    def __init__(self) -> None:
        self.sent = []

    async def send(self, content, **kwargs):
        self.sent.append((content, kwargs))


class DummyMessage:
    def __init__(self) -> None:
        self.channel = DummyChannel()


def test_general_registers_commands() -> None:
    bot = DummyBot()
    General(cast(Any, bot))

    assert "hello" in bot.registered
    assert "clear history" in bot.registered


def test_hello_sends_message() -> None:
    bot = DummyBot()
    cog = General(cast(Any, bot))
    msg = DummyMessage()

    asyncio.run(cog._hello(cast(Any, msg), "hello"))

    assert msg.channel.sent == [("Hello!", {})]
