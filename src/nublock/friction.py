"""Fricción del modo strict (FR-23): desactivar algo cuesta esperar y escribir una frase.

Es un *commitment device*: no impide desactivar, pero obliga a decidirlo con calma en vez
de por impulso.
"""

import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from nublock.config import BlockingConfig
from nublock.timeutils import utc_now

FrictionAction = Literal["pause_all", "stop_focus", "disable_rule"]
EXPIRY = timedelta(minutes=10)  # una solicitud vieja ya no sirve


@dataclass(frozen=True)
class FrictionRequest:
    token: str
    action: FrictionAction
    target: str | None  # rule_id para disable_rule
    created_at: datetime


@dataclass(frozen=True)
class FrictionResult:
    ok: bool
    request: FrictionRequest | None = None
    wait_seconds: float = 0.0  # > 0: todavía no se puede confirmar
    error: str | None = None


class FrictionGate:
    """Guarda solicitudes pendientes. Lo usan los threads del dashboard: protegido con un Lock."""

    def __init__(self, config: BlockingConfig, clock: Callable[[], datetime] = utc_now) -> None:
        self.phrase = config.confirmation_phrase
        self.wait = timedelta(seconds=config.friction_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        self._requests: dict[str, FrictionRequest] = {}

    def request(self, action: FrictionAction, target: str | None = None) -> FrictionRequest:
        # secrets.token_urlsafe: texto aleatorio impredecible (no se puede adivinar el token).
        request = FrictionRequest(secrets.token_urlsafe(12), action, target, self._clock())
        with self._lock:
            self._requests[request.token] = request
        return request

    def get(self, token: str) -> FrictionRequest | None:
        with self._lock:
            return self._requests.get(token)

    def remaining(self, request: FrictionRequest) -> float:
        return max(0.0, (request.created_at + self.wait - self._clock()).total_seconds())

    def confirm(self, token: str, phrase: str) -> FrictionResult:
        now = self._clock()
        with self._lock:
            request = self._requests.get(token)
            if request is None or now - request.created_at > EXPIRY:
                self._requests.pop(token, None)
                return FrictionResult(ok=False, error="La solicitud no existe o expiró.")
            wait = (request.created_at + self.wait - now).total_seconds()
            if wait > 0:
                return FrictionResult(ok=False, request=request, wait_seconds=wait)
            if phrase.strip() != self.phrase:
                return FrictionResult(ok=False, request=request, error="La frase no coincide.")
            del self._requests[token]  # cada solicitud sirve una sola vez
        return FrictionResult(ok=True, request=request)
