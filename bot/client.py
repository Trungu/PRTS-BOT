# bot/client.py — Bot subclass with cog auto-loading and lifecycle hooks.
from __future__ import annotations

import asyncio
import os
from typing import Awaitable, Callable
import discord
import settings
from discord.ext import commands

from utils.logger import log, LogLevel
from utils.prefix_handler import get_command
from utils.admin import is_admin_only, is_allowed, is_banned
from utils.crisis_detector import detect_crisis, CRISIS_RESPONSE
from utils.rate_limiter import (
    check_rate_limit,
    RateLimitResult,
    WARNING_MESSAGE,
    RATE_LIMITED_MESSAGE,
    COOLDOWN_MESSAGE,
)
from utils.channel_memory import remember_message

# Type alias for a command handler: receives a Message and the stripped command string.
CommandHandler = Callable[[discord.Message, str], Awaitable[None]]
# Type alias for the LLM fallback handler: receives a Message and the prompt string.
LLMHandler = Callable[[discord.Message, str], Awaitable[None]]

_MEMORY_EXCLUDED_COMMAND_PREFIXES = (
    "delete count",
    "delete time",
    "delete response",
)


def _should_remember_message(message: discord.Message) -> bool:
    """Return False for operational commands that should not enter channel memory."""
    content = str(getattr(message, "content", "") or "")
    command = get_command(content)
    if command is None:
        return True
    normalized = command.strip().lower()
    return not any(
        normalized == prefix or normalized.startswith(prefix + " ")
        for prefix in _MEMORY_EXCLUDED_COMMAND_PREFIXES
    )


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
        # Serialises concurrent LLM requests so responses never interleave.
        self._llm_lock: asyncio.Lock = asyncio.Lock()

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

    async def _is_reply_to_bot(self, message: discord.Message) -> bool:
        """Return True when *message* is a reply to a message authored by this bot."""
        if not settings.REPLY_TRIGGER_ENABLED or self.user is None:
            return False

        ref = getattr(message, "reference", None)
        if ref is None:
            return False

        target = getattr(ref, "resolved", None)
        if target is None:
            ref_message_id = getattr(ref, "message_id", None)
            if ref_message_id is None:
                return False
            try:
                target = await message.channel.fetch_message(ref_message_id)
            except Exception:
                return False

        target_author = getattr(target, "author", None)
        return bool(target_author and getattr(target_author, "id", None) == self.user.id)

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
        # Temporary in-memory channel history for optional LLM context lookup.
        if _should_remember_message(message):
            remember_message(
                channel_id=int(getattr(message.channel, "id", 0) or 0),
                author_name=getattr(message.author, "display_name", None) or str(message.author),
                content=message.content,
                author_is_bot=bool(getattr(message.author, "bot", False)),
                created_at=getattr(message, "created_at", None),
            )

        if message.author.bot:
            return

        # Crisis / distress gate — runs on ALL messages, no prefix required.
        # Sends emergency resources immediately and then continues normal
        # processing so any legitimate command is still handled.
        if detect_crisis(message.content):
            await message.channel.send(CRISIS_RESPONSE)

        command = get_command(message.content)
        if command is None and await self._is_reply_to_bot(message):
            command = message.content.strip()
        if command is None:
            return

        # Admin-only gate: reject non-admins when the mode is active.
        if is_admin_only() and not is_allowed(message.author.id):
            await message.channel.send("⛔ Admin-only mode is active.")
            return

        # Ban gate: reject banned users (admins bypass this).
        if is_banned(message.author.id) and not is_allowed(message.author.id):
            await message.channel.send("⛔ You have been banned from using this bot.")
            return

        # Rate-limit gate: admins bypass rate limiting entirely.
        if not is_allowed(message.author.id):
            rl_result = check_rate_limit(message.author.id)
            if rl_result == RateLimitResult.COOLDOWN:
                await message.channel.send(COOLDOWN_MESSAGE)
                return
            if rl_result == RateLimitResult.RATE_LIMITED:
                await message.channel.send(RATE_LIMITED_MESSAGE)
                return
            if rl_result == RateLimitResult.WARNING:
                await message.channel.send(WARNING_MESSAGE)
                # Do NOT return — the message is still processed after the warning.

        cmd = command.lower().strip()

        # Try longest registered key first to support multi-word commands
        # like "clear history" before a shorter key like "clear".
        for key in sorted(self._command_handlers, key=len, reverse=True):
            if cmd == key or cmd.startswith(key + " "):
                await self._command_handlers[key](message, command)
                return

        # Nothing matched — hand off to the LLM fallback.
        # The lock ensures requests are processed one at a time so concurrent
        # users' responses never interleave with each other.
        if self._llm_handler is not None:
            async with self._llm_lock:
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

         # What commands exist locally (before syncing)?
        local = [c.name for c in self.tree.get_commands()]
        log(f"[Slash] Local tree commands: {local}")

        synced = await self.tree.sync()
        log(f"[Slash] Synced global: {[c.name for c in synced]}")

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
