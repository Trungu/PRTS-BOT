# tests/test_rate_limiter.py — Tests for utils/rate_limiter.py
from __future__ import annotations

import time
from typing import Any
from unittest.mock import patch

import pytest

import utils.rate_limiter as rl
from utils.rate_limiter import (
    RateLimitResult,
    check_rate_limit,
    is_rate_limited,
    reset_all,
    reset_rate_limit,
)


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    """Reset all rate-limiter state before every test."""
    reset_all()


# -----------------------------------------------------------------------
# Stage 1: warning at WARNING_THRESHOLD
# -----------------------------------------------------------------------


class TestWarning:
    def test_first_messages_are_allowed(self) -> None:
        for _ in range(rl.WARNING_THRESHOLD - 1):
            assert check_rate_limit(1) == RateLimitResult.ALLOWED

    def test_warning_fires_at_threshold(self) -> None:
        for _ in range(rl.WARNING_THRESHOLD - 1):
            check_rate_limit(1)
        assert check_rate_limit(1) == RateLimitResult.WARNING

    def test_warning_fires_only_once(self) -> None:
        for _ in range(rl.WARNING_THRESHOLD - 1):
            check_rate_limit(1)
        assert check_rate_limit(1) == RateLimitResult.WARNING
        # Next message between warning and limit should be ALLOWED.
        assert check_rate_limit(1) == RateLimitResult.ALLOWED


# -----------------------------------------------------------------------
# Stage 2: hard rate limit at RATE_LIMIT
# -----------------------------------------------------------------------


class TestRateLimit:
    def test_rate_limited_after_exceeding_limit(self) -> None:
        for _ in range(rl.RATE_LIMIT):
            check_rate_limit(1)
        # One more tips us over.
        assert check_rate_limit(1) == RateLimitResult.RATE_LIMITED

    def test_rate_limited_stays_rate_limited(self) -> None:
        for _ in range(rl.RATE_LIMIT + 1):
            check_rate_limit(1)
        assert check_rate_limit(1) == RateLimitResult.RATE_LIMITED

    def test_rate_limit_resets_after_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """After the sliding window expires, the user is allowed again."""
        base = time.monotonic()
        call_count = 0

        def advancing_monotonic() -> float:
            nonlocal call_count
            call_count += 1
            return base + call_count * 0.1  # each call is 0.1s apart

        monkeypatch.setattr(rl, "time", type("FakeTime", (), {
            "monotonic": staticmethod(advancing_monotonic),
        }))

        for _ in range(rl.RATE_LIMIT + 1):
            check_rate_limit(1)

        # Now jump past the window.
        def past_window() -> float:
            return base + rl.WINDOW_SECONDS + 10

        monkeypatch.setattr(rl, "time", type("FakeTime", (), {
            "monotonic": staticmethod(past_window),
        }))

        assert check_rate_limit(1) == RateLimitResult.ALLOWED


# -----------------------------------------------------------------------
# Stage 3: cooldown after repeated rate-limit strikes
# -----------------------------------------------------------------------


