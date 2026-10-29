from datetime import date, timedelta

from helpers import NOON

from nublock.report import build_daily_report, format_duration, format_report
from nublock.storage import ActivitySession
from nublock.timeutils import local_day_bounds

DAY = date(2026, 10, 29)
DAY_START, DAY_END = local_day_bounds(DAY)


def session(
    process: str,
    start_minutes: float,
    minutes: float | None,
    productivity: str = "neutral",
    subcategory: str | None = "uncategorized",
    is_idle: bool = False,
) -> ActivitySession:
    started = NOON + timedelta(minutes=start_minutes)
    return ActivitySession(
        id=0,
        started_at=started,
        ended_at=None if minutes is None else started + timedelta(minutes=minutes),
        process_name=process,
        app_name=process,
        window_title=None,
        productivity=productivity,  # type: ignore[arg-type]
        subcategory=subcategory,
        is_idle=is_idle,
    )


def test_report_aggregates_by_category_and_app() -> None:
    sessions = [
        session("Code", 0, 30, "productive", "dev"),
        session("Google Chrome", 30, 10, "distracting", "video"),
        session("Google Chrome", 40, 5, "neutral", "uncategorized"),
        session("Code", 45, 15, "productive", "dev"),
        session("Code", 60, 20, "productive", "dev", is_idle=True),
        session("Finder", 80, None),  # recién abierta (sin heartbeat): 0 s
    ]
    report = build_daily_report(DAY, sessions, DAY_START, DAY_END)
    assert report.active_seconds == 60 * 60
    assert report.idle_seconds == 20 * 60
    assert report.by_productivity == {"productive": 45 * 60, "distracting": 600, "neutral": 300}
    assert report.by_subcategory[("distracting", "video")] == 600
    assert [(app.name, app.seconds, app.category) for app in report.top_apps] == [
        ("Code", 45 * 60, "productive/dev"),
        ("Google Chrome", 15 * 60, "distracting/video"),
    ]


def test_sessions_are_clipped_to_the_day() -> None:
    minutes_since_midnight = (NOON - DAY_START).total_seconds() / 60
    crossing = session("Code", -minutes_since_midnight - 30, 90, "productive", "dev")
    report = build_daily_report(DAY, [crossing], DAY_START, DAY_END)
    assert report.active_seconds == 60 * 60  # solo los 60 min que caen hoy


def test_format_report_shows_categories_and_top_apps() -> None:
    sessions = [
        session("Code", 0, 30, "productive", "dev"),
        session("Discord", 30, 10, "distracting", "messaging"),
    ]
    text = format_report(build_daily_report(DAY, sessions, DAY_START, DAY_END))
    assert "Tiempo por categoría:" in text
    assert "productive" in text and "30m 00s" in text and "75.0%" in text
    assert "Top apps:" in text and "1. Code" in text and "2. Discord" in text


def test_empty_report_has_hint() -> None:
    text = format_report(build_daily_report(DAY, [], DAY_START, DAY_END))
    assert "Sin actividad" in text


def test_format_duration() -> None:
    assert format_duration(42) == "42s"
    assert format_duration(312) == "5m 12s"
    assert format_duration(3720) == "1h 02m"
