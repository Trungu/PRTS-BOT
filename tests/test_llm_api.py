import json

import pytest

from tools import llm_api


class DummyResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self) -> dict:
        return self._payload


def test_chat_plain_text_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "choices": [{"finish_reason": "stop", "message": {"content": "hello"}}]
    }

    def fake_post(*args, **kwargs):
        return DummyResponse(payload)

    monkeypatch.setattr(llm_api.requests, "post", fake_post)
    monkeypatch.setattr(llm_api.settings, "LLM_API_KEY", "key")
    monkeypatch.setattr(llm_api.settings, "LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setattr(llm_api.settings, "LLM_MODEL", "model-x")

    result = llm_api.chat("hi")
    assert result == "hello"


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
    monkeypatch.setattr(llm_api.settings, "LLM_API_KEY", "key")

    with pytest.raises(ValueError):
        llm_api.chat("hi")
