# main.py — entry point. Creates the Bot and starts the event loop.
import settings

from bot import Bot
from settings import DISCORD_TOKEN

if __name__ == "__main__":
    print("SUPABASE_URL loaded:", bool(settings.SUPABASE_URL))
    Bot().run(DISCORD_TOKEN)
