# bot/cogs/llm.py — LLM chat command with agentic tool-call support.
from __future__ import annotations

import asyncio
import json
import discord
from discord.ext import commands

from utils.logger import log, LogLevel
from utils.prompts import SYSTEM_PROMPT
from tools.llm_api import chat, MAX_TOOL_CALLS
import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _silent_flags() -> discord.MessageFlags:
    """Return MessageFlags with suppress_notifications set."""
    flags = discord.MessageFlags()
    flags.suppress_notifications = True
    return flags


def _should_silent_all() -> bool:
    return settings.GLOBAL_SILENT


def _should_silent_toolcall() -> bool:
    return settings.GLOBAL_SILENT or settings.TOOLCALL_SILENT


async def _send(channel: discord.abc.Messageable, content: str, *, force_silent: bool = False) -> None:
    """Send *content* to *channel*, applying silent flags when configured."""
    if _should_silent_all() or force_silent:
        await channel.send(content, silent=True)
    else:
        await channel.send(content)


class LLM(commands.Cog):
    """Commands that interact with the language model."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

        # Register as the catch-all fallback — only receives messages that no
        # other cog handler claimed, so it can never swallow a known command.
        bot.set_llm_handler(self._ask)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _ask(self, message: discord.Message, prompt: str) -> None:
        """Send *prompt* to the LLM and reply with the response."""
        log(
            f"[LLM] Prompt from {message.author} (#{message.channel}) "
            f"| {len(prompt)} chars: {prompt!r}"
        )

        loop = asyncio.get_running_loop()

        def on_tool_call(tool_name: str, args: dict, result: str) -> None:
            """Called from the worker thread each time the LLM uses a tool."""
            log(f"[LLM] Tool call: {tool_name}({args}) → {result!r}", LogLevel.DEBUG)

            # Format args compactly for the Discord message.
            args_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
            notice = f"🔧 **{tool_name}**({args_str}) → `{result}`"

            # Schedule the send back on the event loop from this thread.
            asyncio.run_coroutine_threadsafe(
                _send(message.channel, notice, force_silent=_should_silent_toolcall()),
                loop,
            )

        async with message.channel.typing():
            try:
                log(f"[LLM] Sending request to API (tool calls enabled, max={MAX_TOOL_CALLS})…", LogLevel.DEBUG)
                reply = await loop.run_in_executor(
                    None,
                    lambda: chat(
                        prompt,
                        system_prompt=SYSTEM_PROMPT,
                        on_tool_call=on_tool_call,
                    ),
                )
                log(
                    f"[LLM] Response received for {message.author} "
                    f"| {len(reply)} chars"
                )
            except Exception as exc:
                log(
                    f"[LLM] API error for {message.author} "
                    f"| prompt: {prompt!r} | {type(exc).__name__}: {exc}",
                    LogLevel.ERROR,
                )
                await _send(message.channel, f"⚠️ The LLM returned an error: `{exc}`")
                return

        # Discord messages cap at 2000 chars — split if needed.
        chunks = [reply[i:i+2000] for i in range(0, len(reply), 2000)]
        if len(chunks) > 1:
            log(f"[LLM] Reply split into {len(chunks)} chunks for {message.author}", LogLevel.DEBUG)
        for chunk in chunks:
            await _send(message.channel, chunk)


async def setup(bot: commands.Bot) -> None:
    """Entry point called by Bot.load_extension."""
    await bot.add_cog(LLM(bot))
