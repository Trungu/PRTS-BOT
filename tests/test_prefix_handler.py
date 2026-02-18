import importlib

import pytest
import settings
from utils import prefix_handler


def test_build_prefix_variants_case_insensitive() -> None:
    variants = prefix_handler._build_prefix_variants("PrTs", [" ", ", "], case_sensitive=False)
    assert variants == ["prts", "prts ", "prts, "]


def test_get_command_and_has_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setenv("BOT_PREFIX", "prts")
    monkeypatch.setenv("PREFIX_SMART_CHARS", " |, |. ")
    monkeypatch.setenv("PREFIX_CASE_SENSITIVE", "false")

    importlib.reload(settings)
    ph = importlib.reload(prefix_handler)

    assert ph.get_command("prts hello") == "hello"
    assert ph.get_command("PRTS, hello") == ", hello"
    assert ph.get_command("xprts hello") is None
    assert ph.has_prefix("prts. hello")