class TestCooldown:
    def _trigger_strikes(self, user_id: int, count: int) -> None:
        """Trigger *count* rate-limit strikes for *user_id*."""
        for _ in range(count):
            # Clear only message timestamps so the next burst starts fresh,
            # but preserve strike history so strikes accumulate.
            rl._message_timestamps.pop(user_id, None)
            for _ in range(rl.RATE_LIMIT + 1):
                check_rate_limit(user_id)

    def test_cooldown_after_enough_strikes(self) -> None:
        self._trigger_strikes(1, rl.COOLDOWN_STRIKES)
        assert check_rate_limit(1) == RateLimitResult.COOLDOWN

    def test_cooldown_persists(self) -> None:
        self._trigger_strikes(1, rl.COOLDOWN_STRIKES)
        assert check_rate_limit(1) == RateLimitResult.COOLDOWN
        assert check_rate_limit(1) == RateLimitResult.COOLDOWN

    def test_cooldown_expires(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._trigger_strikes(1, rl.COOLDOWN_STRIKES)
        assert check_rate_limit(1) == RateLimitResult.COOLDOWN

        # Jump past the cooldown duration.
        future = time.monotonic() + rl.COOLDOWN_DURATION + 10
        monkeypatch.setattr(rl, "time", type("FakeTime", (), {
            "monotonic": staticmethod(lambda: future),
        }))

        assert check_rate_limit(1) == RateLimitResult.ALLOWED

    def test_is_rate_limited_during_cooldown(self) -> None:
        self._trigger_strikes(1, rl.COOLDOWN_STRIKES)
        assert is_rate_limited(1) is True

    def test_is_rate_limited_false_normally(self) -> None:
        assert is_rate_limited(1) is False

    def test_is_rate_limited_false_after_expiry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._trigger_strikes(1, rl.COOLDOWN_STRIKES)
        future = time.monotonic() + rl.COOLDOWN_DURATION + 10
        monkeypatch.setattr(rl, "time", type("FakeTime", (), {
            "monotonic": staticmethod(lambda: future),
        }))
        assert is_rate_limited(1) is False


# -----------------------------------------------------------------------
# Per-user isolation
# -----------------------------------------------------------------------


class TestUserIsolation:
    def test_different_users_are_independent(self) -> None:
        for _ in range(rl.RATE_LIMIT + 1):
            check_rate_limit(1)
        assert check_rate_limit(1) == RateLimitResult.RATE_LIMITED
        # User 2 should be unaffected.
        assert check_rate_limit(2) == RateLimitResult.ALLOWED

    def test_reset_only_affects_target_user(self) -> None:
        for _ in range(rl.RATE_LIMIT + 1):
            check_rate_limit(1)
        for _ in range(rl.RATE_LIMIT + 1):
            check_rate_limit(2)
        reset_rate_limit(1)
        assert check_rate_limit(1) == RateLimitResult.ALLOWED
        assert check_rate_limit(2) == RateLimitResult.RATE_LIMITED


# -----------------------------------------------------------------------
# Reset helpers
# -----------------------------------------------------------------------


class TestResetHelpers:
    def test_reset_rate_limit_clears_user(self) -> None:
        for _ in range(rl.RATE_LIMIT + 1):
            check_rate_limit(42)
        assert check_rate_limit(42) == RateLimitResult.RATE_LIMITED
        reset_rate_limit(42)
        assert check_rate_limit(42) == RateLimitResult.ALLOWED

    def test_reset_all_clears_everything(self) -> None:
        for uid in (1, 2, 3):
            for _ in range(rl.RATE_LIMIT + 1):
                check_rate_limit(uid)
        reset_all()
        for uid in (1, 2, 3):
            assert check_rate_limit(uid) == RateLimitResult.ALLOWED

    def test_reset_nonexistent_user_is_safe(self) -> None:
        reset_rate_limit(9999)  # should not raise


# -----------------------------------------------------------------------
# Configuration / constants sanity checks
# -----------------------------------------------------------------------


class TestConfiguration:
    def test_warning_threshold_below_rate_limit(self) -> None:
        assert rl.WARNING_THRESHOLD < rl.RATE_LIMIT

    def test_window_is_positive(self) -> None:
        assert rl.WINDOW_SECONDS > 0

    def test_cooldown_duration_is_positive(self) -> None:
        assert rl.COOLDOWN_DURATION > 0

    def test_cooldown_window_is_positive(self) -> None:
        assert rl.COOLDOWN_WINDOW > 0

    def test_cooldown_strikes_is_positive(self) -> None:
        assert rl.COOLDOWN_STRIKES > 0


# -----------------------------------------------------------------------
# Result enum completeness
# -----------------------------------------------------------------------


class TestRateLimitResultEnum:
    def test_all_values_exist(self) -> None:
        assert RateLimitResult.ALLOWED.value == "allowed"
        assert RateLimitResult.WARNING.value == "warning"
        assert RateLimitResult.RATE_LIMITED.value == "rate_limited"
        assert RateLimitResult.COOLDOWN.value == "cooldown"

    def test_enum_has_four_members(self) -> None:
        assert len(RateLimitResult) == 4


# -----------------------------------------------------------------------
# Message constants are non-empty
# -----------------------------------------------------------------------


class TestMessages:
    def test_warning_message_is_non_empty(self) -> None:
        assert len(rl.WARNING_MESSAGE) > 0

    def test_rate_limited_message_is_non_empty(self) -> None:
        assert len(rl.RATE_LIMITED_MESSAGE) > 0

    def test_cooldown_message_is_non_empty(self) -> None:
        assert len(rl.COOLDOWN_MESSAGE) > 0
