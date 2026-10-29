"""Arma los módulos y los corre en threads comunicados por un event bus (PRD sección 9).

main thread   : UI (tray de pystray) o, sin tray, el run loop de macOS
tracker       : ActivityTracker.tick() cada poll_interval -> ActivityEvent al bus
attention     : AttentionMonitor.run() (~8 FPS)        -> AttentionTransition al bus
core          : consume el bus -> rules, interventions, focus sessions, SQLite
dashboard     : servidor uvicorn en 127.0.0.1 (lee SQLite, publica comandos al bus)
"""

import logging
import signal
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from nublock.attention.monitor import AttentionMonitor
from nublock.blocking import Enforcer
from nublock.classifier import Classifier
from nublock.config import Config
from nublock.core import Core
from nublock.events import EventBus
from nublock.interventions.notifier import Notifier
from nublock.interventions.overlay import NullOverlay, Overlay
from nublock.live_state import LiveState
from nublock.site_blocking import SiteBlocker
from nublock.storage import Repository
from nublock.timeutils import utc_now
from nublock.tracker.platform import run_main_loop
from nublock.tracker.platform.base import ActiveWindowProvider
from nublock.tracker.tracker import ActivityTracker

logger = logging.getLogger(__name__)

CORE_TICK_SECONDS = 0.2


class BackgroundService(Protocol):
    """Algo con start()/stop() que corre en su propio thread (ej. el dashboard)."""

    def start(self) -> None: ...

    def stop(self) -> None: ...


class NublockApp:
    def __init__(
        self,
        config: Config,
        provider: ActiveWindowProvider,
        repository: Repository,
        notifier: Notifier,
        *,
        bus: EventBus | None = None,
        overlay: Overlay | None = None,
        monitor: AttentionMonitor | None = None,
        tracker_repository: Repository | None = None,
        clock: Callable[[], datetime] = utc_now,
        enforcer: Enforcer | None = None,
        site_blocker: SiteBlocker | None = None,
    ) -> None:
        general = config.general
        self.config = config
        self.bus = bus or EventBus()
        self.live = LiveState(observe_only=general.observe_only)
        self.stop_event = threading.Event()
        # El tracker escribe con su propia conexión SQLite (corre en otro thread).
        self.tracker = ActivityTracker(
            provider,
            Classifier(config.classification_rules),
            tracker_repository or repository,
            idle_threshold_seconds=general.idle_threshold_seconds,
            store_window_titles=general.store_window_titles,
            max_tick_gap_seconds=max(10.0, 5 * general.poll_interval_seconds),
        )
        self.monitor = monitor
        self.core = Core(
            config,
            repository,
            notifier,
            overlay or NullOverlay(),
            self.live,
            self.tracker,
            monitor,
            clock,
            enforcer,
            site_blocker,
        )
        self._clock = clock

    def startup(self) -> None:
        self.core.startup()

    def tick(self) -> None:
        """Una iteración síncrona de todo, sin threads. La usan los tests."""
        event = self.tracker.tick(self._clock())
        if event is not None:
            self.core.handle(event)
        self.drain_bus()
        self.core.tick()

    def drain_bus(self) -> None:
        while (event := self.bus.get(timeout=0)) is not None:
            self.core.handle(event)

    def run(
        self,
        duration_seconds: float | None = None,
        ui: Callable[[threading.Event], None] | None = None,
        services: list[BackgroundService] | None = None,
    ) -> None:
        """Corre hasta Ctrl+C, SIGTERM, "Salir" en el tray o `duration_seconds`.

        `ui` bloquea el main thread hasta que `stop_event` se active (ej. el tray).
        """
        stop = self.stop_event
        _stop_on_signals(stop)
        self.startup()
        threads = [
            threading.Thread(target=self._tracker_loop, name="tracker", daemon=True),
            threading.Thread(target=self._core_loop, name="core", daemon=True),
        ]
        if self.monitor is not None:
            threads.append(threading.Thread(target=self.monitor.run, name="attention", daemon=True))
        for thread in threads:
            thread.start()
        for service in services or []:
            service.start()
        if duration_seconds is not None:
            timer = threading.Timer(duration_seconds, stop.set)  # llama stop.set() en N s
            timer.daemon = True
            timer.start()
        logger.info("Nublock iniciado (observe_only=%s)", self.config.general.observe_only)
        try:
            if ui is not None:
                ui(stop)
            else:
                run_main_loop(stop)
        finally:
            stop.set()
            if self.monitor is not None:
                self.monitor.stop()
            for service in services or []:
                service.stop()
            for thread in threads:
                thread.join(timeout=5)
            self.tracker.close(self._clock())
            self.core.shutdown()
            logger.info("Nublock detenido")

    def _tracker_loop(self) -> None:
        interval = self.config.general.poll_interval_seconds
        while not self.stop_event.is_set():
            try:
                event = self.tracker.tick(self._clock())
                if event is not None:
                    self.bus.publish(event)
            except Exception:
                logger.exception("Error en el tracker")
            self.stop_event.wait(interval)  # como sleep(), pero despierta al instante con stop

    def _core_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                event = self.bus.get(timeout=CORE_TICK_SECONDS)
                if event is not None:
                    self.core.handle(event)
                self.core.tick()
            except Exception:
                logger.exception("Error en el core")


def _stop_on_signals(stop: threading.Event) -> None:
    """Ctrl+C (SIGINT) y SIGTERM activan `stop` en vez de matar el proceso.

    Python ejecuta estos handlers en el main thread cuando éste corre código Python: sin
    tray, `run_main_loop` lo hace cada 0,25 s. Con tray, el run loop de Cocoa no corre
    Python, y el tray reinstala los handlers con `PyObjCTools.MachSignals` (ver ui/tray.py).
    """
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda _signum, _frame: stop.set())
