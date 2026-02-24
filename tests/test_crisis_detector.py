# tests/test_crisis_detector.py — Tests for utils/crisis_detector.py
from __future__ import annotations

import pytest

from utils.crisis_detector import detect_crisis, CRISIS_RESPONSE


# ---------------------------------------------------------------------------
# True positives — these must always trigger
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    # Suicidal ideation
    "I want to kill myself",
    "I'm thinking about killing myself",
    "I'm going to end my life",
    "I want to end it all",
    "I want to take my life",
    "I want to die",
    "I wanna die",
    "die today",
    "die tonight",
    "die by suicide",
    # Self-harm
    "I've been hurting myself",
    "I keep cutting myself",
    "I engage in self harm",
    "self-harm is what I do",
    "I want to slit my wrists",
    # Hopelessness
    "there's no reason to live",
    "I have nothing to live for",
    "I don't want to live anymore",
    "I dont want to be alive",
    "I can't go on",
    "I cant go on like this",
    "life isn't worth living",
    "life is not worth anything",
    "I'd be better off dead",
    "everyone would be better off without me",
    "there's no point in living",
    "no point anymore",
    # Methods
    "I'm going to overdose on pills",
    "I want to hang myself",
    "I'm hanging myself",
    "jump off a bridge",
    "jump off the bridge",
    "I want to shoot myself",
    # Single-word crisis terms
    "I feel suicidal",
    "this is a suicide note",
    # Case insensitivity
    "KILL MYSELF",
    "Kill Myself",
    "SUICIDE",
    "Suicidal",
])
def test_detect_crisis_true_positives(text: str) -> None:
    assert detect_crisis(text) is True, f"Expected crisis detected in: {text!r}"


# ---------------------------------------------------------------------------
# False positives — these must NOT trigger
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    # Common informal / hyperbolic phrases in a technical context
    "I want to kill this bug",
    "kill it with fire",
    "this task is killing me",
    "I'm dying of laughter",
    "this code is dead",
    "the process died",
    "I killed the container",
    "rm -rf will delete everything",
    # Normal technical discussion
    "calculate 2 + 2",
    "run my Python script",
    "hello world",
    "what is the speed of light",
    "how do I reverse a linked list",
    # Casual conversation
    "I love this project",
    "the plants died in the drought",
    "the show ended last night",
    "game over",
    "this is killing my battery",
    "I am dead tired",
    # Partial word matches that should NOT trigger (word-boundary tests)
    "genocidal tendencies song",   # contains 'cidal' but not 'suicidal'
])
def test_detect_crisis_false_positives(text: str) -> None:
    assert detect_crisis(text) is False, f"Unexpected crisis detected in: {text!r}"


# ---------------------------------------------------------------------------
# CRISIS_RESPONSE content checks
# ---------------------------------------------------------------------------

def test_crisis_response_contains_988() -> None:
    """US crisis line must be present."""
    assert "988" in CRISIS_RESPONSE


def test_crisis_response_contains_crisis_text_line() -> None:
    """Crisis Text Line short code must be present."""
    assert "741741" in CRISIS_RESPONSE


def test_crisis_response_contains_international_link() -> None:
    """International resource link must be present."""
    assert "iasp.info" in CRISIS_RESPONSE


def test_crisis_response_contains_emergency_number() -> None:
    """At least one emergency services number must be mentioned."""
    assert "911" in CRISIS_RESPONSE or "999" in CRISIS_RESPONSE or "112" in CRISIS_RESPONSE


def test_crisis_response_is_non_empty() -> None:
    assert len(CRISIS_RESPONSE.strip()) > 0
