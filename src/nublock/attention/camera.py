"""Captura de video con OpenCV (FR-30).

Privacidad (PRD sección 16): un frame es una variable local que se procesa y se
descarta. Prohibido `cv2.imwrite`, guardarlo en atributos, loguearlo o serializarlo.
"""

import logging
from typing import Protocol

import cv2
import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)

Frame = NDArray[np.uint8]  # array (alto, ancho, 3)


class Camera(Protocol):
    def open(self) -> bool:
        """Intenta abrir la cámara. Retorna False si no está disponible o no hay permiso."""
        ...

    def read(self) -> Frame | None:
        """Un frame BGR, o None si falló la lectura."""
        ...

    def release(self) -> None:
        """Libera la cámara para otras apps (FR-36)."""
        ...


class OpenCVCamera:
    def __init__(self, index: int, width: int) -> None:
        self._index = index
        self._width = width
        self._capture: cv2.VideoCapture | None = None

    def open(self) -> bool:
        capture = cv2.VideoCapture(self._index)
        if not capture.isOpened():
            capture.release()
            logger.warning("No se pudo abrir la cámara %d (¿permiso de Camera?)", self._index)
            return False
        # Pedimos una resolución menor: menos CPU. La cámara puede ignorarlo.
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._capture = capture
        return True

    def read(self) -> Frame | None:
        if self._capture is None:
            return None
        ok, frame = self._capture.read()
        return frame if ok else None

    def release(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


def to_rgb(frame_bgr: Frame, max_width: int) -> Frame:
    """Reduce el frame a `max_width` de ancho y lo pasa de BGR (OpenCV) a RGB (MediaPipe)."""
    height, width = frame_bgr.shape[:2]
    if width > max_width:
        new_size = (max_width, round(height * max_width / width))  # (ancho, alto)
        frame_bgr = cv2.resize(frame_bgr, new_size, interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
