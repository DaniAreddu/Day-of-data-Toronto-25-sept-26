"""Time handling. Every timestamp in this project is UTC.

Two clocks exist on purpose and are always labelled separately:

* the fixed *scenario clock* (``DEMO_CLOCK_UTC``) is the business "as-of" time used for
  freshness SLAs, so the narrative is identical on every run;
* the *wall clock* records when a pipeline actually executed (observability).
"""

from __future__ import annotations

from datetime import UTC, datetime

DEMO_CLOCK_UTC = datetime(2026, 9, 26, 18, 0, 0, tzinfo=UTC)
DEMO_SEED = 20260926


def wall_clock_utc() -> datetime:
    return datetime.now(UTC)


def parse_utc(value: str | datetime | None) -> datetime | None:
    """Parse an ISO-8601 or SQL-style timestamp and return an aware UTC datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    text = str(value).strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def format_utc(value: datetime | None) -> str:
    if value is None:
        return "never"
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def minutes_between(earlier: datetime, later: datetime) -> int:
    return int((later - earlier).total_seconds() // 60)
