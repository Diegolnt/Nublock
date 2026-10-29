"""Eventos entre módulos y el event bus (`queue.Queue`) que los transporta entre threads.

Productores: tracker thread (ActivityEvent), attention thread (AttentionTransition),
tray y dashboard (comandos). Consumidor: el core thread (`nublock.core.Core`).
"""

import queue
from dataclasses import dataclass
from datetime import datetime

from nublock.attention.state_machine import AttentionTransition
from nublock.classifier import Classification
from nublock.config import Action, Mode
from nublock.tracker.platform.base import WindowInfo


@dataclass(frozen=True)
class ActivityEvent:
    """Lo que el tracker observó en un tick."""

    at: datetime  # UTC
    seconds: float  # segundos transcurridos desde el tick anterior (0 si hubo un gap)
    window: WindowInfo
    classification: Classification
    is_idle: bool


@dataclass(frozen=True)
class RuleViolation:
    """Una regla del usuario empezó a no cumplirse."""

    at: datetime  # UTC
    rule_id: str
    action: Action  # acción configurada; `warn`/`block` se ejecutan como `notify` hasta M6
    mode: Mode
    message: str


# --- Comandos (desde el tray o el dashboard) ---------------------------------------


@dataclass(frozen=True)
class StartFocus:
    minutes: int | None = None  # None = focus_session.default_minutes
    mode: Mode | None = None


@dataclass(frozen=True)
class StopFocus:
    confirmed: bool = False  # True = pasó la fricción del modo strict (FR-23)


@dataclass(frozen=True)
class SetCameraPaused:
    paused: bool


@dataclass(frozen=True)
class PauseAll:
    minutes: float  # 0 = reanudar
    confirmed: bool = False


@dataclass(frozen=True)
class DisableRule:
    """Desactiva una regla por el resto del día (M6)."""

    rule_id: str
    confirmed: bool = False


@dataclass(frozen=True)
class FalseAlarm:
    pass


@dataclass(frozen=True)
class ReloadClassifier:
    pass


Command = (
    StartFocus
    | StopFocus
    | SetCameraPaused
    | PauseAll
    | DisableRule
    | FalseAlarm
    | ReloadClassifier
)
BusEvent = ActivityEvent | AttentionTransition | Command


class EventBus:
    """Canal thread-safe: varios threads publican, uno consume."""

    def __init__(self) -> None:
        self._queue: queue.Queue[BusEvent] = queue.Queue()

    def publish(self, event: BusEvent) -> None:
        self._queue.put(event)

    def get(self, timeout: float | None = None) -> BusEvent | None:
        """Siguiente evento; None si no llegó ninguno en `timeout` segundos."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
