"""Face landmarks + head pose con MediaPipe Face Landmarker (FR-31)."""

import logging
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from nublock.attention.camera import Frame

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FaceObservation:
    """Lo que se extrae de un frame. Son ángulos y scores: nunca la imagen."""

    yaw: float  # grados, giro izquierda/derecha
    pitch: float  # grados, arriba/abajo
    roll: float  # grados, inclinación lateral
    gaze_down: float  # 0–1, promedio de los blendshapes eyeLookDownLeft/Right
    # Rectángulo de la cara (x_min, y_min, x_max, y_max), normalizado 0–1. Sirve para ubicar
    # el recorte donde se busca el teléfono.
    face_box: tuple[float, float, float, float] | None = None
    # (x, y) normalizados 0–1. Solo se llenan para el debug view; nunca se guardan.
    landmarks: tuple[tuple[float, float], ...] = ()


class FaceAnalyzer(Protocol):
    def analyze(self, rgb_frame: Frame) -> FaceObservation | None:
        """None si no hay cara en el frame."""
        ...

    def close(self) -> None: ...


def euler_from_matrix(matrix: NDArray[np.floating]) -> tuple[float, float, float]:
    """(yaw, pitch, roll) en grados desde una matriz de transformación 4×4 (o 3×3).

    Usa la descomposición Z-Y-X de la submatriz de rotación R:
    pitch = rotación en X, yaw = rotación en Y, roll = rotación en Z.
    """
    r = np.asarray(matrix, dtype=float)[:3, :3]
    pitch = math.degrees(math.atan2(r[2, 1], r[2, 2]))
    yaw = math.degrees(math.atan2(-r[2, 0], math.hypot(r[2, 1], r[2, 2])))
    roll = math.degrees(math.atan2(r[1, 0], r[0, 0]))
    return yaw, pitch, roll


class MediaPipeFaceAnalyzer:
    def __init__(self, model_path: Path, keep_landmarks: bool = False) -> None:
        if not model_path.exists():
            raise FileNotFoundError(
                f"Falta el modelo {model_path}. Descárgalo con los comandos del README."
            )
        os.environ.setdefault("GLOG_minloglevel", "2")  # menos logs internos de MediaPipe
        # Import tardío: mediapipe tarda en cargar y solo se necesita con la cámara activa.
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        self._mp = mp
        options = vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        self._keep_landmarks = keep_landmarks
        self._last_timestamp_ms = -1

    def analyze(self, rgb_frame: Frame) -> FaceObservation | None:
        # En modo VIDEO el timestamp debe ser estrictamente creciente.
        timestamp_ms = max(int(time.monotonic() * 1000), self._last_timestamp_ms + 1)
        self._last_timestamp_ms = timestamp_ms
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb_frame)
        result = self._landmarker.detect_for_video(image, timestamp_ms)
        if not result.face_landmarks or not result.facial_transformation_matrixes:
            return None
        yaw, pitch, roll = euler_from_matrix(np.array(result.facial_transformation_matrixes[0]))
        scores: dict[str, float] = {}
        if result.face_blendshapes:
            scores = {cat.category_name: cat.score for cat in result.face_blendshapes[0]}
        gaze_down = (scores.get("eyeLookDownLeft", 0.0) + scores.get("eyeLookDownRight", 0.0)) / 2
        xs = [point.x for point in result.face_landmarks[0]]
        ys = [point.y for point in result.face_landmarks[0]]
        return FaceObservation(
            yaw=yaw,
            pitch=pitch,
            roll=roll,
            gaze_down=gaze_down,
            face_box=(min(xs), min(ys), max(xs), max(ys)),
            landmarks=tuple(zip(xs, ys, strict=True)) if self._keep_landmarks else (),
        )

    def close(self) -> None:
        self._landmarker.close()
