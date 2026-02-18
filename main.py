# main.py — entry point for the Discord bot.
# Defines the client, registers event handlers, and starts the bot.
import discord
from settings import DISCORD_TOKEN
import settings
from utils.prefix_handler import get_command, has_prefix

class MyClient(discord.Client):
    async def on_ready(self):
        """Called once the bot has successfully connected to Discord."""
        print(f'Logged on as {self.user}!')

    async def on_message(self, message):
        """Called for every message the bot can see."""
        # Ignore messages from the bot itself or other bots.
        if message.author == self.user or message.author.bot:
            return

        # Strip the prefix (and any smart-char variant) from the message.
        # Returns None if the message doesn't start with a valid prefix.
        command = get_command(message.content)
        if command is None:
            return

        # --- Commands ---
        if command.lower() == 'hello':
            await message.channel.send('Hello!')

# Enable the message content intent so on_message receives message text.
intents = discord.Intents.default()
intents.message_content = True

client = MyClient(intents=intents)
client.run(settings.DISCORD_TOKEN)
