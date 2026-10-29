"""Bloqueo de apps (FR-50): ocultar en modo soft, cerrar en modo strict."""

import logging
import os
from datetime import datetime, timedelta
from typing import Literal

from nublock.config import BlockingConfig
from nublock.tracker.platform.base import AppBlocker, WindowInfo

logger = logging.getLogger(__name__)

BlockAction = Literal["hide", "terminate"]

# Nunca se bloquean: el sistema, nuestro propio proceso y el intérprete que corre Nublock.
PROTECTED = frozenset({"loginwindow", "finder", "dock", "systemuiserver", "windowserver"})
MIN_INTERVAL = timedelta(seconds=2)  # no insistir sobre la misma app más de una vez cada 2 s


class Enforcer:
    def __init__(
        self, blocker: AppBlocker, config: BlockingConfig, own_pid: int | None = None
    ) -> None:
        self._blocker = blocker
        self._never_terminate = {name.casefold() for name in config.never_terminate}
        self._own_pid = os.getpid() if own_pid is None else own_pid
        self._last_action: dict[int, datetime] = {}

    def enforce(self, window: WindowInfo, strict: bool, now: datetime) -> BlockAction | None:
        """Oculta o cierra la app de `window`. Retorna la acción hecha, o None si no hizo nada."""
        name = window.process_name.casefold()
        if name in PROTECTED or window.pid == self._own_pid:
            return None
        last = self._last_action.get(window.pid)
        if last is not None and now - last < MIN_INTERVAL:
            return None
        self._last_action[window.pid] = now
        action: BlockAction = (
            "terminate" if strict and name not in self._never_terminate else "hide"
        )
        done = (
            self._blocker.terminate(window.pid)
            if action == "terminate"
            else self._blocker.hide(window.pid)
        )
        if not done:
            logger.warning(
                "No se pudo %s %s",
                "cerrar" if action == "terminate" else "ocultar",
                window.process_name,
            )
            return None
        logger.info("Bloqueo: %s %s", action, window.process_name)
        return action
