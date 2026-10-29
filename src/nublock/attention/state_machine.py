"""State machine con debounce (FR-34): un estado raw debe durar N segundos para contar."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from nublock.attention.states import AttentionState

# Estados que no son "percepción" sino hechos: se aplican sin esperar el debounce.
IMMEDIATE_STATES = frozenset({AttentionState.PAUSED, AttentionState.CAMERA_UNAVAILABLE})


@dataclass(frozen=True)
class AttentionTransition:
    """El estado *estable* cambió. Es el evento que se publica en el event bus."""

    previous: AttentionState | None
    state: AttentionState
    started_at: datetime  # cuándo empezó realmente (inicio del candidato, no fin del debounce)
    # Fracción (0–1) de frames del estado anterior que coincidían con él -> columna `confidence`.
    previous_confidence: float | None


class AttentionStateMachine:
    def __init__(self, debounce_seconds: float) -> None:
        self._debounce = timedelta(seconds=debounce_seconds)
        self.state: AttentionState | None = None
        self.state_since: datetime | None = None
        self._candidate: AttentionState | None = None
        self._candidate_since: datetime | None = None
        self._frames = 0
        self._matching_frames = 0

    def update(self, raw: AttentionState, now: datetime) -> AttentionTransition | None:
        """Procesa el estado raw de un frame. Retorna una transición si el estado cambió."""
        self._frames += 1
        if raw == self.state:
            self._matching_frames += 1
            self._candidate = None
            return None
        if self.state is None or raw in IMMEDIATE_STATES:
            return self._transition(raw, now)
        if raw != self._candidate:
            self._candidate, self._candidate_since = raw, now
        assert self._candidate_since is not None
        if now - self._candidate_since >= self._debounce:
            return self._transition(raw, self._candidate_since)
        return None

    def _transition(self, new_state: AttentionState, since: datetime) -> AttentionTransition:
        confidence = self._matching_frames / self._frames if self.state is not None else None
        transition = AttentionTransition(
            previous=self.state, state=new_state, started_at=since, previous_confidence=confidence
        )
        self.state, self.state_since = new_state, since
        self._candidate = self._candidate_since = None
        self._frames = self._matching_frames = 1
        return transition
