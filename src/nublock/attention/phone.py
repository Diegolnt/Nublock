"""Phone detection con MediaPipe Object Detector (EfficientDet-Lite0, clases COCO) — FR-33."""

import os
import time
from pathlib import Path
from typing import Protocol

from nublock.attention.camera import Frame

PHONE_CATEGORY = "cell phone"  # nombre de la clase en COCO


class PhoneDetector(Protocol):
    def detect(self, rgb_frame: Frame) -> float:
        """Score (0–1) del teléfono más probable en el frame; 0.0 si no hay ninguno."""
        ...

    def close(self) -> None: ...


class MediaPipePhoneDetector:
    def __init__(self, model_path: Path, min_score: float) -> None:
        if not model_path.exists():
            raise FileNotFoundError(
                f"Falta el modelo {model_path}. Descárgalo con los comandos del README."
            )
        os.environ.setdefault("GLOG_minloglevel", "2")
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        self._mp = mp
        options = vision.ObjectDetectorOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            score_threshold=min_score,
            category_allowlist=[PHONE_CATEGORY],  # ignora las otras 79 clases
            max_results=1,
        )
        self._detector = vision.ObjectDetector.create_from_options(options)
        self._last_timestamp_ms = -1

    def detect(self, rgb_frame: Frame) -> float:
        timestamp_ms = max(int(time.monotonic() * 1000), self._last_timestamp_ms + 1)
        self._last_timestamp_ms = timestamp_ms
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb_frame)
        result = self._detector.detect_for_video(image, timestamp_ms)
        scores = [
            category.score
            for detection in result.detections
            for category in detection.categories
            if category.category_name == PHONE_CATEGORY
        ]
        return max(scores, default=0.0)

    def close(self) -> None:
        self._detector.close()
