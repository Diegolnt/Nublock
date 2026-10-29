"""Intervention Manager (FR-40..45): grace periods, escalation, cooldown, refocus y feedback.

Un *episode* de distracción empieza cuando el estado estable sale de FOCUSED hacia
LOOKING_AWAY / LOOKING_DOWN / PHONE y termina al volver a FOCUSED (o quedar ABSENT/PAUSED).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from nublock.attention.state_machine import AttentionTransition
from nublock.attention.states import DISTRACTED_STATES, AttentionState
from nublock.config import InterventionsConfig
from nublock.interventions.notifier import Notifier
from nublock.interventions.overlay import Overlay
from nublock.storage import Repository

logger = logging.getLogger(__name__)

MESSAGES: dict[AttentionState, str] = {
    AttentionState.LOOKING_AWAY: "Estás mirando hacia otro lado. Vuelve a lo tuyo.",
    AttentionState.LOOKING_DOWN: "Llevas un rato mirando hacia abajo.",
    AttentionState.PHONE: "Deja el teléfono: vuelve a tu sesión de foco.",
}
ALERT_TITLE = "Vuelve al foco"
FALSE_ALARM_STEP = 0.25  # cada falsa alarma (últimos 7 días) alarga ese grace un 25 %
FALSE_ALARM_MAX_MULTIPLIER = 2.0
FEEDBACK_WINDOW = timedelta(days=7)


@dataclass(frozen=True)
class InterventionContext:
    """Lo que el manager necesita saber del resto de la app en cada tick."""

    enabled: bool  # False: observe-only, pausado, break o app exenta
    strict_focus: bool  # el nivel 3 (overlay) solo existe en focus session strict
    focus_remaining_minutes: float | None


@dataclass
class _Episode:
    state: AttentionState
    state_since: datetime
    level: int = 0
    level1_at: datetime | None = None
    interventions: list[tuple[int, datetime]] = field(default_factory=list)  # (id, at)


class InterventionManager:
    def __init__(
        self,
        config: InterventionsConfig,
        notifier: Notifier,
        overlay: Overlay,
        repository: Repository,
    ) -> None:
        self._config = config
        self._notifier = notifier
        self._overlay = overlay
        self._repository = repository
        self._episode: _Episode | None = None
        self._last_level1_at: datetime | None = None
        self._multipliers: dict[AttentionState, float] = {}

    def grace_seconds(self, state: AttentionState) -> float:
        base = self._config.grace_seconds[state.value]  # type: ignore[index]
        return base * self._multipliers.get(state, 1.0)

    def refresh_feedback(self, now: datetime) -> None:
        """FR-43: recalibra los grace periods según las falsas alarmas recientes."""
        for state in DISTRACTED_STATES:
            count = self._repository.count_false_alarms(f"attention:{state}", now - FEEDBACK_WINDOW)
            self._multipliers[state] = min(FALSE_ALARM_MAX_MULTIPLIER, 1 + FALSE_ALARM_STEP * count)

    def on_transition(self, transition: AttentionTransition) -> None:
        state = transition.state
        if state in DISTRACTED_STATES:
            if self._episode is None:
                self._episode = _Episode(state=state, state_since=transition.started_at)
            else:  # ej. LOOKING_DOWN -> PHONE dentro del mismo episode
                self._episode.state = state
                self._episode.state_since = transition.started_at
            return
        episode, self._episode = self._episode, None
        self._overlay.hide()
        if episode is not None and state == AttentionState.FOCUSED:
            # FR-44: segundos entre cada intervention y el regreso a FOCUSED.
            for intervention_id, at in episode.interventions:
                seconds = max(0.0, (transition.started_at - at).total_seconds())
                self._repository.set_refocus_seconds(intervention_id, seconds)

    def tick(self, now: datetime, context: InterventionContext) -> None:
        episode = self._episode
        if episode is None:
            return
        if not context.enabled:
            self._overlay.hide()
            return
        escalation = self._config.escalation_seconds
        if episode.level == 0:
            alert_start = episode.state_since + timedelta(seconds=self.grace_seconds(episode.state))
            if now < alert_start + timedelta(seconds=escalation[0]):
                return
            cooldown = timedelta(seconds=self._config.cooldown_seconds)
            if self._last_level1_at is not None and now - self._last_level1_at < cooldown:
                return  # FR-45: máximo un aviso nuevo cada cooldown_seconds
            self._fire(1, now, context)
            return
        max_level = 3 if context.strict_focus else 2
        next_level = episode.level + 1
        if next_level > max_level:
            return
        assert episode.level1_at is not None
        due = episode.level1_at + timedelta(seconds=escalation[next_level - 1] - escalation[0])
        if now >= due:
            self._fire(next_level, now, context)

    def _fire(self, level: int, now: datetime, context: InterventionContext) -> None:
        episode = self._episode
        assert episode is not None
        message = MESSAGES[episode.state]
        if level == 1:
            self._notifier.notify(ALERT_TITLE, message, false_alarm_button=True)  # silenciosa
            episode.level1_at = self._last_level1_at = now
        elif level == 2:
            sound = self._config.sound_name if self._config.sound else None
            self._notifier.notify(ALERT_TITLE, message, sound=sound, false_alarm_button=True)
        else:
            remaining = context.focus_remaining_minutes or 0
            self._overlay.show(f"Vuelve: te quedan {remaining:.0f} min de sesión")
        intervention_id = self._repository.record_intervention(
            now, trigger=f"attention:{episode.state}", level=level, rule_id=None
        )
        episode.interventions.append((intervention_id, now))
        episode.level = level
        logger.info("Intervention nivel %d por %s", level, episode.state)
