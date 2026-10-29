"""Core con fakes: comandos de UI, persistencia de atención, overrides y contexto."""

from dataclasses import dataclass
from datetime import timedelta

from helpers import NOON, FakeClock, RecordingNotifier, at, make_window

from nublock.app import NublockApp
from nublock.attention.fake import FakeCamera, FakeFaceAnalyzer
from nublock.attention.monitor import AttentionMonitor, AttentionPipeline
from nublock.attention.state_machine import AttentionTransition
from nublock.attention.states import AttentionState as S
from nublock.attention.zone import DEFAULT_ZONE
from nublock.config import Config
from nublock.events import (
    FalseAlarm,
    PauseAll,
    ReloadClassifier,
    SetCameraPaused,
    StartFocus,
    StopFocus,
)
from nublock.storage import Repository
from nublock.tracker.platform.fake import FakeWindowProvider


@dataclass
class Rig:
    app: NublockApp
    clock: FakeClock
    notifier: RecordingNotifier
    provider: FakeWindowProvider

    def tick(self, seconds: float = 0) -> None:
        self.clock.advance(seconds)
        self.app.tick()

    def camera_active(self) -> bool:
        return self.app.core.camera_should_run(self.clock())

    def alerts_enabled(self) -> bool:
        return self.app.core.intervention_context(self.clock()).enabled


def make_rig(repo: Repository, observe_only: bool = True, **attention: object) -> Rig:
    config = Config.model_validate(
        {
            "general": {"observe_only": observe_only},
            "classification_rules": [
                {
                    "match": {"process": "Instagram"},
                    "productivity": "distracting",
                    "subcategory": "social",
                }
            ],
            "attention": {"attention_exempt": [{"process": "zoom.us"}], **attention},
        }
    )
    clock = FakeClock(NOON)
    notifier = RecordingNotifier()
    monitor = AttentionMonitor(
        config.attention,
        FakeCamera(),
        lambda: AttentionPipeline(config.attention, DEFAULT_ZONE, FakeFaceAnalyzer(), None),
        lambda transition: None,
        clock=clock,
    )
    provider = FakeWindowProvider(make_window("Code"))
    app = NublockApp(config, provider, repo, notifier, monitor=monitor, clock=clock)
    app.startup()
    return Rig(app, clock, notifier, provider)


def test_camera_only_runs_during_focus_session(repo: Repository) -> None:
    rig = make_rig(repo)
    rig.tick()
    assert not rig.camera_active()
    rig.app.bus.publish(StartFocus(minutes=25))
    rig.tick()
    assert rig.camera_active() and rig.app.live.snapshot().focus_active
    rig.app.bus.publish(StopFocus())
    rig.tick()
    assert not rig.camera_active()


def test_camera_can_run_always_when_configured(repo: Repository) -> None:
    rig = make_rig(repo, only_during_focus=False)
    rig.tick()
    assert rig.camera_active()


def test_pause_camera_and_pause_all(repo: Repository) -> None:
    rig = make_rig(repo, only_during_focus=False)
    rig.app.bus.publish(SetCameraPaused(True))
    rig.tick()
    assert not rig.camera_active() and rig.app.live.snapshot().camera_paused
    rig.app.bus.publish(SetCameraPaused(False))
    rig.app.bus.publish(PauseAll(15))
    rig.tick()
    assert not rig.camera_active() and rig.app.live.snapshot().paused_until is not None
    rig.tick(16 * 60)
    assert rig.camera_active()


def test_exempt_app_releases_camera_and_disables_alerts(repo: Repository) -> None:
    rig = make_rig(repo, observe_only=False, only_during_focus=False)
    rig.tick()
    assert rig.camera_active() and rig.alerts_enabled()
    rig.provider.window = make_window("zoom.us")  # videollamada
    rig.tick(1)
    assert not rig.camera_active() and not rig.alerts_enabled()


def test_observe_only_allows_alerts_only_inside_focus_session(repo: Repository) -> None:
    rig = make_rig(repo, observe_only=True)
    assert not rig.alerts_enabled()
    rig.app.bus.publish(StartFocus())
    rig.tick()
    assert rig.alerts_enabled()


def test_attention_transitions_are_persisted_with_confidence(repo: Repository) -> None:
    rig = make_rig(repo)
    rig.app.bus.publish(AttentionTransition(None, S.FOCUSED, at(0), None))
    rig.app.bus.publish(AttentionTransition(S.FOCUSED, S.PHONE, at(30), 0.9))
    rig.tick()
    rows = repo.attention_events_between(at(-10), at(60))
    assert [(r.state, r.started_at, r.ended_at, r.confidence) for r in rows] == [
        ("FOCUSED", at(0), at(30), 0.9),
        ("PHONE", at(30), None, None),
    ]
    rig.app.core.shutdown()
    assert repo.attention_events_between(at(-10), at(60))[-1].ended_at is not None


def test_false_alarm_command_marks_latest_intervention(repo: Repository) -> None:
    rig = make_rig(repo)
    repo.record_intervention(NOON - timedelta(seconds=30), "attention:PHONE", 1, None)
    rig.app.bus.publish(FalseAlarm())
    rig.tick()
    (row,) = repo.interventions_between(NOON - timedelta(minutes=1), NOON + timedelta(minutes=1))
    assert row.user_feedback == "false_alarm"


def test_override_from_dashboard_applies_to_new_sessions(repo: Repository) -> None:
    """FR-13 AC: tras clasificar una app, sus nuevas sesiones usan la nueva categoría."""
    rig = make_rig(repo)
    rig.tick()
    repo.add_override("process", "code", "productive", "dev", NOON)
    rig.app.bus.publish(ReloadClassifier())
    rig.tick(1)
    rig.tick(1)
    rig.app.tracker.close(rig.clock())
    sessions = repo.sessions_between(NOON - timedelta(hours=1), NOON + timedelta(hours=1))
    assert [(s.productivity, s.subcategory) for s in sessions] == [
        ("neutral", "uncategorized"),
        ("productive", "dev"),
    ]


def test_distracting_app_during_focus_session_notifies(repo: Repository) -> None:
    rig = make_rig(repo, observe_only=True)
    rig.app.bus.publish(StartFocus())
    rig.tick()
    rig.provider.window = make_window("Instagram")
    rig.tick(1)
    assert any("focus session" in message for _, message in rig.notifier.messages)
    assert repo.count_interventions() == 1


def test_live_state_tracks_current_app_and_timers(repo: Repository) -> None:
    rig = make_rig(repo)
    rig.tick()
    for _ in range(4):
        rig.tick(1)
    snapshot = rig.app.live.snapshot()
    assert snapshot.current_app == "Code"
    assert snapshot.current_category == "neutral/uncategorized"
    assert snapshot.today_seconds == {"neutral": 4.0}
