import os

import pytest


def _set_default_env() -> None:
    os.environ.setdefault("DISCORD_TOKEN", "test-discord-token")
    os.environ.setdefault("LLM_API_KEY", "test-llm-key")


_set_default_env()


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> None:
    """Ensure rate-limiter state never leaks between tests."""
    from utils.rate_limiter import reset_all
    reset_all()
