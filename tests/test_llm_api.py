import json

import pytest

from tools import llm_api


class DummyResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self) -> dict:
        return self._payload


def test_chat_plain_text_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "choices": [{"finish_reason": "stop", "message": {"content": "hello"}}]
    }

    captured = {}

    def fake_post(*args, **kwargs):
        captured["url"] = args[0]
        captured["headers"] = kwargs["headers"]
        return DummyResponse(payload)

    monkeypatch.setattr(llm_api.requests, "post", fake_post)
    monkeypatch.setattr(llm_api.settings, "LLM_PROVIDER", "groq", raising=False)
    monkeypatch.setattr(llm_api.settings, "LLM_API_KEY", "key")
    monkeypatch.setattr(llm_api.settings, "LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setattr(llm_api.settings, "LLM_MODEL", "model-x")

    result = llm_api.chat("hi")
    assert result == "hello"
    assert captured["url"] == "https://example.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer key"


def test_chat_tool_call_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    first_payload = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "calculator",
                                "arguments": json.dumps({"expression": "2+3"}),
                            },
                        }
                    ],
                },
            }
        ]
    }
    second_payload = {
        "choices": [{"finish_reason": "stop", "message": {"content": "5"}}]
    }
    responses = [DummyResponse(first_payload), DummyResponse(second_payload)]

    def fake_post(*args, **kwargs):
        return responses.pop(0)

    calls = []

    monkeypatch.setattr(llm_api.requests, "post", fake_post)
    monkeypatch.setattr(llm_api.settings, "LLM_PROVIDER", "groq", raising=False)
    monkeypatch.setattr(llm_api.settings, "LLM_API_KEY", "key")
    monkeypatch.setattr(llm_api.settings, "LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setattr(llm_api.settings, "LLM_MODEL", "model-x")

    result = llm_api.chat("calculate", on_tool_call=lambda n, a, r: calls.append((n, a, r)))

    assert result == "5"
    assert calls == [("calculator", {"expression": "2+3"}, "5")]


def test_chat_bad_shape_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(*args, **kwargs):
        return DummyResponse({"not": "expected"})

    monkeypatch.setattr(llm_api.requests, "post", fake_post)
    monkeypatch.setattr(llm_api.settings, "LLM_PROVIDER", "groq", raising=False)
    monkeypatch.setattr(llm_api.settings, "LLM_API_KEY", "key")

    with pytest.raises(ValueError):
        llm_api.chat("hi")


def test_chat_tool_args_transform_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    first_payload = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "calculator",
                                "arguments": json.dumps({"expression": "1+1"}),
                            },
                        }
                    ],
                },
            }
        ]
    }
    second_payload = {
        "choices": [{"finish_reason": "stop", "message": {"content": "3"}}]
    }
    responses = [DummyResponse(first_payload), DummyResponse(second_payload)]

    def fake_post(*args, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(llm_api.requests, "post", fake_post)
    monkeypatch.setattr(llm_api.settings, "LLM_PROVIDER", "groq", raising=False)
    monkeypatch.setattr(llm_api.settings, "LLM_API_KEY", "key")
    monkeypatch.setattr(llm_api.settings, "LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setattr(llm_api.settings, "LLM_MODEL", "model-x")

    result = llm_api.chat(
        "calculate",
        tool_args_transform=lambda name, args: {"expression": "1+2"} if name == "calculator" else args,
    )

    assert result == "3"


def test_chat_ollama_defaults_without_auth_header(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "choices": [{"finish_reason": "stop", "message": {"content": "local"}}]
    }
    captured = {}

    def fake_post(*args, **kwargs):
        captured["url"] = args[0]
        captured["headers"] = kwargs["headers"]
        captured["json"] = kwargs["json"]
        return DummyResponse(payload)

    monkeypatch.setattr(llm_api.requests, "post", fake_post)
    monkeypatch.setattr(llm_api.settings, "LLM_PROVIDER", "ollama", raising=False)
    monkeypatch.setattr(llm_api.settings, "LLM_API_KEY", None, raising=False)
    monkeypatch.setattr(llm_api.settings, "LLM_BASE_URL", None, raising=False)
    monkeypatch.setattr(llm_api.settings, "LLM_MODEL", None, raising=False)

    result = llm_api.chat("hi")

    assert result == "local"
    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
    assert "Authorization" not in captured["headers"]
    assert captured["json"]["model"] == "llama3.1:8b"


def test_chat_logs_http_error_response_body(monkeypatch: pytest.MonkeyPatch) -> None:
    logged = []

    def fake_post(*args, **kwargs):
        return DummyResponse({"error": {"message": "tools not supported"}}, status_code=400)

    monkeypatch.setattr(llm_api.requests, "post", fake_post)
    monkeypatch.setattr(llm_api, "log", lambda message, level=None, **kwargs: logged.append((message, level)))
    monkeypatch.setattr(llm_api.settings, "LLM_PROVIDER", "ollama", raising=False)
    monkeypatch.setattr(llm_api.settings, "LLM_API_KEY", None, raising=False)

    with pytest.raises(RuntimeError):
        llm_api.chat("hi")

    assert logged
    assert "tools not supported" in logged[0][0]
