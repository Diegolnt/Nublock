"""Estado "en vivo" que el core escribe y el tray/dashboard leen desde otros threads."""

import threading
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from nublock.config import Mode


@dataclass(frozen=True)
class Snapshot:
    observe_only: bool = True
    attention_state: str | None = None
    camera_open: bool = False
    camera_paused: bool = False
    current_app: str | None = None
    current_category: str | None = None  # "productivity/subcategory"
    focus_active: bool = False
    focus_mode: Mode | None = None
    focus_ends_at: datetime | None = None
    on_break_until: datetime | None = None
    paused_until: datetime | None = None
    today_seconds: dict[str, float] = field(default_factory=dict)  # por productivity
    # M6: True si desactivar/pausar requiere la fricción del modo strict.
    strict_active: bool = False
    disabled_rules: dict[str, datetime] = field(default_factory=dict)  # rule_id -> hasta
    blocked_sites: list[str] = field(default_factory=list)  # M7: dominios bloqueados ahora


class LiveState:
    def __init__(self, observe_only: bool = True) -> None:
        # Lock (mutex): solo un thread a la vez puede leer/escribir el snapshot.
        self._lock = threading.Lock()
        self._snapshot = Snapshot(observe_only=observe_only)

    def update(self, **changes: Any) -> None:
        with self._lock:
            # replace(): copia del dataclass inmutable con algunos campos cambiados.
            self._snapshot = replace(self._snapshot, **changes)

    def snapshot(self) -> Snapshot:
        with self._lock:
            return self._snapshot
