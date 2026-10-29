"""activity_sessions: agrupación (FR-02), títulos opcionales (FR-05), idle (FR-03) y gaps."""

from datetime import timedelta

from helpers import NOON, at, make_window

from nublock.classifier import Classifier
from nublock.config import ClassificationRule
from nublock.storage import ActivitySession, Repository
from nublock.tracker.platform.base import WindowInfo
from nublock.tracker.platform.fake import FakeWindowProvider
from nublock.tracker.tracker import ActivityTracker

YOUTUBE = ClassificationRule.model_validate(
    {"match": {"title_regex": "YouTube"}, "productivity": "distracting", "subcategory": "video"}
)


def make_tracker(
    provider: FakeWindowProvider,
    repo: Repository,
    *,
    store_window_titles: bool = True,
    idle_threshold_seconds: float = 120,
) -> ActivityTracker:
    return ActivityTracker(
        provider,
        Classifier([YOUTUBE]),
        repo,
        idle_threshold_seconds=idle_threshold_seconds,
        store_window_titles=store_window_titles,
    )


def all_sessions(repo: Repository) -> list[ActivitySession]:
    return repo.sessions_between(NOON - timedelta(days=1), NOON + timedelta(days=1))


def spans(repo: Repository) -> list[tuple[str, float, float | None, bool]]:
    """(process, inicio, fin, is_idle) en segundos relativos a NOON."""
    return [
        (
            s.process_name,
            (s.started_at - NOON).total_seconds(),
            (s.ended_at - NOON).total_seconds() if s.ended_at else None,
            s.is_idle,
        )
        for s in all_sessions(repo)
    ]


def run(
    tracker: ActivityTracker,
    provider: FakeWindowProvider,
    window: WindowInfo,
    start: int,
    end: int,
) -> None:
    """Un tick por segundo en [start, end) con `window` activa."""
    provider.window = window
    for second in range(start, end):
        tracker.tick(at(second))


# --- Agrupación en sesiones ----------------------------------------------------


def test_same_window_extends_a_single_session(repo: Repository) -> None:
    provider = FakeWindowProvider()
    tracker = make_tracker(provider, repo)
    run(tracker, provider, make_window("Code", "main.py"), 0, 300)
    tracker.close(at(300))
    assert spans(repo) == [("Code", 0, 300, False)]  # 300 ticks -> 1 fila


def test_window_change_closes_and_opens_sessions(repo: Repository) -> None:
    provider = FakeWindowProvider()
    tracker = make_tracker(provider, repo)
    run(tracker, provider, make_window("Code", "main.py"), 0, 10)
    run(tracker, provider, make_window("Google Chrome", "Docs"), 10, 15)
    run(tracker, provider, make_window("Code", "main.py"), 15, 20)
    tracker.close(at(20))
    assert spans(repo) == [
        ("Code", 0, 10, False),
        ("Google Chrome", 10, 15, False),
        ("Code", 15, 20, False),
    ]


def test_title_change_starts_new_session_and_is_classified(repo: Repository) -> None:
    provider = FakeWindowProvider()
    tracker = make_tracker(provider, repo)
    run(tracker, provider, make_window("Google Chrome", "Docs"), 0, 5)
    run(tracker, provider, make_window("Google Chrome", "Cats - YouTube"), 5, 8)
    tracker.close(at(8))
    first, second = all_sessions(repo)
    assert (first.window_title, first.productivity, first.subcategory) == (
        "Docs",
        "neutral",
        "uncategorized",
    )
    assert (second.window_title, second.productivity, second.subcategory) == (
        "Cats - YouTube",
        "distracting",
        "video",
    )


