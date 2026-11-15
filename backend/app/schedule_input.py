"""Parsing and bounds-checking the requested publish time.

The browser sends an absolute UTC instant (its local picker value converted
with toISOString), so the server never has to guess a timezone. Everything is
stored in one canonical UTC format.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Tolerance for clock skew between browser and server, and for the seconds
# that pass between picking a time and the request arriving.
PAST_TOLERANCE = timedelta(minutes=2)
MAX_FUTURE = timedelta(days=365)


@dataclass(frozen=True)
class ScheduleResult:
    moment: datetime
    problem: str | None = None

    @property
    def ok(self) -> bool:
        return self.problem is None


def parse_schedule(raw: str, now: datetime | None = None) -> ScheduleResult:
    """Empty or "now" means publish immediately."""
    now = now or datetime.now(timezone.utc)

    cleaned = (raw or "").strip()
    if not cleaned or cleaned.lower() == "now":
        return ScheduleResult(moment=now)

    try:
        # fromisoformat does not accept a trailing Z before Python 3.11+.
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return ScheduleResult(
            moment=now,
            problem=f"Could not read '{raw}' as a date and time.",
        )

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)

    if parsed < now - PAST_TOLERANCE:
        return ScheduleResult(
            moment=parsed,
            problem="That time is in the past.",
        )

    if parsed > now + MAX_FUTURE:
        return ScheduleResult(
            moment=parsed,
            problem="That is more than a year away.",
        )

    # A time a hair in the past (clock skew) just means now.
    return ScheduleResult(moment=max(parsed, now))


def is_due(scheduled: datetime, now: datetime | None = None) -> bool:
    return scheduled <= (now or datetime.now(timezone.utc))
