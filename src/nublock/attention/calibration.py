"""Calibración (FR-32): mirar puntos de cada monitor y derivar la zona "mirando la pantalla"."""

import json
import statistics
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path

from nublock.attention.camera import Camera, to_rgb
from nublock.attention.face import FaceAnalyzer
from nublock.attention.zone import CalibrationZone
from nublock.timeutils import to_iso, utc_now

# (key, texto). Las keys "top"/"bottom" sirven para saber hacia dónde crece el pitch.
POINTS: tuple[tuple[str, str], ...] = (
    ("center", "el CENTRO"),
    ("top-left", "la esquina SUPERIOR IZQUIERDA"),
    ("top-right", "la esquina SUPERIOR DERECHA"),
    ("bottom-left", "la esquina INFERIOR IZQUIERDA"),
    ("bottom-right", "la esquina INFERIOR DERECHA"),
)

Sample = tuple[float, float]  # (yaw, pitch)


class CalibrationError(Exception):
    pass


def compute_zone(samples: Mapping[str, Sequence[Sample]]) -> CalibrationZone:
    """Zona = rango de las medianas de cada punto. Keys como 'm1-top-left' -> (yaw, pitch)."""
    medians = {
        key: (statistics.median(s[0] for s in values), statistics.median(s[1] for s in values))
        for key, values in samples.items()
        if values
    }
    if len(medians) < 2:
        raise CalibrationError("se necesitan al menos 2 puntos con cara detectada")
    yaws = [yaw for yaw, _ in medians.values()]
    pitches = [pitch for _, pitch in medians.values()]
    top = [pitch for key, (_, pitch) in medians.items() if "top" in key]
    bottom = [pitch for key, (_, pitch) in medians.items() if "bottom" in key]
    down_sign = 1
    if top and bottom and statistics.mean(bottom) < statistics.mean(top):
        down_sign = -1  # en este modelo/cámara, mirar abajo baja el pitch
    return CalibrationZone(
        yaw_min=min(yaws),
        yaw_max=max(yaws),
        pitch_min=min(pitches),
        pitch_max=max(pitches),
        down_sign=down_sign,
    )


def save_zone(zone: CalibrationZone, path: Path, created_at: datetime | None = None) -> None:
    """Guarda solo números (ángulos), nunca imágenes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {**zone.to_dict(), "created_at": to_iso(created_at or utc_now())}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_zone(path: Path) -> CalibrationZone | None:
    if not path.exists():
        return None
    return CalibrationZone.from_dict(json.loads(path.read_text(encoding="utf-8")))


def run_calibration(
    camera: Camera,
    analyzer: FaceAnalyzer,
    monitors: int,
    frame_width: int,
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
    sample_seconds: float = 2.0,
) -> CalibrationZone:
    """Calibración interactiva en la terminal. La cámara debe estar abierta."""
    samples: dict[str, list[Sample]] = {}
    for monitor in range(1, monitors + 1):
        for key, label in POINTS:
            where = f"{label} del monitor {monitor}" if monitors > 1 else label
            ask(f"Mira {where} y presiona Enter... ")
            samples[f"m{monitor}-{key}"] = _collect(camera, analyzer, frame_width, sample_seconds)
            say(f"  {len(samples[f'm{monitor}-{key}'])} muestras")
    return compute_zone(samples)


def _collect(camera: Camera, analyzer: FaceAnalyzer, width: int, seconds: float) -> list[Sample]:
    collected: list[Sample] = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        frame = camera.read()
        if frame is None:
            continue
        observation = analyzer.analyze(to_rgb(frame, width))
        if observation is not None:
            collected.append((observation.yaw, observation.pitch))
    return collected


def run_calibration_gui(
    camera: Camera,
    analyzer: FaceAnalyzer,
    monitors: int,
    frame_width: int,
    sample_seconds: float = 2.0,
) -> CalibrationZone | None:
    """Calibración en una ventana (sin terminal): ESPACIO mide cada punto, Esc cancela.

    Retorna None si se cancela. La vista previa es solo en vivo: nada se guarda.
    """
    import cv2  # import tardío: solo esta función abre ventanas

    window = "Nublock - calibracion (ESPACIO = medir, Esc = cancelar)"
    points = [
        (f"m{monitor}-{key}", f"{label} del monitor {monitor}" if monitors > 1 else label)
        for monitor in range(1, monitors + 1)
        for key, label in POINTS
    ]
    samples: dict[str, list[Sample]] = {}
    index = 0
    measuring_until: float | None = None
    try:
        while index < len(points):
            frame = camera.read()
            if frame is None:
                continue
            observation = analyzer.analyze(to_rgb(frame, frame_width))
            key, label = points[index]
            now = time.monotonic()
            if measuring_until is not None:
                if observation is not None:
                    samples[key].append((observation.yaw, observation.pitch))
                if now >= measuring_until:
                    measuring_until = None
                    index += 1
                    continue
            # Vista previa reducida y en espejo (como un espejo, más natural para el usuario).
            height, width = frame.shape[:2]
            scale = 640 / width
            view = cv2.flip(cv2.resize(frame, (640, round(height * scale))), 1)
            white, green, red = (255, 255, 255), (80, 200, 80), (60, 60, 255)
            step = f"Paso {index + 1}/{len(points)}"
            action = "Midiendo... no muevas la cabeza" if measuring_until else "y presiona ESPACIO"
            # Las fuentes de OpenCV no tienen tildes: textos en ASCII.
            cv2.putText(view, step, (16, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.7, white, 2)
            cv2.putText(view, f"Mira {label}", (16, 64), cv2.FONT_HERSHEY_SIMPLEX, 0.7, white, 2)
            cv2.putText(view, action, (16, 96), cv2.FONT_HERSHEY_SIMPLEX, 0.6, white, 1)
            face = "Cara detectada" if observation is not None else "No veo tu cara"
            color = green if observation is not None else red
            cv2.putText(
                view, face, (16, view.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2
            )
            cv2.imshow(window, view)
            pressed = cv2.waitKey(1) & 0xFF
            if pressed == 27:  # Esc
                return None
            if pressed == 32 and measuring_until is None:  # ESPACIO
                samples[key] = []
                measuring_until = now + sample_seconds
    finally:
        cv2.destroyAllWindows()
    return compute_zone(samples)
