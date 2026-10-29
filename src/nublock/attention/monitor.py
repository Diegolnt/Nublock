"""Attention Monitor: el thread de cámara (~8 FPS) que publica transiciones de atención."""

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta

import cv2

from nublock.attention.camera import Camera, Frame, to_rgb
from nublock.attention.face import FaceAnalyzer, FaceObservation
from nublock.attention.phone import PhoneDetector
from nublock.attention.state_machine import AttentionStateMachine, AttentionTransition
from nublock.attention.states import AttentionState
from nublock.attention.zone import CalibrationZone, classify_observation
from nublock.config import AttentionConfig
from nublock.timeutils import utc_now

logger = logging.getLogger(__name__)

# Un teléfono visto hace menos de esto sigue contando (el detector corre a solo 1–2 FPS).
PHONE_MEMORY = timedelta(seconds=2)

Box = tuple[int, int, int, int]  # (x0, y0, x1, y1) en pixeles


def phone_crop_box(
    face_box: tuple[float, float, float, float] | None, width: int, height: int
) -> Box:
    """Región cuadrada bajo la cara, donde suele estar un teléfono en la mano.

    El detector reduce su entrada a 448×448: pasarle solo esta región (en vez del frame
    16:9 completo) hace que el teléfono ocupe muchos más pixeles y su score suba de
    ~0.1–0.4 a ~0.6–0.9 (medido, ver DECISIONS.md).
    """
    if face_box is None:
        return (0, 0, width, height)
    x_min, _, x_max, y_max = face_box
    face_height = (face_box[3] - face_box[1]) * height
    side = int(min(width, height, max(2.2 * face_height, 0.5 * height)))
    center_x = (x_min + x_max) / 2 * width
    center_y = y_max * height + 0.3 * side  # un poco bajo el mentón
    x0 = int(min(max(center_x - side / 2, 0), width - side))
    y0 = int(min(max(center_y - side / 2, 0), height - side))
    return (x0, y0, x0 + side, y0 + side)


class AttentionPipeline:
    """frame BGR -> (observación, estado raw). Compartido por el monitor y el debug view."""

    def __init__(
        self,
        config: AttentionConfig,
        zone: CalibrationZone,
        analyzer: FaceAnalyzer,
        phone_detector: PhoneDetector | None,
        always_check_phone: bool = False,
    ) -> None:
        self._config = config
        self._zone = zone
        self._analyzer = analyzer
        self._phone_detector = phone_detector
        self._phone_interval = timedelta(seconds=1 / config.phone_detection.fps)
        # True solo en el debug view: muestra el score aunque no estés mirando abajo.
        self._always_check_phone = always_check_phone
        self._last_raw: AttentionState | None = None
        self._last_phone_check: datetime | None = None
        self._last_phone_seen: datetime | None = None
        self.last_phone_score = 0.0
        self.last_phone_box: Box | None = None

    def process(
        self, frame_bgr: Frame, now: datetime
    ) -> tuple[FaceObservation | None, AttentionState]:
        # La cara se analiza en una copia reducida (rápido); el teléfono, en un recorte del
        # frame a resolución completa (más pixeles para un objeto chico).
        observation = self._analyzer.analyze(to_rgb(frame_bgr, self._config.frame_width))
        raw = classify_observation(observation, self._zone, self._config, self._last_raw)
        looking_down = raw in (AttentionState.LOOKING_DOWN, AttentionState.PHONE)
        wants_phone = looking_down or (self._always_check_phone and observation is not None)
        if self._phone_detector is not None and wants_phone:
            # FR-33: el detector (caro) corre mirando hacia abajo y a baja frecuencia.
            if (
                self._last_phone_check is None
                or now - self._last_phone_check >= self._phone_interval
            ):
                self._last_phone_check = now
                self._check_phone(frame_bgr, observation, now)
            seen_recently = (
                self._last_phone_seen is not None and now - self._last_phone_seen <= PHONE_MEMORY
            )
            if looking_down and seen_recently:
                raw = AttentionState.PHONE
        self._last_raw = raw
        return observation, raw

    def _check_phone(
        self, frame_bgr: Frame, observation: FaceObservation | None, now: datetime
    ) -> None:
        assert self._phone_detector is not None
        height, width = frame_bgr.shape[:2]
        face_box = observation.face_box if observation is not None else None
        x0, y0, x1, y1 = self.last_phone_box = phone_crop_box(face_box, width, height)
        crop = cv2.cvtColor(frame_bgr[y0:y1, x0:x1], cv2.COLOR_BGR2RGB)
        self.last_phone_score = self._phone_detector.detect(crop)
        logger.debug("phone score %.2f", self.last_phone_score)
        if self.last_phone_score >= self._config.phone_detection.min_score:
            self._last_phone_seen = now

    def close(self) -> None:
        self._analyzer.close()
        if self._phone_detector is not None:
            self._phone_detector.close()


