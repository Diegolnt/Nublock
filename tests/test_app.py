"""Integración con fakes: tracker -> timers -> rules -> notifier (DoD de M2)."""

from datetime import timedelta

from helpers import NOON, FakeClock, RecordingNotifier, make_window

from nublock.app import NublockApp
from nublock.classifier import Classification
from nublock.config import Config
from nublock.storage import Repository
from nublock.tracker.platform.fake import FakeWindowProvider


def make_config(observe_only: bool, limit_minutes: float = 1) -> Config:
    return Config.model_validate(
        {
            "general": {"observe_only": observe_only},
            "classification_rules": [
                {
                    "match": {"process": "Instagram"},
                    "productivity": "distracting",
                    "subcategory": "social",
                },
            ],
            "rules": [
                {
                    "id": "social-daily-limit",
                    "type": "daily_limit",
                    "target": {"subcategory": "social"},
                    "limit_minutes": limit_minutes,
                    "action": "block",
                }
            ],
        }
    )


def run_app(app: NublockApp, clock: FakeClock, seconds: int) -> None:
    for _ in range(seconds):
        app.tick()
        clock.advance(1)


def test_limit_crossed_sends_notification_when_not_observe_only(repo: Repository) -> None:
    clock = FakeClock(NOON)
    notifier = RecordingNotifier()
    provider = FakeWindowProvider(make_window("Instagram"))
    app = NublockApp(make_config(observe_only=False), provider, repo, notifier, clock=clock)
    app.startup()
    run_app(app, clock, 59)
    assert notifier.messages == []
    run_app(app, clock, 30)
    assert len(notifier.messages) == 1
    title, message = notifier.messages[0]
    assert title == "Regla de Nublock" and "social-daily-limit" in message
    assert repo.count_interventions() == 1


def test_observe_only_records_but_never_notifies(repo: Repository) -> None:
    clock = FakeClock(NOON)
    notifier = RecordingNotifier()
    provider = FakeWindowProvider(make_window("Instagram"))
    app = NublockApp(make_config(observe_only=True), provider, repo, notifier, clock=clock)
    app.startup()
    run_app(app, clock, 300)
    app.tracker.close(clock())
    assert notifier.messages == []
    assert repo.count_interventions() == 0
    (session,) = repo.sessions_between(NOON, NOON + timedelta(hours=1))
    assert session.subcategory == "social"  # pero la actividad sí se registró


def test_startup_loads_todays_usage_from_database(repo: Repository) -> None:
    # Antes de reiniciar la app ya había 59 min de social hoy.
    session_id = repo.open_session(
        NOON - timedelta(hours=2),
        "Instagram",
        "Instagram",
        None,
        Classification("distracting", "social"),
        False,
    )
    repo.set_session_end(session_id, NOON - timedelta(hours=2) + timedelta(minutes=59))
    clock = FakeClock(NOON)
    notifier = RecordingNotifier()
    provider = FakeWindowProvider(make_window("Instagram"))
    app = NublockApp(
        make_config(observe_only=False, limit_minutes=60), provider, repo, notifier, clock=clock
    )
    app.startup()
    run_app(app, clock, 59)
    assert notifier.messages == []
    run_app(app, clock, 2)
    assert len(notifier.messages) == 1


def test_retention_deletes_old_sessions_on_startup(repo: Repository) -> None:
    old = NOON - timedelta(days=200)
    session_id = repo.open_session(old, "Old", None, None, Classification("neutral", None), False)
    repo.set_session_end(session_id, old + timedelta(minutes=5))
    app = NublockApp(
        Config(), FakeWindowProvider(), repo, RecordingNotifier(), clock=FakeClock(NOON)
    )
    app.startup()
    assert repo.sessions_between(old - timedelta(days=1), NOON) == []
