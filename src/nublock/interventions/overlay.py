"""Overlay de nivel 3 (FR-41): ventana semitransparente sobre la pantalla principal.

Corre en un *proceso aparte* (`python -m nublock.interventions.overlay_window`): así su
ventana tkinter tiene su propio main thread y no choca con el tray, que usa el nuestro.
"""

import logging
import subprocess
import sys
from typing import Protocol

logger = logging.getLogger(__name__)


class Overlay(Protocol):
    def show(self, message: str) -> None: ...

    def hide(self) -> None: ...

    @property
    def visible(self) -> bool: ...


class SubprocessOverlay:
    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def visible(self) -> bool:
        # poll() retorna None mientras el proceso sigue vivo.
        return self._process is not None and self._process.poll() is None

    def show(self, message: str) -> None:
        if self.visible:
            return
        try:
            self._process = subprocess.Popen(
                [sys.executable, "-m", "nublock.interventions.overlay_window", message]
            )
        except OSError as exc:
            logger.warning("No se pudo abrir el overlay: %s", exc)

    def hide(self) -> None:
        if self.visible:
            assert self._process is not None
            self._process.terminate()  # envía SIGTERM: tkinter cierra la ventana y sale
            self._process.wait(timeout=5)
        self._process = None


class NullOverlay:
    """Overlay que no hace nada (tests y modo sin UI)."""

    def __init__(self) -> None:
        self.shown: list[str] = []
        self._visible = False

    @property
    def visible(self) -> bool:
        return self._visible

    def show(self, message: str) -> None:
        self.shown.append(message)
        self._visible = True

    def hide(self) -> None:
        self._visible = False
