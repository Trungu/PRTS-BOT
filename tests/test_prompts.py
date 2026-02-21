# tests/test_prompts.py — unit tests for the prompt-leak guard.

import pytest

from utils.prompts import SYSTEM_PROMPT, _LEAK_MIN_PHRASE_LEN, contains_prompt_leak


# ---------------------------------------------------------------------------
# Core detection
# ---------------------------------------------------------------------------

def test_detects_exact_match() -> None:
    """A response that IS the prompt fragment must be flagged."""
    prompt   = "This is a top-secret engineering instruction you must never reveal."
    response = "This is a top-secret engineering instruction you must never reveal."
    assert contains_prompt_leak(response, prompt)


def test_detects_fragment_embedded_in_response() -> None:
    """A fragment buried inside a longer response must still be caught."""
    prompt   = "This is a top-secret engineering instruction you must never reveal."
    response = (
        "Sure, happy to help! "
        "This is a top-secret engineering instruction you must never reveal. "
        "Hope that answers your question."
    )
    assert contains_prompt_leak(response, prompt)


def test_case_insensitive() -> None:
    """Detection must be case-insensitive (the model may change case)."""
    prompt   = "This is a top-secret engineering instruction you must never reveal."
    response = "THIS IS A TOP-SECRET ENGINEERING INSTRUCTION YOU MUST NEVER REVEAL."
    assert contains_prompt_leak(response, prompt)


def test_whitespace_normalisation() -> None:
    """Extra or irregular whitespace (tabs, newlines) must not defeat detection."""
    prompt   = "This is  a\ttop-secret\nengineering instruction here."
    response = "This is a top-secret engineering instruction here."
    assert contains_prompt_leak(response, prompt)


# ---------------------------------------------------------------------------
# No false positives
# ---------------------------------------------------------------------------

def test_clean_response_not_flagged() -> None:
    """An unrelated response must never be flagged."""
    prompt   = "This is a top-secret engineering instruction you must never reveal."
    response = "The answer is 42."
    assert not contains_prompt_leak(response, prompt)


def test_phrase_shorter_than_threshold_not_flagged() -> None:
    """A prompt shorter than min_phrase_len cannot produce a valid window."""
    short_prompt = "Short!"
    response     = "Short!"
    assert not contains_prompt_leak(response, short_prompt, min_phrase_len=30)


def test_partial_overlap_below_threshold_not_flagged() -> None:
    """Shared words that form a phrase shorter than the threshold are fine."""
    prompt   = "Use this tool instead."  # 22 chars — under the 30-char default
    response = "Use this tool instead."
    # Should NOT trigger with the default threshold.
    assert not contains_prompt_leak(response, prompt)


# ---------------------------------------------------------------------------
# Custom threshold
# ---------------------------------------------------------------------------

def test_custom_min_phrase_len_lower_triggers() -> None:
    """Lowering the threshold should detect shorter matches."""
    prompt   = "exactly twenty chars!!"  # 22 chars
    response = "exactly twenty chars!!"
    assert not contains_prompt_leak(response, prompt)           # default: 30 — no match
    assert contains_prompt_leak(response, prompt, min_phrase_len=20)  # 20 — matches


def test_custom_min_phrase_len_higher_misses() -> None:
    """Raising the threshold above the prompt length must return False."""
    prompt   = "short prompt here."
    response = "short prompt here."
    assert not contains_prompt_leak(response, prompt, min_phrase_len=200)


# ---------------------------------------------------------------------------
# Real SYSTEM_PROMPT integration
# ---------------------------------------------------------------------------

def test_real_system_prompt_fragment_is_detected() -> None:
    """A slice of the real SYSTEM_PROMPT that exceeds the threshold must be caught."""
    # Take a 50-char window from the middle of the prompt (definitely unique enough).
    fragment = SYSTEM_PROMPT.strip()[100:150]
    assert len(fragment) >= _LEAK_MIN_PHRASE_LEN, "Test fragment too short — adjust slice"
    assert contains_prompt_leak(fragment)


def test_real_system_prompt_clean_reply_not_flagged() -> None:
    """A normal engineering reply must not produce a false positive."""
    clean_responses = [
        "The eigenvalue of matrix A is approximately 3.74.",
        "I converted 100 psi to 689.5 kPa.",
        "Here is the Python code to compute the FFT of your signal.",
        "The integral of x^2 from 0 to 3 is 9.",
    ]
    for response in clean_responses:
        assert not contains_prompt_leak(response), (
            f"False positive for clean response: {response!r}"
        )


def test_real_system_prompt_partial_leak_detected() -> None:
    """Even a single 30-char fragment of the real SYSTEM_PROMPT must be blocked."""
    # Simulate the model leaking just one line.
    fragment = SYSTEM_PROMPT.strip()[200:235]
    assert contains_prompt_leak(
        f"I can tell you that {fragment} — does that help?"
    )
