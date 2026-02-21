# utils/crisis_detector.py — Distress and crisis-signal detection for public safety.
#
# Purpose
# -------
# The bot is public-facing and watched by non-technical stakeholders.
# If a user sends a message containing signals of genuine distress (suicidal
# ideation, self-harm, extreme hopelessness) the bot must respond immediately
# with emergency resources — regardless of admin mode, command prefix, or
# whether the LLM is active.
#
# Design decisions
# ----------------
# * Detection runs on EVERY non-bot message, not just prefixed ones.
#   Someone in crisis may not address the bot formally.
# * False positives (sending crisis resources unnecessarily) are far less
#   harmful than false negatives (missing a real emergency).
# * Phrase matching is case-insensitive.
# * Regex word-boundary anchors (\b) are used for single terms that are
#   common in other contexts (e.g. "suicide", "suicidal") to avoid substring
#   collisions inside unrelated words.
# * The response message is intentionally brief, non-judgmental, and
#   contains internationally recognised hotlines.

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Crisis phrases
# ---------------------------------------------------------------------------
# Each entry is either:
#   - A plain substring (matched case-insensitively anywhere in the text), or
#   - A regex string (when it starts with \b, anchored at a word boundary).
#
# Guidelines for adding new entries:
#   • Add specific multi-word phrases before single-word entries.
#   • Prefer specificity over breadth to reduce false positives.
#   • Single words that appear often in non-distress contexts must use \b anchors.

_CRISIS_PHRASES: list[str] = [
    # --- Suicidal ideation ---
    "kill myself",
    "killing myself",
    "killed myself",
    "end my life",
    "end it all",
    "take my life",
    "took my life",
    "want to die",
    "wanna die",
    "going to die by",
    "die by suicide",
    "die today",
    "die tonight",
    # --- Self-harm ---
    "hurt myself",
    "hurting myself",
    "harm myself",
    "harming myself",
    "cut myself",
    "cutting myself",
    "self harm",
    "self-harm",
    "slit my wrists",
    "slit my",
    # --- Hopelessness / giving up ---
    "no reason to live",
    "nothing to live for",
    "don't want to live",
    "dont want to live",
    "don't want to be alive",
    "dont want to be alive",
    "can't go on",
    "cant go on",
    "can't do this anymore",
    "cant do this anymore",
    "not worth living",
    "life isn't worth",
    "life is not worth",
    "better off dead",
    "better off without me",
    "everyone would be better",
    "no point in living",
    "no point anymore",
    # --- Methods (specific enough to not false-positive) ---
    "overdose on",
    "hang myself",
    "hanging myself",
    "jump off a bridge",
    "jump off the bridge",
    "jump off a building",
    "shoot myself",
    # --- Crisis terms (word-boundary anchored single words) ---
    r"\bsuicidal\b",
    r"\bsuicide\b",
]

# Pre-compile for performance — done once at import time.
_COMPILED: list[re.Pattern[str]] = [
    re.compile(p if p.startswith(r"\b") else re.escape(p), re.IGNORECASE)
    for p in _CRISIS_PHRASES
]

# ---------------------------------------------------------------------------
# Emergency response
# ---------------------------------------------------------------------------

CRISIS_RESPONSE: str = (
    "💙 I noticed something in your message that concerns me. "
    "If you or someone you know is struggling, **please reach out — you are not alone**.\n\n"
    "🇺🇸 **988 Suicide & Crisis Lifeline** — call or text **988** (US)\n"
    "💬 **Crisis Text Line** — text **HOME** to **741741** (US / UK / CA / IE)\n"
    "🌍 **International resources** — <https://www.iasp.info/resources/Crisis_Centres/>\n"
    "🚨 **Emergency services** — call your local emergency number (**911** / **999** / **112**)\n\n"
    "❤️ You matter."
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_crisis(text: str) -> bool:
    """Return ``True`` if *text* contains a recognised distress signal.

    Matching is case-insensitive.  False positives are acceptable — sending
    crisis resources to someone who does not need them is harmless; failing
    to send them to someone who does is not.

    Parameters
    ----------
    text:
        The raw message content to inspect.
    """
    for pattern in _COMPILED:
        if pattern.search(text):
            return True
    return False
