# bot/client.py — Bot subclass with cog auto-loading and lifecycle hooks.
from __future__ import annotations

import os
from typing import Awaitable, Callable
import discord
from discord.ext import commands

from utils.logger import log, LogLevel
from utils.prefix_handler import get_command

# Type alias for a command handler: receives a Message and the stripped command string.
CommandHandler = Callable[[discord.Message, str], Awaitable[None]]
# Type alias for the LLM fallback handler: receives a Message and the prompt string.
LLMHandler = Callable[[discord.Message, str], Awaitable[None]]


class Bot(commands.Bot):
    """Custom Bot subclass.

    Cogs are loaded automatically from the ``bot/cogs/`` directory.
    Any module inside that package that contains a top-level ``setup``
    coroutine will be loaded on startup.

    Dispatch model
    --------------
    All ``on_message`` routing is handled here, in one place, so cogs never
    need to listen for ``on_message`` themselves.  Cogs register their
    handlers at load time via:

    * ``bot.register_command(name, handler)``  — exact / prefix command match
    * ``bot.set_llm_handler(handler)``          — catches everything else

    This guarantees that the LLM fallback can *never* accidentally swallow a
    command that belongs to another cog.
    """

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            # commands.Bot requires a command_prefix, but we handle prefix
            # matching ourselves, so use a no-op callable.
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,  # disable the built-in help command
        )

        # Maps lowercased command name → async handler.
        self._command_handlers: dict[str, CommandHandler] = {}
        # Optional catch-all for unrecognised commands (typically the LLM cog).
        self._llm_handler: LLMHandler | None = None

    # ------------------------------------------------------------------
    # Handler registration (called by cogs in their __init__)
    # ------------------------------------------------------------------

    def register_command(self, name: str, handler: CommandHandler) -> None:
        """Register *handler* for the exact command string *name* (case-insensitive).

        Also accepts multi-word commands (e.g. ``"clear history"``).
        When a message matches any registered prefix the handler is called
        with the full remaining text, so ``"clear history"`` will also match
        ``"clear history all"``.
        """
        self._command_handlers[name.lower().strip()] = handler

    def set_llm_handler(self, handler: LLMHandler) -> None:
        """Set the fallback handler that receives any unrecognised prompt."""
        self._llm_handler = handler

    # ------------------------------------------------------------------
    # Central on_message dispatcher
    # ------------------------------------------------------------------

    async def on_message(self, message: discord.Message) -> None:
        """Single entry point for all custom-prefix message routing.

        1. Ignore bots.
        2. Strip the prefix; ignore messages that don't match.
        3. Walk registered command handlers (longest match first).
        4. Fall back to the LLM handler if no command matched.
        """
        if message.author.bot:
            return

        command = get_command(message.content)
        if command is None:
            return

        cmd = command.lower().strip()

        # Try longest registered key first to support multi-word commands
        # like "clear history" before a shorter key like "clear".
        for key in sorted(self._command_handlers, key=len, reverse=True):
            if cmd == key or cmd.startswith(key + " "):
                await self._command_handlers[key](message, command)
                return

        # Nothing matched — hand off to the LLM fallback.
        if self._llm_handler is not None:
            await self._llm_handler(message, command)
        else:
            log(f"[Bot] No handler for command: {command!r}", LogLevel.WARNING)

        await self.process_commands(message)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def setup_hook(self) -> None:
        """Called automatically by discord.py before the bot connects.

        This is the right place to load cogs because it runs in the async
        context, and ``load_extension`` is a coroutine.
        """
        await self._load_cogs()

    async def _load_cogs(self) -> None:
        """Discover and load every cog module in ``bot/cogs/``."""
        cogs_dir = os.path.join(os.path.dirname(__file__), "cogs")

        for filename in sorted(os.listdir(cogs_dir)):
            if filename.startswith("_") or not filename.endswith(".py"):
                continue

            extension = f"bot.cogs.{filename[:-3]}"  # strip .py
            try:
                await self.load_extension(extension)
                log(f"Loaded cog: {extension}")
            except Exception as exc:  # noqa: BLE001
                log(f"Failed to load cog {extension}: {exc}", LogLevel.ERROR)

    async def on_ready(self) -> None:
        """Called once the bot has connected and all cogs are ready."""
        assert self.user is not None  # self.user can theoretically be None before the connection is fully established
        log(f"Logged in as {self.user} (id: {self.user.id})")
        log("------")
