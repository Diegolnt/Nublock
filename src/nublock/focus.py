"""Focus sessions (FR-21 `focus_session`): sesión manual tipo Pomodoro + break."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from nublock.config import FocusSessionConfig, Mode
from nublock.events import ActivityEvent
from nublock.interventions.notifier import Notifier
from nublock.storage import Repository

logger = logging.getLogger(__name__)

DISTRACTING_COOLDOWN = timedelta(seconds=30)


@dataclass(frozen=True)
class FocusStatus:
    active: bool
    mode: Mode | None
    ends_at: datetime | None
    on_break_until: datetime | None


class FocusSessionManager:
    def __init__(
        self, config: FocusSessionConfig, repository: Repository, notifier: Notifier
    ) -> None:
        self._config = config
        self._repository = repository
        self._notifier = notifier
        self._session_id: int | None = None
        self._mode: Mode | None = None
        self._ends_at: datetime | None = None
        self._break_until: datetime | None = None
        self._in_distracting = False
        self._last_warning: datetime | None = None

    @property
    def active(self) -> bool:
        return self._session_id is not None

    @property
    def strict(self) -> bool:
        return self.active and self._mode == "strict"

    def status(self, now: datetime) -> FocusStatus:
        on_break = self._break_until if self._break_until and now < self._break_until else None
        return FocusStatus(self.active, self._mode, self._ends_at, on_break)

    def on_break(self, now: datetime) -> bool:
        return self._break_until is not None and now < self._break_until

    def remaining_minutes(self, now: datetime) -> float | None:
        if self._ends_at is None:
            return None
        return max(0.0, (self._ends_at - now).total_seconds() / 60)

    def start(self, now: datetime, minutes: int | None = None, mode: Mode | None = None) -> bool:
        """Inicia una sesión. Retorna False si ya había una activa."""
        if self.active:
            return False
        minutes = minutes or self._config.default_minutes
        self._mode = mode or self._config.mode
        self._session_id = self._repository.start_focus_session(now, minutes, self._mode)
        self._ends_at = now + timedelta(minutes=minutes)
        self._break_until = None
        self._in_distracting = False
        logger.info("Focus session iniciada: %d min, %s", minutes, self._mode)
        return True

    def stop(self, now: datetime) -> None:
        """Termina antes de tiempo (completed = 0)."""
        self._end(now, completed=False)

    def tick(self, now: datetime) -> None:
        if self._ends_at is not None and now >= self._ends_at:
            self._end(self._ends_at, completed=True)
            self._break_until = now + timedelta(minutes=self._config.break_minutes)
            self._notifier.notify(
                "Focus session",
                f"¡Focus session completada! Tómate {self._config.break_minutes} min de break.",
                sound="Glass",
            )

    def check_activity(self, event: ActivityEvent, now: datetime) -> str | None:
        """Con `block_distracting`, avisa al entrar a una app distractora durante la sesión.

        Retorna el mensaje a notificar (o None). Edge-triggered con cooldown de 30 s.
        """
        distracting = (
            self.active
            and self._config.block_distracting
            and not event.is_idle
            and event.classification.productivity == "distracting"
        )
        entered = distracting and not self._in_distracting
        self._in_distracting = distracting
        if not entered:
            return None
        if self._last_warning is not None and now - self._last_warning < DISTRACTING_COOLDOWN:
            return None
        self._last_warning = now
        return f"Estás en una focus session: {event.window.process_name} es distractor."

    def _end(self, at: datetime, completed: bool) -> None:
        if self._session_id is None:
            return
        self._repository.end_focus_session(self._session_id, at, completed)
        logger.info("Focus session terminada (completed=%s)", completed)
        self._session_id = self._mode = self._ends_at = None
