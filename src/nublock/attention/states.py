"""Estados de atención (FR-34)."""

from enum import StrEnum


class AttentionState(StrEnum):
    # StrEnum: cada miembro también es un str, así se guarda directo en SQLite.
    FOCUSED = "FOCUSED"
    LOOKING_AWAY = "LOOKING_AWAY"
    LOOKING_DOWN = "LOOKING_DOWN"
    PHONE = "PHONE"
    ABSENT = "ABSENT"
    PAUSED = "PAUSED"
    CAMERA_UNAVAILABLE = "CAMERA_UNAVAILABLE"


# Estados que pueden generar una intervention (ABSENT se registra como pausa, sin alerta).
DISTRACTED_STATES = frozenset(
    {AttentionState.LOOKING_AWAY, AttentionState.LOOKING_DOWN, AttentionState.PHONE}
)
