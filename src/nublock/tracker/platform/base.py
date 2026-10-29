"""Interfaz común de los platform adapters (NFR-07).

El resto de Nublock solo conoce `ActiveWindowProvider`; no sabe en qué OS corre.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class WindowInfo:
    """Foto de la ventana activa en un instante."""

    process_name: str  # nombre del ejecutable, ej. "Google Chrome"
    pid: int  # Process Identifier
    app_name: str | None  # nombre visible de la app (puede diferir del ejecutable)
    window_title: str | None  # None si el OS no lo entrega (ej. falta permiso)


class ActiveWindowProvider(Protocol):
    """Cualquier clase con estos dos métodos sirve como provider (structural typing)."""

    def get_active_window(self) -> WindowInfo | None:
        """Ventana en primer plano, o None si no hay ninguna."""
        ...

    def get_idle_seconds(self) -> float:
        """Segundos desde el último input de teclado/mouse."""
        ...


class AppBlocker(Protocol):
    """Acciones de bloqueo sobre una app (FR-50). Retornan True si el OS las aceptó."""

    def hide(self, pid: int) -> bool:
        """Ocultar la app (modo soft): sigue abierta, pero sale de la pantalla."""
        ...

    def terminate(self, pid: int) -> bool:
        """Cerrar la app (modo strict), como si el usuario la cerrara."""
        ...
