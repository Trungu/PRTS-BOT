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


def _parse_pipe_list(value: str | None, default: list[str]) -> list[str]:
    """Parse a pipe-delimited env var (e.g. 'a|b|c') into a list."""
    if value is None:
        return default
    parts = value.split("|")
    # Keep whitespace tokens like " " because they are meaningful for
    # PREFIX_SMART_CHARS; only drop truly empty tokens.
    parsed = [part for part in parts if part != ""]
    return parsed or default


def _parse_bool(value: str | None, default: bool) -> bool:
    """Parse common true/false env strings with a fallback default."""
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default

# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------

# Bot token — must be set, raises immediately on startup if missing.
DISCORD_TOKEN = get_env_var("DISCORD_TOKEN")

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

# API key for the language model provider.
LLM_API_KEY = get_env_var("LLM_API_KEY")
# Optional: override the default API endpoint (e.g. a local OpenAI-compatible server).
LLM_BASE_URL = get_env_var("LLM_BASE_URL", required=False)
# Optional: model name to use (e.g. 'llama3'). Falls back to provider default if unset.
LLM_MODEL = get_env_var("LLM_MODEL", required=False)

# ---------------------------------------------------------------------------
# Bot prefix
# ---------------------------------------------------------------------------

# The trigger word(s) users type before a command. Multiple prefixes are supported.
# Required: define BOT_PREFIX in .env (use "|" to separate multiple prefixes).
BOT_PREFIX: list[str] = _parse_pipe_list(get_env_var("BOT_PREFIX"), [])
if not BOT_PREFIX:
    raise RuntimeError("Required environment variable 'BOT_PREFIX' is empty.")

# Suffixes that are also accepted after the prefix.
# e.g. [" ", ", ", ". "] allows: 'gemma hello', 'gemma, hello', 'gemma. hello'
PREFIX_SMART_CHARS: list[str] = _parse_pipe_list(
    get_env_var("PREFIX_SMART_CHARS", required=False),
    [" ", ", ", ". "],
)

# Whether the prefix match is case-sensitive.
PREFIX_CASE_SENSITIVE: bool = _parse_bool(
    get_env_var("PREFIX_CASE_SENSITIVE", required=False),
    False,
)

# ---------------------------------------------------------------------------
# KaTeX / math renderer
# ---------------------------------------------------------------------------

# Background colour: "none" for transparent, or a hex string e.g. "#2b2d31".
KATEX_BG_COLOR: str = "none"

# Math/text colour. #CCCCCC is readable on Discord's dark-mode background.
KATEX_FG_COLOR: str = "#CCCCCC"

# Font size in points.
KATEX_FONT_SIZE: int = 18

# DPI of the saved PNG.
KATEX_DPI: int = 200

# ---------------------------------------------------------------------------
# Silent mode
# ---------------------------------------------------------------------------

# If True, tool-call notification messages are sent as silent Discord messages
# (suppress notifications — the bell-with-slash icon). Users still see them.
TOOLCALL_SILENT: bool = True

# If True, EVERY message the bot sends (replies, tool notices, errors) is silent.
# Overrides TOOLCALL_SILENT.
GLOBAL_SILENT: bool = False

# ---------------------------------------------------------------------------
# Smart message cutoff
# ---------------------------------------------------------------------------

# If True, long replies are split at natural language boundaries (paragraph,
# sentence, word) rather than a hard character-count chop.
# If False, replies are still safely split at 2000 chars (no crash), just
# without trying to find a clean break point.
SMART_CUTOFF: bool = True

# ---------------------------------------------------------------------------
# Google Calendar / OAuth
# ---------------------------------------------------------------------------

CLIENT_ID = get_env_var("CLIENT_ID", required=False)
CLIENT_SECRET = get_env_var("CLIENT_SECRET", required=False)
OAUTH_BASE_URL = get_env_var("OAUTH_BASE_URL", required=False)
OAUTH_REDIRECT_URI = get_env_var("OAUTH_REDIRECT_URI", required=False)
GCAL_DB_PATH = get_env_var("GCAL_DB_PATH", required=False)

