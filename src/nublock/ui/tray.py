"""System tray (FR-70/71) con pystray + Pillow. Corre en el main thread (requisito de macOS)."""

import logging
import signal
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from datetime import datetime

import pystray
from PIL import Image, ImageDraw

from nublock.events import BusEvent, FalseAlarm, PauseAll, SetCameraPaused, StartFocus, StopFocus
from nublock.live_state import LiveState, Snapshot
from nublock.report import format_duration
from nublock.timeutils import utc_now

logger = logging.getLogger(__name__)

GREEN, YELLOW, GRAY, RED = (52, 168, 83), (242, 183, 5), (140, 140, 140), (220, 50, 47)
DISTRACTED = {"LOOKING_AWAY", "LOOKING_DOWN", "PHONE"}


def icon_color(snapshot: Snapshot, now: datetime) -> tuple[int, int, int]:
    """Verde = focus, amarillo = distraído, gris = pausado / cámara apagada."""
    if snapshot.paused_until is not None and now < snapshot.paused_until:
        return GRAY
    state = snapshot.attention_state if snapshot.camera_open else None
    if state == "FOCUSED":
        return GREEN
    if state in DISTRACTED:
        return YELLOW
    if (
        state is None
        and snapshot.current_category
        and snapshot.current_category.startswith("distracting")
    ):
        return YELLOW  # sin cámara, el color sigue a la app activa
    if state is None and snapshot.current_category:
        return GREEN if snapshot.current_category.startswith("productive") else GRAY
    return GRAY


