"""Zona "mirando la pantalla" y clasificación de cada frame en un estado *raw*."""

from dataclasses import asdict, dataclass

from nublock.attention.face import FaceObservation
from nublock.attention.states import AttentionState
from nublock.config import AttentionConfig


@dataclass(frozen=True)
class CalibrationZone:
    """Rangos de yaw/pitch (grados) medidos al mirar los puntos de calibración."""

    yaw_min: float
    yaw_max: float
    pitch_min: float
    pitch_max: float
    # +1 si un pitch mayor significa mirar más abajo; -1 si es al revés. Se mide al calibrar.
    down_sign: int = 1

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, float]) -> "CalibrationZone":
        return cls(
            yaw_min=float(data["yaw_min"]),
            yaw_max=float(data["yaw_max"]),
            pitch_min=float(data["pitch_min"]),
            pitch_max=float(data["pitch_max"]),
            down_sign=1 if data.get("down_sign", 1) >= 0 else -1,
        )


# Zona por defecto si nunca calibraste: un rango genérico alrededor de mirar al frente.
DEFAULT_ZONE = CalibrationZone(yaw_min=-20, yaw_max=20, pitch_min=-12, pitch_max=12, down_sign=1)


def classify_observation(
    observation: FaceObservation | None,
    zone: CalibrationZone,
    config: AttentionConfig,
    previous: AttentionState | None,
) -> AttentionState:
    """Estado raw de un frame (sin debounce). `previous` es el raw anterior (para hysteresis)."""
    if observation is None:
        return AttentionState.ABSENT

    # Hysteresis: estando FOCUSED la zona incluye todo el margen; para *volver* a FOCUSED
    # desde otro estado hay que entrar `hysteresis_deg` más adentro. Evita el "parpadeo".
    shrink = 0.0 if previous in (None, AttentionState.FOCUSED) else config.hysteresis_deg
    yaw_margin = config.yaw_margin_deg - shrink
    pitch_margin = config.pitch_margin_deg - shrink

    if not zone.yaw_min - yaw_margin <= observation.yaw <= zone.yaw_max + yaw_margin:
        return AttentionState.LOOKING_AWAY

    # Pasamos el pitch a "cuánto hacia abajo" para no depender del signo del modelo.
    down = observation.pitch * zone.down_sign
    low, high = sorted((zone.pitch_min * zone.down_sign, zone.pitch_max * zone.down_sign))
    if down > high + pitch_margin:
        return AttentionState.LOOKING_DOWN
    if down < low - pitch_margin:
        return AttentionState.LOOKING_AWAY  # mirando hacia arriba, fuera de la pantalla

    # Señal secundaria: cabeza al frente pero ojos muy abajo (ej. teléfono en las manos).
    gaze_threshold = config.gaze_down_threshold
    if previous in (AttentionState.LOOKING_DOWN, AttentionState.PHONE):
        gaze_threshold -= 0.1  # hysteresis también para la mirada
    if observation.gaze_down >= gaze_threshold:
        return AttentionState.LOOKING_DOWN
    return AttentionState.FOCUSED
