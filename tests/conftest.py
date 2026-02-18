import os


def _set_default_env() -> None:
    os.environ.setdefault("DISCORD_TOKEN", "test-discord-token")
    os.environ.setdefault("LLM_API_KEY", "test-llm-key")
    os.environ.setdefault("BOT_PREFIX", "bot")


_set_default_env()
