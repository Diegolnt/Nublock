"""Intervention Manager: grace periods, escalation, cooldown, refocus y falsas alarmas."""

from datetime import datetime

from helpers import DOWN_FACE, FOCUSED_FACE, FakeClock, RecordingNotifier, at

from nublock.attention.fake import FakeCamera, FakeFaceAnalyzer, FakePhoneDetector
from nublock.attention.monitor import AttentionMonitor, AttentionPipeline
from nublock.attention.state_machine import AttentionTransition
from nublock.attention.states import AttentionState as S
from nublock.attention.zone import DEFAULT_ZONE
from nublock.config import AttentionConfig, InterventionsConfig
from nublock.interventions.manager import InterventionContext, InterventionManager
from nublock.interventions.overlay import NullOverlay
from nublock.storage import Repository

SOFT = InterventionContext(enabled=True, strict_focus=False, focus_remaining_minutes=30)
STRICT = InterventionContext(enabled=True, strict_focus=True, focus_remaining_minutes=12)
DISABLED = InterventionContext(enabled=False, strict_focus=False, focus_remaining_minutes=None)


class Rig:
    def __init__(self, repo: Repository) -> None:
        self.notifier = RecordingNotifier()
        self.overlay = NullOverlay()
        self.repo = repo
        self.manager = InterventionManager(InterventionsConfig(), self.notifier, self.overlay, repo)

    def transition(self, state: S, second: float, previous: S | None = None) -> None:
        self.manager.on_transition(AttentionTransition(previous, state, at(second), None))

    def run(self, start: float, end: float, context: InterventionContext = SOFT) -> None:
        second = start
        while second <= end:
            self.manager.tick(at(second), context)
            second += 0.5

    def fired_at(self) -> list[tuple[int, datetime]]:
        rows = self.repo.interventions_between(at(-3600), at(3600))
        return [(row.level, row.at) for row in rows]


def test_looking_away_waits_grace_then_escalates(repo: Repository) -> None:
    rig = Rig(repo)
    rig.transition(S.LOOKING_AWAY, 0)
    rig.run(0, 9.5)
    assert rig.notifier.messages == []  # grace de 10 s
    rig.run(10, 40)
    assert rig.fired_at() == [(1, at(10)), (2, at(20))]  # sin nivel 3 fuera de strict
    assert rig.notifier.sounds == [None, "Glass"]  # nivel 1 silencioso, nivel 2 con sonido
    assert rig.notifier.false_alarm_buttons == [True, True]  # botón "Falsa alarma" (FR-43)
    assert rig.overlay.shown == []


def test_strict_focus_session_escalates_to_overlay(repo: Repository) -> None:
    rig = Rig(repo)
    rig.transition(S.LOOKING_DOWN, 0)
    rig.run(0, 60, STRICT)
    assert rig.fired_at() == [(1, at(15)), (2, at(25)), (3, at(35))]
    assert rig.overlay.shown == ["Vuelve: te quedan 12 min de sesión"]
    rig.transition(S.FOCUSED, 61)
    assert not rig.overlay.visible  # al volver a FOCUSED se cierra


def test_phone_has_short_grace(repo: Repository) -> None:
    rig = Rig(repo)
    rig.transition(S.PHONE, 0)
    rig.run(0, 5)
    assert rig.fired_at() == [(1, at(3))]
    assert repo.interventions_between(at(0), at(10))[0].trigger == "attention:PHONE"


def test_absent_never_alerts(repo: Repository) -> None:
    rig = Rig(repo)
    rig.transition(S.ABSENT, 0)
    rig.run(0, 120)
    assert rig.fired_at() == []


def test_refocus_seconds_measured_until_back_to_focused(repo: Repository) -> None:
    rig = Rig(repo)
    rig.transition(S.LOOKING_AWAY, 0)
    rig.run(0, 22)  # nivel 1 en 10 s, nivel 2 en 20 s
    rig.transition(S.FOCUSED, 24, previous=S.LOOKING_AWAY)
    rows = repo.interventions_between(at(0), at(60))
    assert [row.refocus_seconds for row in rows] == [14, 4]


def test_cooldown_between_episodes(repo: Repository) -> None:
    rig = Rig(repo)
    rig.transition(S.PHONE, 0)
    rig.run(0, 4)  # alerta en t=3
    rig.transition(S.FOCUSED, 5)
    rig.transition(S.PHONE, 6)
    rig.run(4.5, 40)
    # La 2ª alerta llega cuando termina el cooldown (3 + 30), no en t=9.
    assert [(level, when) for level, when in rig.fired_at() if level == 1] == [
        (1, at(3)),
        (1, at(33)),
    ]


def test_switching_distracted_state_keeps_the_episode(repo: Repository) -> None:
    rig = Rig(repo)
    rig.transition(S.LOOKING_DOWN, 0)
    rig.run(0, 2)
    rig.transition(S.PHONE, 2)  # mirando abajo -> se detecta el teléfono
    rig.run(2.5, 6)
    assert rig.fired_at() == [(1, at(5))]  # grace de PHONE (3 s) desde que empezó PHONE


def test_disabled_context_never_alerts(repo: Repository) -> None:
    rig = Rig(repo)
    rig.transition(S.PHONE, 0)
    rig.run(0, 60, DISABLED)
    assert rig.fired_at() == []


def test_false_alarms_lengthen_grace(repo: Repository) -> None:
    rig = Rig(repo)
    assert rig.manager.grace_seconds(S.LOOKING_AWAY) == 10
    for second in (0, 100):
        repo.record_intervention(at(second), "attention:LOOKING_AWAY", 1, None)
        repo.mark_latest_false_alarm(at(second - 1))
    rig.manager.refresh_feedback(at(200))
    assert rig.manager.grace_seconds(S.LOOKING_AWAY) == 15  # +25 % por cada una
    assert rig.manager.grace_seconds(S.PHONE) == 3  # otros estados no cambian


def test_phone_in_focus_session_alerts_in_under_5_seconds(repo: Repository) -> None:
    """DoD de M4: tomar el teléfono durante una focus session -> alerta en < 5 s."""
    clock = FakeClock(at(0))
    config = AttentionConfig()  # debounce 2 s, phone detection a 1 FPS
    analyzer = FakeFaceAnalyzer(FOCUSED_FACE)
    phone = FakePhoneDetector(score=0.0)
    rig = Rig(repo)
    monitor = AttentionMonitor(
        config,
        FakeCamera(),
        lambda: AttentionPipeline(config, DEFAULT_ZONE, analyzer, phone),
        rig.manager.on_transition,
        clock=clock,
    )
    monitor.set_active(True)

    def run(seconds: float) -> None:
        for _ in range(round(seconds * 8)):  # 8 FPS
            monitor.step()
            rig.manager.tick(clock(), SOFT)
            clock.advance(0.125)

    run(5)
    picked_up_at = clock()
    analyzer.observation, phone.score = DOWN_FACE, 0.9  # mira hacia abajo, teléfono en la mano
    run(10)
    first_alert = rig.fired_at()[0]
    assert first_alert[0] == 1
    assert (first_alert[1] - picked_up_at).total_seconds() < 5