class AttentionMonitor:
    def __init__(
        self,
        config: AttentionConfig,
        camera: Camera,
        pipeline_factory: Callable[[], AttentionPipeline],
        publish: Callable[[AttentionTransition], None],
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        # Dependency injection: en tests se pasan FakeCamera y un pipeline con fakes.
        self._config = config
        self._camera = camera
        self._pipeline_factory = pipeline_factory
        self._pipeline: AttentionPipeline | None = None
        self._publish = publish
        self._clock = clock
        self.machine = AttentionStateMachine(config.state_debounce_seconds)
        # threading.Event: flag thread-safe; el core lo prende/apaga desde otro thread.
        self._active = threading.Event()
        self._stop = threading.Event()
        self._camera_open = False
        self._retry_at: datetime | None = None

    @property
    def camera_open(self) -> bool:
        return self._camera_open

    def set_active(self, active: bool) -> None:
        if active:
            self._active.set()
        else:
            self._active.clear()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        """Target del thread: ~`process_fps` iteraciones por segundo hasta `stop()`."""
        period = 1 / self._config.process_fps
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                try:
                    self.step()
                except Exception:  # un error de cámara/modelo no debe tumbar Nublock (NFR-06)
                    logger.exception("Error en el attention monitor")
                    self._close_camera(retry=True)
                    self._emit(AttentionState.CAMERA_UNAVAILABLE)
                wait = period if self._camera_open else 0.5
                self._stop.wait(max(0.0, wait - (time.monotonic() - started)))
        finally:
            self._close_camera(retry=False)
            if self._pipeline is not None:
                self._pipeline.close()

    def step(self) -> None:
        """Una iteración: leer un frame, analizarlo y descartarlo."""
        now = self._clock()
        if not self._active.is_set():
            self._close_camera(retry=False)
            self._emit(AttentionState.PAUSED, now)
            return
        if not self._camera_open:
            if self._retry_at is not None and now < self._retry_at:
                self._emit(AttentionState.CAMERA_UNAVAILABLE, now)
                return
            if self._pipeline is None:
                try:
                    self._pipeline = self._pipeline_factory()
                except FileNotFoundError as exc:
                    logger.error("%s", exc)
                    self._retry_at = now + timedelta(seconds=self._config.camera_retry_seconds)
                    self._emit(AttentionState.CAMERA_UNAVAILABLE, now)
                    return
            if not self._camera.open():
                self._retry_at = now + timedelta(seconds=self._config.camera_retry_seconds)
                self._emit(AttentionState.CAMERA_UNAVAILABLE, now)
                return
            self._camera_open = True
            self._retry_at = None

        frame = self._camera.read()
        if frame is None:  # cámara desconectada u ocupada: liberar y reintentar (FR-36)
            self._close_camera(retry=True)
            self._emit(AttentionState.CAMERA_UNAVAILABLE, now)
            return
        assert self._pipeline is not None
        # El frame vive solo en estas variables locales; al salir de step() se descarta.
        _, raw = self._pipeline.process(frame, now)
        self._emit(raw, now)

    def _emit(self, raw: AttentionState, now: datetime | None = None) -> None:
        transition = self.machine.update(raw, now or self._clock())
        if transition is not None:
            self._publish(transition)

    def _close_camera(self, retry: bool) -> None:
        if self._camera_open:
            self._camera.release()
            self._camera_open = False
        if retry:
            self._retry_at = self._clock() + timedelta(seconds=self._config.camera_retry_seconds)
