import importlib

import pytest
import settings


def test_get_env_var_required_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOME_REQUIRED_VAR", raising=False)

    with pytest.raises(RuntimeError):
        settings.get_env_var("SOME_REQUIRED_VAR", required=True)


def test_get_env_var_optional_missing_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPTIONAL_VAR", raising=False)

    assert settings.get_env_var("OPTIONAL_VAR", required=False) is None


def test_prefix_and_silent_flags_parse_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setenv("BOT_PREFIX", "prts")
    monkeypatch.setenv("PREFIX_SMART_CHARS", " |, |. ")
    monkeypatch.setenv("PREFIX_CASE_SENSITIVE", "true")
    monkeypatch.setenv("TOOLCALL_SILENT", "true")
    monkeypatch.setenv("GLOBAL_SILENT", "false")

    reloaded = importlib.reload(settings)

    assert reloaded.BOT_PREFIX == "prts"
    assert reloaded.PREFIX_SMART_CHARS == [" ", ", ", ". "]
    assert reloaded.PREFIX_CASE_SENSITIVE is True
    assert reloaded.TOOLCALL_SILENT is True
    assert reloaded.GLOBAL_SILENT is False
