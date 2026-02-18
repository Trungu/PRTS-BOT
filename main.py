import discord
import os
from dotenv import load_dotenv

load_dotenv()
_DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

class MyClient(discord.Client):
    async def on_ready(self):
        print(f'Logged on as {self.user}!')

    async def on_message(self, message):
        if message.author == self.user or message.author.bot:
            return
        if message.content.lower().startswith('prts hello'):
            await message.channel.send('Hello!')

intents = discord.Intents.default()
intents.message_content = True

client = MyClient(intents=intents)
client.run(_DISCORD_TOKEN)
