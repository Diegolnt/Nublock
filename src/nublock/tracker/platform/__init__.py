"""Elige el platform adapter según el OS."""

import sys
import threading

from nublock.tracker.platform.base import ActiveWindowProvider, AppBlocker, WindowInfo

__all__ = [
    "ActiveWindowProvider",
    "AppBlocker",
    "WindowInfo",
    "get_app_blocker",
    "get_window_provider",
    "run_main_loop",
]


def get_window_provider() -> ActiveWindowProvider:
    if sys.platform == "darwin":
        # Import tardío: pyobjc solo existe (y solo se instala) en macOS.
        from nublock.tracker.platform.macos import MacOSWindowProvider

        return MacOSWindowProvider()
    raise NotImplementedError(
        f"Nublock v1 aún no tiene platform adapter para {sys.platform!r} (solo macOS)."
    )


def get_app_blocker() -> AppBlocker:
    if sys.platform == "darwin":
        from nublock.tracker.platform.macos import MacOSAppBlocker

        return MacOSAppBlocker()
    raise NotImplementedError(f"Bloqueo de apps aún no disponible en {sys.platform!r}.")


def run_main_loop(stop: threading.Event) -> None:
    """Bloquea el main thread hasta `stop`, atendiendo los eventos que el OS necesite."""
    if sys.platform == "darwin":
        from nublock.tracker.platform.macos import run_main_loop as macos_main_loop

        macos_main_loop(stop)
    else:
        stop.wait()
