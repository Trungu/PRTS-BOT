import pytest
import settings


def test_get_env_var_required_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOME_REQUIRED_VAR", raising=False)

    with pytest.raises(RuntimeError):
        settings.get_env_var("SOME_REQUIRED_VAR", required=True)


def test_get_env_var_optional_missing_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPTIONAL_VAR", raising=False)

    assert settings.get_env_var("OPTIONAL_VAR", required=False) is None


def test_config_values_have_correct_types() -> None:
    assert isinstance(settings.BOT_PREFIX, list)
    assert all(isinstance(p, str) for p in settings.BOT_PREFIX)
    assert len(settings.BOT_PREFIX) > 0
    assert isinstance(settings.PREFIX_SMART_CHARS, list)
    assert all(isinstance(c, str) for c in settings.PREFIX_SMART_CHARS)
    assert isinstance(settings.PREFIX_CASE_SENSITIVE, bool)
    assert isinstance(settings.TOOLCALL_SILENT, bool)
    assert isinstance(settings.GLOBAL_SILENT, bool)
