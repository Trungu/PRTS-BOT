# settings.py — central config loader for the bot.
# All environment variables are read here so the rest of the codebase
# never touches os.getenv directly.
import os
from dotenv import load_dotenv
from typing import Optional, overload

# Load variables from the .env file into the process environment.
load_dotenv()

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

# Overloads let the type checker know that required=True (the default)
# always returns str, while required=False may return None.
@overload
def get_env_var(name: str, required: bool = ...) -> str: ...
@overload
def get_env_var(name: str, required: bool) -> Optional[str]: ...
def get_env_var(name: str, required: bool = True) -> Optional[str]:
    """Read an env var by name. Raises RuntimeError if it is required but missing."""
    value = os.getenv(name)
    if required and (value is None or value.strip() == ""):
        raise RuntimeError(f"Required environment variable '{name}' is not set.")
    return value

# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------

# Bot token — must be set, raises immediately on startup if missing.
DISCORD_TOKEN = get_env_var("DISCORD_TOKEN")

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

# API key for the language model provider (e.g. Groq).
LLM_API_KEY = get_env_var("LLM_API_KEY")
# Optional: override the default API endpoint (e.g. a local OpenAI-compatible server).
LLM_BASE_URL = get_env_var("LLM_BASE_URL", required=False)
# Optional: model name to use (e.g. 'llama3'). Falls back to provider default if unset.
LLM_MODEL = get_env_var("LLM_MODEL", required=False)

# ---------------------------------------------------------------------------
# Bot prefix
# ---------------------------------------------------------------------------

# The trigger word users type before a command (e.g. 'bot').
# Defaults to 'bot' if not set in .env.
BOT_PREFIX: str = get_env_var("BOT_PREFIX", required=False) or "bot"

# Pipe-separated list of suffixes that are also accepted after the prefix.
# e.g. " |, |. " allows: 'prts hello', 'prts, hello', 'prts. hello'
# Defaults to a plain space, comma+space, and period+space.
_smart_chars_raw: str = get_env_var("PREFIX_SMART_CHARS", required=False) or " |, |. "
PREFIX_SMART_CHARS: list[str] = [c for c in _smart_chars_raw.split("|") if c != ""]

# Whether the prefix match is case-sensitive.
# Defaults to False (case-insensitive), so 'BOT hello' works the same as 'bot hello'.
PREFIX_CASE_SENSITIVE: bool = (get_env_var("PREFIX_CASE_SENSITIVE", required=False) or "false").strip().lower() == "true"