def test_titles_not_stored_when_disabled(repo: Repository) -> None:
    provider = FakeWindowProvider()
    tracker = make_tracker(provider, repo, store_window_titles=False)
    run(tracker, provider, make_window("Google Chrome", "Inbox (3) - secret subject"), 0, 5)
    # Otro título con la misma categoría: como el título no se guarda, sigue la misma fila.
    run(tracker, provider, make_window("Google Chrome", "Bank statement.pdf"), 5, 10)
    # Cambio de categoría: sí abre una sesión nueva.
    run(tracker, provider, make_window("Google Chrome", "Cats - YouTube"), 10, 12)
    tracker.close(at(12))
    sessions = all_sessions(repo)
    assert [s.window_title for s in sessions] == [None, None]
    assert [(s.subcategory, s.ended_at) for s in sessions] == [
        ("uncategorized", at(10)),
        ("video", at(12)),
    ]


def test_tick_returns_event_with_elapsed_seconds(repo: Repository) -> None:
    provider = FakeWindowProvider(make_window("Code"))
    tracker = make_tracker(provider, repo)
    first = tracker.tick(at(0))
    second = tracker.tick(at(1.5))
    assert first is not None and first.seconds == 0
    assert second is not None and second.seconds == 1.5
    assert second.classification.subcategory == "uncategorized"


def test_heartbeat_writes_ended_at_while_session_is_open(repo: Repository) -> None:
    provider = FakeWindowProvider()
    tracker = make_tracker(provider, repo)
    run(tracker, provider, make_window("Code"), 0, 5)
    assert spans(repo) == [("Code", 0, None, False)]  # todavía sin heartbeat
    run(tracker, provider, make_window("Code"), 5, 12)
    assert spans(repo) == [("Code", 0, 10, False)]  # heartbeat a los 10 s


def test_sleep_gap_closes_session_and_is_not_counted(repo: Repository) -> None:
    provider = FakeWindowProvider()
    tracker = make_tracker(provider, repo)
    run(tracker, provider, make_window("Code"), 0, 5)
    event = tracker.tick(at(3600))  # el computador durmió 1 hora
    tracker.close(at(3601))
    assert event is not None and event.seconds == 0
    assert spans(repo) == [("Code", 0, 4, False), ("Code", 3600, 3601, False)]


def test_no_active_window_closes_session(repo: Repository) -> None:
    provider = FakeWindowProvider()
    tracker = make_tracker(provider, repo)
    run(tracker, provider, make_window("Code"), 0, 5)
    provider.window = None
    assert tracker.tick(at(5)) is None
    assert tracker.current_session_id is None
    assert spans(repo) == [("Code", 0, 5, False)]


# --- Idle detection ------------------------------------------------------------


def test_idle_below_threshold_is_not_idle(repo: Repository) -> None:
    provider = FakeWindowProvider(make_window("Code"), idle_seconds=119)
    tracker = make_tracker(provider, repo)
    event = tracker.tick(at(0))
    assert event is not None and event.is_idle is False


def test_idle_session_is_backdated_to_last_input(repo: Repository) -> None:
    provider = FakeWindowProvider(make_window("Code"))
    tracker = make_tracker(provider, repo, idle_threshold_seconds=120)
    for second in range(0, 400):
        # Último input en t=50; el usuario vuelve en t=300.
        provider.idle_seconds = 0 if second < 50 or second >= 300 else second - 50
        event = tracker.tick(at(second))
        assert event is not None
        assert event.is_idle == (170 <= second < 300)
    tracker.close(at(400))
    # Recién en t=170 se cumplen 120 s sin input, pero la sesión idle parte en t=50.
    assert spans(repo) == [
        ("Code", 0, 50, False),
        ("Code", 50, 300, True),
        ("Code", 300, 400, False),
    ]


def test_idle_backdating_never_goes_before_session_start(repo: Repository) -> None:
    provider = FakeWindowProvider(make_window("Code"))
    tracker = make_tracker(provider, repo, idle_threshold_seconds=120)
    tracker.tick(at(0))
    # Una ventana cambia sola (sin input) y luego se detecta idle de 500 s.
    provider.window = make_window("Finder")
    tracker.tick(at(10))
    provider.idle_seconds = 500
    tracker.tick(at(11))
    tracker.close(at(20))
    assert spans(repo) == [
        ("Code", 0, 10, False),
        ("Finder", 10, 10, False),
        ("Finder", 10, 20, True),
    ]
