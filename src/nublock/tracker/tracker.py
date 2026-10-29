"""Activity Tracker: convierte "fotos" de la ventana activa en activity_sessions (FR-01..05).

En cada `tick(now)`:
1. Pregunta al provider qué ventana está activa y cuántos segundos lleva sin input.
2. La clasifica.
3. Si lo que se guardaría en la DB es igual al tick anterior, extiende la sesión;
   si cambió, cierra la sesión actual y abre otra (una fila por periodo continuo).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from nublock.classifier import Classification, Classifier
from nublock.events import ActivityEvent
from nublock.storage import Repository
from nublock.tracker.platform.base import ActiveWindowProvider, WindowInfo

logger = logging.getLogger(__name__)

# (process_name, app_name, window_title guardado, productivity, subcategory, is_idle)
SessionKey = tuple[str, str | None, str | None, str, str | None, bool]


@dataclass
class _OpenSession:
    id: int
    key: SessionKey
    started_at: datetime
    is_idle: bool
    last_heartbeat: datetime


class ActivityTracker:
    def __init__(
        self,
        provider: ActiveWindowProvider,
        classifier: Classifier,
        repository: Repository,
        *,
        idle_threshold_seconds: float,
        store_window_titles: bool,
        max_tick_gap_seconds: float = 10.0,
        heartbeat_seconds: float = 10.0,
    ) -> None:
        # Dependency injection: en tests se pasa un FakeWindowProvider y una DB en RAM.
        self._provider = provider
        # Público: el core lo reemplaza al agregar overrides desde el dashboard (FR-13).
        self.classifier = classifier
        self._repository = repository
        self._idle_threshold = idle_threshold_seconds
        self._store_titles = store_window_titles
        self._max_gap = timedelta(seconds=max_tick_gap_seconds)
        self._heartbeat = timedelta(seconds=heartbeat_seconds)
        self._session: _OpenSession | None = None
        self._last_tick: datetime | None = None

    @property
    def current_session_id(self) -> int | None:
        return self._session.id if self._session else None

    def tick(self, now: datetime) -> ActivityEvent | None:
        """Procesa un poll. `now` debe tener timezone (UTC). Retorna None si no hay ventana."""
        elapsed = self._elapsed_since_last_tick(now)
        self._last_tick = now

        window = self._provider.get_active_window()
        if window is None:
            self.close(now)
            return None

        idle_seconds = self._provider.get_idle_seconds()
        is_idle = idle_seconds >= self._idle_threshold
        classification = self.classifier.classify(window)
        stored_title = window.window_title if self._store_titles else None
        key: SessionKey = (
            window.process_name,
            window.app_name,
            stored_title,
            classification.productivity,
            classification.subcategory,
            is_idle,
        )

        session = self._session
        if session is not None and session.key == key:
            if now - session.last_heartbeat >= self._heartbeat:
                self._repository.set_session_end(session.id, now)
                session.last_heartbeat = now
        else:
            boundary = now
            if is_idle and session is not None and not session.is_idle:
                # El usuario dejó de tocar el teclado/mouse hace `idle_seconds`:
                # ese tiempo ya era idle, así que la sesión idle empieza ahí.
                boundary = max(session.started_at, now - timedelta(seconds=idle_seconds))
            self.close(boundary)
            self._open(boundary, window, stored_title, classification, is_idle, key)

        return ActivityEvent(
            at=now,
            seconds=elapsed,
            window=window,
            classification=classification,
            is_idle=is_idle,
        )

    def close(self, at: datetime) -> None:
        """Cierra la sesión abierta (si hay). Se llama al cambiar de ventana y al salir."""
        if self._session is not None:
            self._repository.set_session_end(self._session.id, at)
            self._session = None

    def _elapsed_since_last_tick(self, now: datetime) -> float:
        if self._last_tick is None:
            return 0.0
        elapsed = now - self._last_tick
        if elapsed < timedelta(0) or elapsed > self._max_gap:
            # El computador durmió, el proceso se congeló o el reloj saltó:
            # cerramos la sesión donde la vimos por última vez y no contamos el gap.
            logger.info("Gap de %.0f s entre ticks; se cierra la sesión", elapsed.total_seconds())
            self.close(self._last_tick)
            return 0.0
        return elapsed.total_seconds()

    def _open(
        self,
        at: datetime,
        window: WindowInfo,
        stored_title: str | None,
        classification: Classification,
        is_idle: bool,
        key: SessionKey,
    ) -> None:
        session_id = self._repository.open_session(
            started_at=at,
            process_name=window.process_name,
            app_name=window.app_name,
            window_title=stored_title,
            classification=classification,
            is_idle=is_idle,
        )
        self._session = _OpenSession(
            id=session_id, key=key, started_at=at, is_idle=is_idle, last_heartbeat=at
        )
        # Nunca se loguea el título de ventana (NFR-09).
        logger.debug(
            "Nueva sesión %d: %s (%s/%s)%s",
            session_id,
            window.process_name,
            classification.productivity,
            classification.subcategory,
            " [idle]" if is_idle else "",
        )
