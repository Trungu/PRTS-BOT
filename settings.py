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


def _parse_int(value: str | None, default: int, *, min_value: int = 1) -> int:
    """Parse an int env var with fallback and minimum clamp."""
    if value is None:
        return default
    try:
        parsed = int(value.strip())
    except Exception:
        return default
    return max(parsed, min_value)


def _parse_choice(value: str | None, default: str, allowed: set[str]) -> str:
    """Parse a case-insensitive enum-like env var with fallback."""
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in allowed:
        return normalized
    return default

# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------

# Bot token — must be set, raises immediately on startup if missing.
DISCORD_TOKEN = get_env_var("DISCORD_TOKEN")

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

# LLM backend selector. "groq" preserves the current hosted default;
# "ollama" enables local OpenAI-compatible requests against Ollama.
LLM_PROVIDER = _parse_choice(
    get_env_var("LLM_PROVIDER", required=False),
    "groq",
    {"groq", "ollama"},
)
# API key for the language model provider. Required for hosted backends,
# optional for local Ollama.
LLM_API_KEY = get_env_var("LLM_API_KEY", required=False)
if LLM_PROVIDER != "ollama" and (LLM_API_KEY is None or LLM_API_KEY.strip() == ""):
    raise RuntimeError(
        "Required environment variable 'LLM_API_KEY' is not set."
    )
# Optional: override the default API endpoint (e.g. a local OpenAI-compatible server).
LLM_BASE_URL = get_env_var("LLM_BASE_URL", required=False)
# Optional: model name to use (e.g. 'llama3'). Falls back to provider default if unset.
LLM_MODEL = get_env_var("LLM_MODEL", required=False)
# Default HTTP timeout for LLM requests.
LLM_REQUEST_TIMEOUT_SECONDS: int = _parse_int(
    get_env_var("LLM_REQUEST_TIMEOUT_SECONDS", required=False),
    120,
    min_value=5,
)

# ---------------------------------------------------------------------------
# Reply trigger
# ---------------------------------------------------------------------------

# If True, a message that replies directly to the bot can be processed even
# without the configured text prefix.
REPLY_TRIGGER_ENABLED: bool = _parse_bool(
    get_env_var("REPLY_TRIGGER_ENABLED", required=False),
    True,
)

# If True, include a small recent channel context window in every LLM prompt.
RECENT_CONTEXT_ENABLED: bool = _parse_bool(
    get_env_var("RECENT_CONTEXT_ENABLED", required=False),
    True,
)

# Number of recent prior channel messages to include in the default prompt context.
RECENT_CONTEXT_MESSAGE_COUNT: int = _parse_int(
    get_env_var("RECENT_CONTEXT_MESSAGE_COUNT", required=False),
    20,
    min_value=1,
)

# ---------------------------------------------------------------------------
# Temporary memory (channel history context)
# ---------------------------------------------------------------------------

# If True, enable in-memory channel history lookup tool for LLM context.
TEMPORARY_MEMORY_ENABLED: bool = _parse_bool(
    get_env_var("TEMPORARY_MEMORY_ENABLED", required=False),
    False,
)

# Max messages stored per channel in transient memory.
TEMP_MEMORY_BUFFER_SIZE: int = _parse_int(
    get_env_var("TEMP_MEMORY_BUFFER_SIZE", required=False),
    200,
    min_value=10,
)

# Hard cap for on-demand lookback requests from the model.
TEMP_MEMORY_MAX_LOOKBACK: int = _parse_int(
    get_env_var("TEMP_MEMORY_MAX_LOOKBACK", required=False),
    60,
    min_value=5,
)

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

# If True, send explicit tool-call notice messages (tool name/args/result) to
# Discord. Keep disabled in production to avoid exposing internal operations.
SHOW_TOOLCALL_NOTICES: bool = False

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

# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------

SUPABASE_URL = get_env_var("SUPABASE_URL", required=False)
SUPABASE_SERVICE_ROLE_KEY = get_env_var("SUPABASE_SERVICE_ROLE_KEY", required=False)
