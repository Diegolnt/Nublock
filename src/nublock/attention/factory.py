"""Construye las piezas reales (OpenCV + MediaPipe) del Attention Monitor."""

import logging
from collections.abc import Callable
from pathlib import Path

from nublock.attention.calibration import load_zone
from nublock.attention.camera import OpenCVCamera
from nublock.attention.face import MediaPipeFaceAnalyzer
from nublock.attention.monitor import AttentionMonitor, AttentionPipeline
from nublock.attention.phone import MediaPipePhoneDetector, PhoneDetector
from nublock.attention.state_machine import AttentionTransition
from nublock.attention.zone import DEFAULT_ZONE, CalibrationZone
from nublock.config import AttentionConfig
from nublock.paths import resolve_models_dir

logger = logging.getLogger(__name__)

FACE_MODEL = "face_landmarker.task"


def load_zone_or_default(calibration_path: Path) -> CalibrationZone:
    zone = load_zone(calibration_path)
    if zone is None:
        logger.warning("Sin calibración: usando una zona genérica. Corre `nublock calibrate`.")
        return DEFAULT_ZONE
    return zone


def build_pipeline(
    config: AttentionConfig, zone: CalibrationZone, debug: bool = False
) -> AttentionPipeline:
    """`debug=True`: guarda landmarks para dibujarlos y mide el teléfono siempre."""
    models = resolve_models_dir(config.models_dir)
    analyzer = MediaPipeFaceAnalyzer(models / FACE_MODEL, keep_landmarks=debug)
    phone: PhoneDetector | None = None
    if config.phone_detection.enabled:
        # score_threshold bajo: así el debug view muestra también los scores débiles.
        phone = MediaPipePhoneDetector(models / config.phone_detection.model, 0.1)
    return AttentionPipeline(config, zone, analyzer, phone, always_check_phone=debug)


def build_monitor(
    config: AttentionConfig,
    calibration_path: Path,
    publish: Callable[[AttentionTransition], None],
) -> AttentionMonitor:
    zone = load_zone_or_default(calibration_path)
    camera = OpenCVCamera(config.camera_index, config.capture_width)
    # Los modelos se cargan recién cuando la cámara se activa por primera vez.
    return AttentionMonitor(config, camera, lambda: build_pipeline(config, zone), publish)
