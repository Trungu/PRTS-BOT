import importlib

import pytest
import settings
from utils import prefix_handler


def test_build_prefix_variants_case_insensitive() -> None:
    variants = prefix_handler._build_prefix_variants(["PrTs"], [" ", ", "], case_sensitive=False)
    # Variants must be sorted longest-first so smart-char prefixes are tried
    # before the bare prefix, preventing 'bot, hello' → ', hello'.
    assert variants == ["prts, ", "prts ", "prts"]


def test_get_command_and_has_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BOT_PREFIX", ["prts"])
    monkeypatch.setattr(settings, "PREFIX_SMART_CHARS", [" ", ", ", ". "])
    monkeypatch.setattr(settings, "PREFIX_CASE_SENSITIVE", False)

    ph = importlib.reload(prefix_handler)

    assert ph.get_command("prts hello") == "hello"
    assert ph.get_command("PRTS, hello") == "hello"
    assert ph.get_command("xprts hello") is None
    assert ph.has_prefix("prts. hello")
