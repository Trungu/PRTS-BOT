# bot/cogs/general.py — general-purpose commands.
from __future__ import annotations

from typing import cast

import discord
from discord.ext import commands

from bot.client import Bot
from utils.logger import log


class General(commands.Cog):
    """General commands available to all users."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

        # Register every command this cog owns directly with the bot dispatcher.
        # The bot will route matching messages here; no manual command_registry
        # call is needed, and the LLM cog can never accidentally steal these.
        bot.register_command("hello",         self._hello)
        bot.register_command("clear history", self._clear_history)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _hello(self, message: discord.Message, _command: str) -> None:
        await message.channel.send("Hello!")

    async def _clear_history(self, message: discord.Message, _command: str) -> None:
        await message.channel.send("Clearing history is not implemented")


async def setup(bot: commands.Bot) -> None:
    """Entry point called by Bot.load_extension."""
    await bot.add_cog(General(cast(Bot, bot)))
