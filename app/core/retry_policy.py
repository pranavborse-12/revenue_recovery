"""
RetryPolicy: the single place retry delays and max attempts are defined.

Backed by Settings.RETRY_DELAY_MINUTES (see app/core/config.py). Max
attempts is *derived* from the length of that list rather than stored as
a separate setting -- this makes it structurally impossible for
"max attempts" and "how many delays we've defined" to disagree.

Attempt numbering is 1-based (attempt_number=1 is the first retry),
matching RecoveryAction.attempt_number.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings


@dataclass(frozen=True)
class RetryPolicy:
    delay_minutes: list[int]

    @property
    def max_attempts(self) -> int:
        return len(self.delay_minutes)

    def is_exhausted(self, attempt_count: int) -> bool:
        """True once attempt_count has reached or passed max_attempts."""
        return attempt_count >= self.max_attempts

    def delay_for_attempt(self, attempt_number: int) -> timedelta:
        """
        Delay to wait before executing the given attempt_number (1-based).

        Raises ValueError for an attempt number outside the configured
        policy -- callers should check is_exhausted() first.
        """
        if attempt_number < 1 or attempt_number > self.max_attempts:
            raise ValueError(
                f"attempt_number={attempt_number} is outside policy range "
                f"1..{self.max_attempts}"
            )
        return timedelta(minutes=self.delay_minutes[attempt_number - 1])

    def scheduled_at_for_attempt(self, attempt_number: int) -> datetime:
        """The wall-clock time attempt_number should run at, from now."""
        return datetime.now(timezone.utc) + self.delay_for_attempt(attempt_number)


def get_retry_policy() -> RetryPolicy:
    """
    Build a RetryPolicy from current Settings.

    Not cached (unlike get_settings()) -- it's cheap to construct and
    tests frequently need to override Settings.RETRY_DELAY_MINUTES per
    test case, which a cached policy would fight against.
    """
    settings = get_settings()
    return RetryPolicy(delay_minutes=list(settings.RETRY_DELAY_MINUTES))
