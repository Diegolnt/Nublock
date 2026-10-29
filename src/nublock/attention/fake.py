"""Fakes para tests: cámara, analizador de cara y detector de teléfono sin hardware ni modelos."""

import numpy as np

from nublock.attention.camera import Frame
from nublock.attention.face import FaceObservation


class FakeCamera:
    """Entrega frames negros sintéticos. El test controla si está disponible."""

    def __init__(self, available: bool = True, width: int = 1280, height: int = 720) -> None:
        self.available = available
        self.fail_reads = False
        self.is_open = False
        self.opens = 0
        self.releases = 0
        self._shape = (height, width, 3)

    def open(self) -> bool:
        self.opens += 1
        self.is_open = self.available
        return self.available

    def read(self) -> Frame | None:
        if not self.is_open or self.fail_reads:
            return None
        return np.zeros(self._shape, dtype=np.uint8)

    def release(self) -> None:
        self.releases += 1
        self.is_open = False


class FakeFaceAnalyzer:
    """Retorna la observación que el test asigne en `observation` (None = sin cara)."""

    def __init__(self, observation: FaceObservation | None = None) -> None:
        self.observation = observation
        self.frames_seen = 0
        self.last_shape: tuple[int, ...] | None = None
        self.closed = False

    def analyze(self, rgb_frame: Frame) -> FaceObservation | None:
        self.frames_seen += 1
        self.last_shape = rgb_frame.shape
        return self.observation

    def close(self) -> None:
        self.closed = True


class FakePhoneDetector:
    def __init__(self, score: float = 0.0) -> None:
        self.score = score
        self.calls = 0
        self.last_shape: tuple[int, ...] | None = None

    def detect(self, rgb_frame: Frame) -> float:
        self.calls += 1
        self.last_shape = rgb_frame.shape
        return self.score

    def close(self) -> None:
        pass
