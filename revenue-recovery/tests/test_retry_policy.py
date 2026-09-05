"""Tests for app.core.retry_policy."""

import pytest

from app.core.retry_policy import RetryPolicy


class TestRetryPolicy:
    def test_max_attempts_derived_from_delay_list_length(self):
        policy = RetryPolicy(delay_minutes=[30, 360, 1440])
        assert policy.max_attempts == 3

    def test_is_exhausted_false_below_max(self):
        policy = RetryPolicy(delay_minutes=[30, 360, 1440])
        assert policy.is_exhausted(0) is False
        assert policy.is_exhausted(2) is False

    def test_is_exhausted_true_at_or_above_max(self):
        policy = RetryPolicy(delay_minutes=[30, 360, 1440])
        assert policy.is_exhausted(3) is True
        assert policy.is_exhausted(4) is True

    def test_delay_for_attempt_uses_correct_index(self):
        policy = RetryPolicy(delay_minutes=[30, 360, 1440])
        assert policy.delay_for_attempt(1).total_seconds() == 30 * 60
        assert policy.delay_for_attempt(2).total_seconds() == 360 * 60
        assert policy.delay_for_attempt(3).total_seconds() == 1440 * 60

    def test_delay_for_attempt_out_of_range_raises(self):
        policy = RetryPolicy(delay_minutes=[30, 360, 1440])
        with pytest.raises(ValueError):
            policy.delay_for_attempt(0)
        with pytest.raises(ValueError):
            policy.delay_for_attempt(4)

    def test_scheduled_at_for_attempt_is_in_the_future(self):
        from datetime import datetime, timezone

        policy = RetryPolicy(delay_minutes=[30])
        scheduled = policy.scheduled_at_for_attempt(1)
        assert scheduled > datetime.now(timezone.utc)
