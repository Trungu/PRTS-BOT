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
    assert isinstance(settings.LLM_PROVIDER, str)
    assert settings.LLM_PROVIDER in {"groq", "ollama"}
    assert isinstance(settings.LLM_REQUEST_TIMEOUT_SECONDS, int)
    assert settings.LLM_REQUEST_TIMEOUT_SECONDS >= 5
    assert isinstance(settings.REPLY_TRIGGER_ENABLED, bool)
    assert isinstance(settings.RECENT_CONTEXT_ENABLED, bool)
    assert isinstance(settings.RECENT_CONTEXT_MESSAGE_COUNT, int)
    assert settings.RECENT_CONTEXT_MESSAGE_COUNT >= 1
    assert isinstance(settings.TEMPORARY_MEMORY_ENABLED, bool)
    assert isinstance(settings.TEMP_MEMORY_BUFFER_SIZE, int)
    assert settings.TEMP_MEMORY_BUFFER_SIZE >= 10
    assert isinstance(settings.TEMP_MEMORY_MAX_LOOKBACK, int)
    assert settings.TEMP_MEMORY_MAX_LOOKBACK >= 5
    assert isinstance(settings.BOT_PREFIX, list)
    assert all(isinstance(p, str) for p in settings.BOT_PREFIX)
    assert len(settings.BOT_PREFIX) > 0
    assert isinstance(settings.PREFIX_SMART_CHARS, list)
    assert all(isinstance(c, str) for c in settings.PREFIX_SMART_CHARS)
    assert isinstance(settings.PREFIX_CASE_SENSITIVE, bool)
    assert isinstance(settings.KATEX_MAX_WIDTH_PX, int)
    assert settings.KATEX_MAX_WIDTH_PX >= 200
    assert isinstance(settings.KATEX_MAX_HEIGHT_PX, int)
    assert settings.KATEX_MAX_HEIGHT_PX >= 80
    assert isinstance(settings.LATEX_RENDERER, str)
    assert settings.LATEX_RENDERER in {"mathjax", "matplotlib"}
    assert isinstance(settings.LATEX_RENDERER_FALLBACK, bool)
    assert isinstance(settings.KATEX_RENDER_SCALE, float)
    assert settings.KATEX_RENDER_SCALE >= 0.3
    assert isinstance(settings.KATEX_ADAPTIVE_SCALE, bool)
    assert isinstance(settings.KATEX_RENDER_PAD_PX, int)
    assert settings.KATEX_RENDER_PAD_PX >= 0
    assert isinstance(settings.TOOLCALL_SILENT, bool)
    assert isinstance(settings.SHOW_TOOLCALL_NOTICES, bool)
    assert isinstance(settings.GLOBAL_SILENT, bool)
