"""Timers diarios (FR-20): segundos acumulados hoy por app/subcategoría/categoría."""

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime

from nublock.config import Productivity, RuleTarget
from nublock.events import ActivityEvent
from nublock.storage import ActivitySession
from nublock.timeutils import overlap_seconds

# (process_name, productivity, subcategory)
UsageKey = tuple[str, Productivity, str | None]


def matches_target(
    target: RuleTarget, process_name: str, productivity: Productivity, subcategory: str | None
) -> bool:
    """True si la actividad cumple todas las keys definidas en el target (AND)."""
    if target.process is not None and target.process.casefold() != process_name.casefold():
        return False
    if target.productivity is not None and target.productivity != productivity:
        return False
    if target.subcategory is not None and target.subcategory != subcategory:
        return False
    return True


class DailyTimers:
    """Acumula tiempo activo (no idle) del día local. Se reinicia al cambiar de día."""

    def __init__(self) -> None:
        self.day: date | None = None
        # defaultdict(float): una key nueva parte en 0.0 sin tener que inicializarla.
        self._seconds: defaultdict[UsageKey, float] = defaultdict(float)

    def add_event(self, day: date, event: ActivityEvent) -> None:
        if event.is_idle:
            return
        self._add(
            day,
            (
                event.window.process_name,
                event.classification.productivity,
                event.classification.subcategory,
            ),
            event.seconds,
        )

    def load_sessions(
        self,
        day: date,
        sessions: Iterable[ActivitySession],
        day_start: datetime,
        day_end: datetime,
    ) -> None:
        """Inicializa los timers con lo ya guardado hoy (ej. al reiniciar la app)."""
        for session in sessions:
            if session.is_idle:
                continue
            end = session.ended_at or session.started_at
            seconds = overlap_seconds(session.started_at, end, day_start, day_end)
            self._add(
                day, (session.process_name, session.productivity, session.subcategory), seconds
            )

    def totals_by_productivity(self) -> dict[str, float]:
        totals: defaultdict[str, float] = defaultdict(float)
        for (_, productivity, _), seconds in self._seconds.items():
            totals[productivity] += seconds
        return dict(totals)

    def seconds_for(self, target: RuleTarget) -> float:
        return sum(
            seconds
            for (process, productivity, subcategory), seconds in self._seconds.items()
            if matches_target(target, process, productivity, subcategory)
        )

    def _add(self, day: date, key: UsageKey, seconds: float) -> None:
        if day != self.day:
            self.day = day
            self._seconds.clear()
        self._seconds[key] += seconds
