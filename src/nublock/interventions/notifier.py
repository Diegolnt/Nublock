"""Notificaciones nativas del OS."""

import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Protocol

from nublock.interventions.app_bundle import executable_path

logger = logging.getLogger(__name__)

# Fallback: AppleScript que recibe título, mensaje y sonido como argumentos (argv), así el
# texto nunca se interpreta como código aunque contenga comillas.
_APPLESCRIPT = """on run argv
if (item 3 of argv) is "" then
    display notification (item 2 of argv) with title (item 1 of argv)
else
    display notification (item 2 of argv) with title (item 1 of argv) sound name (item 3 of argv)
end if
end run"""


class Notifier(Protocol):
    def notify(
        self,
        title: str,
        message: str,
        sound: str | None = None,
        false_alarm_button: bool = False,
    ) -> None:
        """`sound`: sonido del sistema (ej. "Glass") o None = silenciosa.

        `false_alarm_button`: agrega el botón "Falsa alarma" (FR-43), si el OS lo permite.
        """
        ...


class MacOSNotifier:
    """Notificaciones de macOS a nombre de "Nublock" (con su ícono) usando `Nublock.app`.

    Si la app todavía no se construyó (`nublock setup-notifications`), usa `osascript`, cuyas
    notificaciones macOS atribuye a "Script Editor" (y descarta si no tiene permiso).
    """

    def __init__(self, app_path: Path | None = None, dashboard_url: str | None = None) -> None:
        self._executable = executable_path(app_path) if app_path else None
        self._dashboard_url = dashboard_url
        self._warned = False

    def notify(
        self,
        title: str,
        message: str,
        sound: str | None = None,
        false_alarm_button: bool = False,
    ) -> None:
        command = self.command(title, message, sound, false_alarm_button)
        # En un thread aparte: el core no espera a que macOS muestre la notificación.
        threading.Thread(target=_run, args=(command,), name="notify", daemon=True).start()

    def command(
        self,
        title: str,
        message: str,
        sound: str | None = None,
        false_alarm_button: bool = False,
    ) -> list[str]:
        """Comando que muestra la notificación: Nublock.app si existe, si no osascript."""
        if self._executable is None or not self._executable.exists():
            if not self._warned:
                logger.warning(
                    "Nublock.app no existe: usando osascript. Para notificaciones con el ícono "
                    "de Nublock corre: python -m nublock setup-notifications"
                )
                self._warned = True
            return ["osascript", "-e", _APPLESCRIPT, title, message, sound or ""]
        command = [str(self._executable), "--notify", "--title", title, "--message", message]
        if sound:
            command += ["--sound", sound]
        if self._dashboard_url:
            command += ["--dashboard", self._dashboard_url]
        if false_alarm_button:
            command.append("--false-alarm")
        return command


class LogNotifier:
    """Fallback para OS sin notificador: solo escribe en el log."""

    def notify(
        self,
        title: str,
        message: str,
        sound: str | None = None,
        false_alarm_button: bool = False,
    ) -> None:
        logger.warning("[notificación] %s: %s", title, message)


def get_notifier(app_path: Path | None = None, dashboard_url: str | None = None) -> Notifier:
    if sys.platform == "darwin":
        return MacOSNotifier(app_path, dashboard_url)
    # Windows (toast abajo a la derecha) y Linux: pendiente junto con sus platform adapters.
    return LogNotifier()


def _run(command: list[str]) -> None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("No se pudo mostrar la notificación: %s", exc)
        return
    if result.returncode != 0:
        logger.warning(
            "La notificación falló (%d): %s", result.returncode, result.stderr.strip() or "-"
        )
