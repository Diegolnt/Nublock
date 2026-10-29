"""Provider falso para tests: el test decide qué ventana está activa y el idle."""

from nublock.tracker.platform.base import WindowInfo


class FakeWindowProvider:
    def __init__(self, window: WindowInfo | None = None, idle_seconds: float = 0.0) -> None:
        self.window = window
        self.idle_seconds = idle_seconds

    def get_active_window(self) -> WindowInfo | None:
        return self.window

    def get_idle_seconds(self) -> float:
        return self.idle_seconds


class FakeAppBlocker:
    """Blocker falso: registra qué se pidió en vez de ocultar/cerrar apps de verdad."""

    def __init__(self) -> None:
        self.actions: list[tuple[str, int]] = []  # ("hide" | "terminate", pid)

    def hide(self, pid: int) -> bool:
        self.actions.append(("hide", pid))
        return True

    def terminate(self, pid: int) -> bool:
        self.actions.append(("terminate", pid))
        return True
