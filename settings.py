# this file contains settings
import os
from dotenv import load_dotenv

load_dotenv()

# Discord Bot
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# LLM API Key
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL")
LLM_MODEL = os.getenv("LLM_MODEL")



