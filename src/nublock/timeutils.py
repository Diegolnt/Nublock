"""Helpers de fechas. En la DB todo es ISO 8601 UTC; al mostrar se usa la hora local."""

from datetime import UTC, date, datetime, time, timedelta


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_iso(moment: datetime) -> str:
    """datetime con timezone -> '2026-10-29T15:19:00.123Z'."""
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def from_iso(text: str) -> datetime:
    """Inverso de `to_iso` (fromisoformat acepta el sufijo 'Z' desde Python 3.11)."""
    return datetime.fromisoformat(text)


def local_day_bounds(day: date) -> tuple[datetime, datetime]:
    """Inicio y fin (exclusivo) de un día en la timezone local del sistema, como UTC."""
    # Un datetime naive + .astimezone() se interpreta como hora local (respeta DST).
    start = datetime.combine(day, time.min).astimezone()
    end = datetime.combine(day + timedelta(days=1), time.min).astimezone()
    return start.astimezone(UTC), end.astimezone(UTC)


def overlap_seconds(
    start: datetime, end: datetime, window_start: datetime, window_end: datetime
) -> float:
    """Segundos en que [start, end) se superpone con [window_start, window_end)."""
    seconds = (min(end, window_end) - max(start, window_start)).total_seconds()
    return max(0.0, seconds)
