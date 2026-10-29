"""Platform adapter de macOS usando pyobjc (AppKit + Quartz).

Importante: NSWorkspace actualiza `frontmostApplication` procesando notificaciones en el
run loop del *main thread*. El provider se puede usar desde cualquier thread, siempre que
el main thread esté haciendo girar su run loop: lo hace el tray (pystray) o, sin tray,
`run_main_loop()`. Si nadie lo hace girar, el valor queda congelado (docs/DECISIONS.md).
"""

import logging
import threading

import psutil
import Quartz
from AppKit import NSRunningApplication, NSWorkspace
from Foundation import NSDate, NSRunLoop

from nublock.tracker.platform.base import WindowInfo

logger = logging.getLogger(__name__)

_WINDOW_LIST_OPTIONS = (
    Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
)


class MacOSWindowProvider:
    def __init__(self) -> None:
        self._workspace = NSWorkspace.sharedWorkspace()
        # Sin permiso Screen Recording, macOS no entrega los títulos de ventana.
        # CGPreflightScreenCaptureAccess() solo consulta; no muestra el diálogo de permiso.
        self.can_read_titles: bool = bool(Quartz.CGPreflightScreenCaptureAccess())
        if not self.can_read_titles:
            logger.warning(
                "Sin permiso Screen Recording: no se leerán títulos de ventana y las reglas "
                "title_regex no coincidirán. Actívalo en System Settings > Privacy & Security "
                "> Screen Recording para tu terminal."
            )

    def get_active_window(self) -> WindowInfo | None:
        app = self._workspace.frontmostApplication()
        if app is None:
            return None
        pid = int(app.processIdentifier())
        app_name = app.localizedName()
        app_name = str(app_name) if app_name else None
        process_name = _process_name(pid) or app_name or "unknown"
        title = self._window_title(pid) if self.can_read_titles else None
        return WindowInfo(process_name=process_name, pid=pid, app_name=app_name, window_title=title)

    def get_idle_seconds(self) -> float:
        return float(
            Quartz.CGEventSourceSecondsSinceLastEventType(
                Quartz.kCGEventSourceStateCombinedSessionState, Quartz.kCGAnyInputEventType
            )
        )

    @staticmethod
    def _window_title(pid: int) -> str | None:
        windows = Quartz.CGWindowListCopyWindowInfo(_WINDOW_LIST_OPTIONS, Quartz.kCGNullWindowID)
        # La lista viene ordenada de adelante hacia atrás: la primera ventana normal
        # (layer 0) del proceso activo es la que el usuario está mirando.
        for window in windows or []:
            if (
                window.get(Quartz.kCGWindowOwnerPID) == pid
                and window.get(Quartz.kCGWindowLayer) == 0
            ):
                title = window.get(Quartz.kCGWindowName)
                return str(title) if title else None
        return None


class MacOSAppBlocker:
    """Oculta (Cmd+H) o cierra (Cmd+Q) apps con NSRunningApplication. No requiere permisos."""

    def hide(self, pid: int) -> bool:
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is None:
            return False
        # Medido en macOS 26: hide() puede retornar NO aunque la app sí se oculta (con la app
        # en primer plano). Por eso no usamos su valor de retorno.
        app.hide()
        return True

    def terminate(self, pid: int) -> bool:
        # terminate() pide a la app que se cierre (puede preguntar si guardar cambios).
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        return bool(app is not None and app.terminate())


def _process_name(pid: int) -> str | None:
    try:
        return psutil.Process(pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def run_main_loop(stop: threading.Event) -> None:
    """Hace girar el run loop del main thread hasta que `stop` se active (modo sin tray)."""
    run_loop = NSRunLoop.currentRunLoop()
    while not stop.is_set():
        run_loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.25))
