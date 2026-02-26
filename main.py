# main.py — entry point. Creates the Bot and starts the event loop.
import os

from dotenv import load_dotenv
load_dotenv()

print("SUPABASE_URL loaded:", bool(os.getenv("SUPABASE_URL")))

from bot import Bot
from settings import DISCORD_TOKEN

if __name__ == "__main__":
    Bot().run(DISCORD_TOKEN)
