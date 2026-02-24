# tests/test_safety_responder.py — Tests for tools/toolcalls/safety_responder.py
from __future__ import annotations

import re

import pytest

from tools.toolcalls.safety_responder import (
    SAFETY_RESPONSE_TAG,
    CRISIS_RESPONSE,
    PR_DEFLECTION_RESPONSE,
    send_crisis_response,
    send_pr_deflection,
    CRISIS_TOOL_DEFINITION,
    PR_DEFLECTION_TOOL_DEFINITION,
)


# ---------------------------------------------------------------------------
# Sentinel tag presence
# ---------------------------------------------------------------------------

def test_send_crisis_response_contains_sentinel() -> None:
    result = send_crisis_response()
    assert f"[{SAFETY_RESPONSE_TAG}=crisis]" in result


def test_send_pr_deflection_contains_sentinel() -> None:
    result = send_pr_deflection("communist Russia")
    assert f"[{SAFETY_RESPONSE_TAG}=pr_deflection]" in result


def test_send_pr_deflection_includes_topic_in_result() -> None:
    result = send_pr_deflection("communist Russia")
    assert "communist Russia" in result


def test_send_pr_deflection_different_topics() -> None:
    r1 = send_pr_deflection("topic A")
    r2 = send_pr_deflection("topic B")
    assert "topic A" in r1
    assert "topic B" in r2
    # The sentinel type should be the same for any topic.
    assert f"[{SAFETY_RESPONSE_TAG}=pr_deflection]" in r1
    assert f"[{SAFETY_RESPONSE_TAG}=pr_deflection]" in r2


# ---------------------------------------------------------------------------
# Sentinel regex extractability
# ---------------------------------------------------------------------------

_SENTINEL_PATTERN = re.compile(
    rf"\[{re.escape(SAFETY_RESPONSE_TAG)}=([^\]]+)\]"
)


def test_crisis_sentinel_type_is_extractable() -> None:
    result = send_crisis_response()
    m = _SENTINEL_PATTERN.search(result)
    assert m is not None
    assert m.group(1).startswith("crisis")


def test_pr_sentinel_type_is_extractable() -> None:
    result = send_pr_deflection("test")
    m = _SENTINEL_PATTERN.search(result)
    assert m is not None
    assert m.group(1).startswith("pr_deflection")


# ---------------------------------------------------------------------------
# Response message content
# ---------------------------------------------------------------------------

def test_crisis_response_contains_988() -> None:
    assert "988" in CRISIS_RESPONSE


def test_crisis_response_contains_crisis_text_line() -> None:
    assert "741741" in CRISIS_RESPONSE


def test_crisis_response_is_nonempty() -> None:
    assert len(CRISIS_RESPONSE.strip()) > 0


def test_pr_deflection_response_is_nonempty() -> None:
    assert len(PR_DEFLECTION_RESPONSE.strip()) > 0


def test_pr_deflection_response_does_not_endorse_any_position() -> None:
    """The deflection should not take a stance — no yes/no/opinion words as whole words."""
    lowered = PR_DEFLECTION_RESPONSE.lower()
    for forbidden in ("yes", "oppose", "agree", "disagree"):
        assert not re.search(rf"\b{forbidden}\b", lowered), (
            f"PR_DEFLECTION_RESPONSE should not contain {forbidden!r} as a word"
        )


# ---------------------------------------------------------------------------
# Tool definitions structure
# ---------------------------------------------------------------------------

def test_crisis_tool_definition_structure() -> None:
    assert CRISIS_TOOL_DEFINITION["type"] == "function"
    fn = CRISIS_TOOL_DEFINITION["function"]
    assert fn["name"] == "send_crisis_response"
    assert "description" in fn
    assert len(fn["description"]) > 20
    assert fn["parameters"]["type"] == "object"


def test_pr_deflection_tool_definition_structure() -> None:
    assert PR_DEFLECTION_TOOL_DEFINITION["type"] == "function"
    fn = PR_DEFLECTION_TOOL_DEFINITION["function"]
    assert fn["name"] == "send_pr_deflection"
    assert "description" in fn
    assert len(fn["description"]) > 20
    props = fn["parameters"]["properties"]
    assert "topic" in props
    assert fn["parameters"]["required"] == ["topic"]


def test_crisis_tool_description_mentions_distress() -> None:
    desc = CRISIS_TOOL_DEFINITION["function"]["description"].lower()
    assert any(kw in desc for kw in ("distress", "suicidal", "self-harm", "risk"))


def test_pr_tool_description_mentions_politics() -> None:
    desc = PR_DEFLECTION_TOOL_DEFINITION["function"]["description"].lower()
    assert any(kw in desc for kw in ("politic", "geopolit", "opinion", "controversial"))
