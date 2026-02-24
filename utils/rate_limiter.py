# utils/rate_limiter.py — Per-user rate limiting with escalating stages.
#
# Design
# ------
# Three escalating stages protect the bot from spam:
#
#   Stage 1 (WARNING):    User hits WARNING_THRESHOLD messages in the time
#                         window.  A soft warning is returned but the message
#                         is still processed.
#   Stage 2 (RATE-LIMITED): User hits RATE_LIMIT messages in the time window.
#                         The message is rejected.
#   Stage 3 (COOLDOWN):  User has been rate-limited COOLDOWN_STRIKES times
#                         within COOLDOWN_WINDOW seconds.  ALL of their
#                         messages are rejected for COOLDOWN_DURATION seconds.
#
# The rate limiter is stateless across restarts — that is intentional.
# Restarting the bot clears all rate-limit state, which is a reasonable
# operational reset.

from __future__ import annotations

import time
from enum import Enum

from utils.logger import log, LogLevel


# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

# Maximum messages allowed per window before hard rejection.
RATE_LIMIT: int = 5

# Number of messages in the window that triggers a soft warning.
# Must be strictly less than RATE_LIMIT.
WARNING_THRESHOLD: int = 4

# Sliding window size in seconds.
WINDOW_SECONDS: float = 60.0

# How many rate-limit rejections within COOLDOWN_WINDOW trigger a cooldown.
COOLDOWN_STRIKES: int = 3

# Window in which strikes are counted (seconds).
COOLDOWN_WINDOW: float = 300.0  # 5 minutes

# How long the cooldown lasts (seconds).
COOLDOWN_DURATION: float = 120.0  # 2 minutes


# ---------------------------------------------------------------------------
# Result enum
# ---------------------------------------------------------------------------

class RateLimitResult(Enum):
    """Outcome of a rate-limit check."""
    ALLOWED = "allowed"            # Message is fine — process normally.
    WARNING = "warning"            # Soft warning — process but notify.
    RATE_LIMITED = "rate_limited"  # Hard rejection — do not process.
    COOLDOWN = "cooldown"          # Escalated rejection — user is cooling down.


# User-facing messages for each rejection / warning stage.
WARNING_MESSAGE: str = "⚠️ You're sending messages pretty fast — please slow down a little."
RATE_LIMITED_MESSAGE: str = "🚫 Rate limit reached. Please wait a moment before sending more messages."
COOLDOWN_MESSAGE: str = "🧊 You've been temporarily rate-limited for sending too many messages. Please wait a couple of minutes."


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

# user_id → list of Unix timestamps for messages inside the current window.
_message_timestamps: dict[int, list[float]] = {}

# user_id → list of Unix timestamps when they were rate-limited (for strike tracking).
_strike_timestamps: dict[int, list[float]] = {}

# user_id → Unix timestamp when their cooldown expires.
_cooldown_until: dict[int, float] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_rate_limit(user_id: int) -> RateLimitResult:
    """Check whether *user_id* is allowed to send a message right now.

    Call this once per incoming message.  The function records the timestamp
    automatically, so repeated calls *do* count as additional messages.

    Returns a `RateLimitResult` indicating what action the caller should take.
    """
    now = time.monotonic()

    # Stage 3 check — is the user currently in cooldown?
    if user_id in _cooldown_until:
        if now < _cooldown_until[user_id]:
            log(f"[RateLimiter] User {user_id} still in cooldown.", LogLevel.DEBUG)
            return RateLimitResult.COOLDOWN
        else:
            # Cooldown expired — clean up and let them through.
            del _cooldown_until[user_id]
            _strike_timestamps.pop(user_id, None)
            log(f"[RateLimiter] User {user_id} cooldown expired.", LogLevel.DEBUG)

    # Prune old timestamps outside the sliding window.
    cutoff = now - WINDOW_SECONDS
    timestamps = _message_timestamps.get(user_id, [])
    timestamps = [t for t in timestamps if t > cutoff]

    # Record this message.
    timestamps.append(now)
    _message_timestamps[user_id] = timestamps

    message_count = len(timestamps)

    # Stage 2 — hard rate limit.
    if message_count > RATE_LIMIT:
        _record_strike(user_id, now)
        log(f"[RateLimiter] User {user_id} rate-limited ({message_count}/{RATE_LIMIT} in window).", LogLevel.WARNING)
        return RateLimitResult.RATE_LIMITED

    # Stage 1 — soft warning.
    if message_count >= WARNING_THRESHOLD:
        # Only warn once (at exactly the threshold), don't spam warnings.
        if message_count == WARNING_THRESHOLD:
            log(f"[RateLimiter] User {user_id} warned ({message_count}/{RATE_LIMIT} in window).", LogLevel.INFO)
            return RateLimitResult.WARNING

        # Between WARNING_THRESHOLD+1 and RATE_LIMIT (inclusive) — allow silently.
        # This is the "last chance" zone: the user saw the warning but hasn't
        # hit the hard limit yet.
        return RateLimitResult.ALLOWED

    return RateLimitResult.ALLOWED


def reset_rate_limit(user_id: int) -> None:
    """Clear all rate-limit state for a single user.

    Useful for admin commands or testing.
    """
    _message_timestamps.pop(user_id, None)
    _strike_timestamps.pop(user_id, None)
    _cooldown_until.pop(user_id, None)


def reset_all() -> None:
    """Clear all rate-limit state for every user."""
    _message_timestamps.clear()
    _strike_timestamps.clear()
    _cooldown_until.clear()


def is_rate_limited(user_id: int) -> bool:
    """Return True if the user is currently in cooldown."""
    if user_id not in _cooldown_until:
        return False
    now = time.monotonic()
    if now < _cooldown_until[user_id]:
        return True
    # Expired — clean up.
    del _cooldown_until[user_id]
    _strike_timestamps.pop(user_id, None)
    return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _record_strike(user_id: int, now: float) -> None:
    """Record a rate-limit strike and check for cooldown escalation."""
    cutoff = now - COOLDOWN_WINDOW
    strikes = _strike_timestamps.get(user_id, [])
    strikes = [t for t in strikes if t > cutoff]
    strikes.append(now)
    _strike_timestamps[user_id] = strikes

    if len(strikes) >= COOLDOWN_STRIKES:
        _cooldown_until[user_id] = now + COOLDOWN_DURATION
        log(
            f"[RateLimiter] User {user_id} placed in cooldown for {COOLDOWN_DURATION}s "
            f"({len(strikes)} strikes in {COOLDOWN_WINDOW}s window).",
            LogLevel.WARNING,
        )
