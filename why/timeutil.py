"""UTC helpers. DuckDB stores naive UTC timestamps; JSON carries ISO 8601 with a trailing Z."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def as_utc(dt: datetime) -> datetime:
    """Aware UTC datetime. Naive input is taken as UTC, never as local time."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def to_iso(dt: datetime | None) -> str | None:
    return None if dt is None else as_utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str | None) -> datetime | None:
    return None if not value else as_utc(datetime.fromisoformat(value))


def to_naive_utc(dt: datetime | None) -> datetime | None:
    return None if dt is None else as_utc(dt).replace(tzinfo=None)
