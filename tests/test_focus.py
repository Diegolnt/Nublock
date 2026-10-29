from helpers import RecordingNotifier, at, make_window

from nublock.classifier import Classification
from nublock.config import FocusSessionConfig
from nublock.events import ActivityEvent
from nublock.focus import FocusSessionManager
from nublock.storage import Repository


def manager(repo: Repository, notifier: RecordingNotifier | None = None) -> FocusSessionManager:
    config = FocusSessionConfig(default_minutes=50, break_minutes=10)
    return FocusSessionManager(config, repo, notifier or RecordingNotifier())


def activity(productivity: str, second: float, is_idle: bool = False) -> ActivityEvent:
    return ActivityEvent(
        at=at(second),
        seconds=1,
        window=make_window("Instagram" if productivity == "distracting" else "Code"),
        classification=Classification(productivity, None),  # type: ignore[arg-type]
        is_idle=is_idle,
    )


def test_start_and_stop_early(repo: Repository) -> None:
    focus = manager(repo)
    assert focus.start(at(0), minutes=25, mode="strict")
    assert not focus.start(at(1))  # ya hay una activa
    assert focus.strict and focus.remaining_minutes(at(60)) == 24
    focus.stop(at(600))
    (row,) = repo.focus_sessions_between(at(-10), at(10))
    assert (row.planned_minutes, row.mode, row.completed, row.ended_at) == (
        25,
        "strict",
        False,
        at(600),
    )
    assert not focus.active


def test_completes_and_starts_break(repo: Repository) -> None:
    notifier = RecordingNotifier()
    focus = manager(repo, notifier)
    focus.start(at(0))  # default 50 min, soft
    focus.tick(at(50 * 60 - 1))
    assert focus.active
    focus.tick(at(50 * 60 + 1))
    assert not focus.active
    (row,) = repo.focus_sessions_between(at(-10), at(10))
    assert row.completed and row.ended_at == at(50 * 60)
    assert "completada" in notifier.messages[0][1]
    assert focus.on_break(at(55 * 60)) and not focus.on_break(at(61 * 60))


def test_warns_once_when_entering_distracting_app(repo: Repository) -> None:
    focus = manager(repo)
    assert focus.check_activity(activity("distracting", 0), at(0)) is None  # sin sesión
    focus.start(at(0))
    assert focus.check_activity(activity("productive", 1), at(1)) is None
    message = focus.check_activity(activity("distracting", 2), at(2))
    assert message is not None and "Instagram" in message
    assert focus.check_activity(activity("distracting", 3), at(3)) is None  # sigue ahí: no repite
    focus.check_activity(activity("productive", 4), at(4))
    assert focus.check_activity(activity("distracting", 5), at(5)) is None  # cooldown 30 s
    focus.check_activity(activity("productive", 40), at(40))
    assert focus.check_activity(activity("distracting", 41), at(41)) is not None
    focus.check_activity(activity("productive", 80), at(80))
    assert focus.check_activity(activity("distracting", 81, is_idle=True), at(81)) is None