def make_icon(color: tuple[int, int, int], camera_on: bool, size: int = 64) -> Image.Image:
    """Círculo de color; con la cámara activa agrega un punto rojo (FR-71)."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))  # fondo transparente
    draw = ImageDraw.Draw(image)
    draw.ellipse((6, 6, size - 6, size - 6), fill=color)
    if camera_on:
        dot = size // 3
        draw.ellipse((size - dot - 1, 1, size - 1, dot + 1), fill=RED, outline=(255, 255, 255))
    return image


def status_lines(snapshot: Snapshot, now: datetime) -> list[str]:
    lines = []
    if snapshot.observe_only:
        lines.append("Modo observe-only")
    if snapshot.focus_active and snapshot.focus_ends_at:
        remaining = max(0.0, (snapshot.focus_ends_at - now).total_seconds())
        lines.append(f"Focus ({snapshot.focus_mode}): quedan {format_duration(remaining)}")
    elif snapshot.on_break_until:
        lines.append(f"Break: {format_duration((snapshot.on_break_until - now).total_seconds())}")
    camera = (
        "pausada" if snapshot.camera_paused else ("activa" if snapshot.camera_open else "apagada")
    )
    lines.append(
        f"Cámara: {camera}" + (f" · {snapshot.attention_state}" if snapshot.camera_open else "")
    )
    if snapshot.current_app:
        lines.append(f"App: {snapshot.current_app} ({snapshot.current_category})")
    totals = snapshot.today_seconds
    if totals:  # FR-20: timers en tiempo real
        lines.append(
            "Hoy: "
            + " · ".join(
                f"{name} {format_duration(totals.get(name, 0))}"
                for name in ("productive", "neutral", "distracting")
            )
        )
    if snapshot.blocked_sites:
        lines.append("Sitios bloqueados: " + ", ".join(snapshot.blocked_sites[:3]))
    if snapshot.paused_until is not None:
        lines.append(f"Todo pausado hasta {snapshot.paused_until.astimezone():%H:%M}")
    return lines


class Tray:
    def __init__(
        self,
        live: LiveState,
        publish: Callable[[BusEvent], None],
        dashboard_url: str | None,
        default_focus_minutes: int,
    ) -> None:
        self._live = live
        self._publish = publish
        self._dashboard_url = dashboard_url
        self._focus_minutes = default_focus_minutes
        self._icon = pystray.Icon(
            "nublock", make_icon(GRAY, camera_on=False), "Nublock", menu=self._build_menu()
        )

    def run(self, stop: threading.Event) -> None:
        """Bloquea el main thread hasta "Salir" o hasta que `stop` se active desde otro lado."""

        def setup(icon: pystray.Icon) -> None:
            # pystray llama `setup` en un thread aparte una vez que el ícono existe.
            icon.visible = True
            _take_over_signals(stop)
            last_key: tuple[object, ...] | None = None
            while not stop.wait(1.0):
                now = utc_now()
                snapshot = self._live.snapshot()
                color = icon_color(snapshot, now)
                key = (color, snapshot.camera_open)
                if key != last_key:
                    icon.icon = make_icon(color, snapshot.camera_open)
                    last_key = key
                icon.title = "Nublock — " + " | ".join(status_lines(snapshot, now)[:2])
                icon.update_menu()
            icon.stop()

        if sys.platform == "darwin":
            from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

            # Sin ícono en el Dock: Nublock vive en la barra de menú.
            NSApplication.sharedApplication().setActivationPolicy_(
                NSApplicationActivationPolicyAccessory
            )
        self._icon.run(setup=setup)
        stop.set()

    def _build_menu(self) -> pystray.Menu:
        # pystray acepta callables para text/visible: se evalúan cada vez que se abre el menú.
        def snapshot() -> Snapshot:
            return self._live.snapshot()

        def status(index: int) -> pystray.MenuItem:
            def text(_item: pystray.MenuItem) -> str:
                lines = status_lines(snapshot(), utc_now())
                return lines[index] if index < len(lines) else ""

            def visible(_item: pystray.MenuItem) -> bool:
                return index < len(status_lines(snapshot(), utc_now()))

            return pystray.MenuItem(text, None, enabled=False, visible=visible)

        def focus_label(mode: str) -> str:
            return f"Iniciar focus session ({self._focus_minutes} min, {mode})"

        return pystray.Menu(
            *(status(index) for index in range(7)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                focus_label("soft"),
                lambda: self._publish(StartFocus(mode="soft")),
                visible=lambda _item: not snapshot().focus_active,
            ),
            pystray.MenuItem(
                focus_label("strict"),
                lambda: self._publish(StartFocus(mode="strict")),
                visible=lambda _item: not snapshot().focus_active,
            ),
            pystray.MenuItem(
                "Terminar focus session",
                self._stop_focus,
                visible=lambda _item: snapshot().focus_active,
            ),
            pystray.MenuItem(
                lambda _item: "Reanudar cámara" if snapshot().camera_paused else "Pausar cámara",
                lambda: self._publish(SetCameraPaused(not snapshot().camera_paused)),
            ),
            pystray.MenuItem(
                lambda _item: "Reanudar todo" if snapshot().paused_until else "Pausar todo 15 min",
                self._toggle_pause,
            ),
            pystray.MenuItem("Última alerta fue falsa alarma", lambda: self._publish(FalseAlarm())),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Abrir dashboard", self._open_dashboard, enabled=self._dashboard_url is not None
            ),
            pystray.MenuItem("Permisos y configuración…", self._open_permissions),
            pystray.MenuItem("Salir", self._quit),
        )

    def _stop_focus(self) -> None:
        snapshot = self._live.snapshot()
        if snapshot.focus_mode == "strict" and self._dashboard_url:
            # Modo strict (FR-23): la confirmación (esperar + escribir la frase) es en el dashboard.
            webbrowser.open(f"{self._dashboard_url}/friction?action=stop_focus")
        else:
            self._publish(StopFocus())

    def _toggle_pause(self) -> None:
        snapshot = self._live.snapshot()
        if snapshot.paused_until:
            self._publish(PauseAll(0))
        elif snapshot.strict_active and self._dashboard_url:
            webbrowser.open(f"{self._dashboard_url}/friction?action=pause_all&target=15")
        else:
            self._publish(PauseAll(15))

    def _open_permissions(self) -> None:
        from nublock.cli import open_permissions_window
        from nublock.paths import default_app_path

        open_permissions_window(default_app_path())

    def _open_dashboard(self) -> None:
        if self._dashboard_url:
            webbrowser.open(self._dashboard_url)  # abre el navegador local; no es una request

    def _quit(self) -> None:
        self._icon.stop()


def _take_over_signals(stop: threading.Event) -> None:
    """Hace que Ctrl+C / SIGTERM cierren Nublock limpio mientras el tray tiene el main thread.

    En macOS pystray registra (con `PyObjCTools.MachSignals`) un handler de SIGINT que
    llama `NSApplication.terminate_`, que termina el proceso sin pasar por nuestro
    `finally`. MachSignals entrega la señal por el run loop de Cocoa (que sí está
    corriendo), así que reemplazamos ese handler por uno que solo activa `stop`.
    """
    if sys.platform != "darwin":
        return
    from PyObjCTools import MachSignals

    deadline = time.monotonic() + 2
    while MachSignals.getsignal(signal.SIGINT) is None and time.monotonic() < deadline:
        time.sleep(0.01)  # esperamos a que pystray instale el suyo, para reemplazarlo

    def handler(signum: int) -> None:
        logger.info("Señal %s recibida", signal.Signals(signum).name)
        stop.set()

    MachSignals.signal(signal.SIGINT, handler)
    MachSignals.signal(signal.SIGTERM, handler)
