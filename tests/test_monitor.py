"""Attention Monitor con FakeCamera: ciclo de cámara, phone detection y privacidad."""

import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from helpers import AWAY_FACE, DOWN_FACE, FOCUSED_FACE, FakeClock, at

from nublock.attention.fake import FakeCamera, FakeFaceAnalyzer, FakePhoneDetector
from nublock.attention.monitor import AttentionMonitor, AttentionPipeline, phone_crop_box
from nublock.attention.state_machine import AttentionTransition
from nublock.attention.states import AttentionState as S
from nublock.attention.zone import DEFAULT_ZONE
from nublock.config import AttentionConfig

CONFIG = AttentionConfig(camera_retry_seconds=10, state_debounce_seconds=2)


class Rig:
    """Monitor armado con fakes; `step(seconds)` avanza el reloj a 8 FPS."""

    def __init__(self, camera: FakeCamera | None = None, phone_score: float | None = None) -> None:
        self.clock = FakeClock(at(0))
        self.camera = camera or FakeCamera()
        self.analyzer = FakeFaceAnalyzer(FOCUSED_FACE)
        self.phone = FakePhoneDetector(phone_score) if phone_score is not None else None
        self.transitions: list[AttentionTransition] = []
        self.monitor = AttentionMonitor(
            CONFIG,
            self.camera,
            lambda: AttentionPipeline(CONFIG, DEFAULT_ZONE, self.analyzer, self.phone),
            self.transitions.append,
            clock=self.clock,
        )

    def step(self, seconds: float = 0.125) -> None:
        for _ in range(round(seconds * 8)):
            self.monitor.step()
            self.clock.advance(0.125)

    def states(self) -> list[S]:
        return [t.state for t in self.transitions]


def test_inactive_monitor_is_paused_and_never_opens_camera() -> None:
    rig = Rig()
    rig.step(2)
    assert rig.states() == [S.PAUSED]
    assert rig.camera.opens == 0


def test_active_monitor_opens_camera_and_tracks_attention() -> None:
    rig = Rig()
    rig.monitor.set_active(True)
    rig.step(1)
    assert rig.monitor.camera_open
    rig.analyzer.observation = AWAY_FACE
    rig.step(3)
    rig.analyzer.observation = None
    rig.step(3)
    assert rig.states() == [S.FOCUSED, S.LOOKING_AWAY, S.ABSENT]


def test_frames_are_downscaled_to_frame_width() -> None:
    rig = Rig()
    rig.monitor.set_active(True)
    rig.step()
    assert rig.analyzer.last_shape == (360, 640, 3)  # 1280x720 -> 640x360


def test_deactivating_releases_camera() -> None:
    rig = Rig()
    rig.monitor.set_active(True)
    rig.step(1)
    rig.monitor.set_active(False)
    rig.step()
    assert not rig.camera.is_open and rig.camera.releases == 1
    assert rig.states()[-1] == S.PAUSED


def test_unavailable_camera_retries_every_n_seconds() -> None:
    rig = Rig(camera=FakeCamera(available=False))
    rig.monitor.set_active(True)
    rig.step(5)
    assert rig.states() == [S.CAMERA_UNAVAILABLE]
    assert rig.camera.opens == 1
    rig.step(6)  # pasan los 10 s de camera_retry_seconds
    assert rig.camera.opens == 2
    rig.camera.available = True
    rig.step(13)  # reintento a los 20 s + 2 s de debounce
    assert rig.states() == [S.CAMERA_UNAVAILABLE, S.FOCUSED]


def test_read_failure_releases_and_marks_unavailable() -> None:
    rig = Rig()
    rig.monitor.set_active(True)
    rig.step(1)
    rig.camera.fail_reads = True
    rig.step()
    assert rig.states() == [S.FOCUSED, S.CAMERA_UNAVAILABLE]
    assert rig.camera.releases == 1


def test_missing_model_marks_camera_unavailable() -> None:
    def broken_factory() -> AttentionPipeline:
        raise FileNotFoundError("Falta el modelo")

    transitions: list[AttentionTransition] = []
    monitor = AttentionMonitor(
        CONFIG, FakeCamera(), broken_factory, transitions.append, clock=FakeClock(at(0))
    )
    monitor.set_active(True)
    monitor.step()
    assert [t.state for t in transitions] == [S.CAMERA_UNAVAILABLE]


def test_phone_detector_runs_only_when_looking_down_and_at_low_fps() -> None:
    rig = Rig(phone_score=0.9)
    rig.monitor.set_active(True)
    rig.step(3)
    assert rig.phone is not None and rig.phone.calls == 0  # mirando la pantalla: no corre
    rig.analyzer.observation = DOWN_FACE
    rig.step(4)
    assert rig.phone.calls == 4 * CONFIG.phone_detection.fps  # 2 FPS durante 4 s (no 8 FPS)
    assert rig.states() == [S.FOCUSED, S.PHONE]


def test_phone_detector_gets_full_resolution_crop_below_the_face() -> None:
    rig = Rig(phone_score=0.9)
    rig.monitor.set_active(True)
    rig.analyzer.observation = DOWN_FACE  # cara en y 25–60 % de un frame de 1280×720
    rig.step()
    assert rig.analyzer.last_shape == (360, 640, 3)  # la cara se analiza reducida
    assert rig.phone is not None and rig.phone.last_shape == (554, 554, 3)  # recorte sin reducir


def test_phone_crop_box_sits_below_the_face_and_inside_the_frame() -> None:
    x0, y0, x1, y1 = phone_crop_box((0.4, 0.25, 0.6, 0.6), 1280, 720)
    assert (x1 - x0, y1 - y0) == (554, 554)  # cuadrado de 2,2 × alto de la cara
    assert x0 + (x1 - x0) / 2 == 640  # centrado con la cara
    assert y0 <= 0.6 * 720 and y1 == 720  # todo lo que está bajo el mentón queda dentro
    assert phone_crop_box((0.0, 0.1, 0.1, 0.3), 1280, 720)[0] == 0  # cara en el borde
    assert phone_crop_box(None, 1280, 720) == (0, 0, 1280, 720)  # sin cara: frame completo


def test_debug_mode_measures_phone_without_changing_the_state() -> None:
    camera, analyzer, phone = FakeCamera(), FakeFaceAnalyzer(FOCUSED_FACE), FakePhoneDetector(0.9)
    pipeline = AttentionPipeline(CONFIG, DEFAULT_ZONE, analyzer, phone, always_check_phone=True)
    camera.open()
    frame = camera.read()
    assert frame is not None
    _, raw = pipeline.process(frame, at(0))
    assert phone.calls == 1 and pipeline.last_phone_score == 0.9
    assert raw == S.FOCUSED  # mirando la pantalla, un teléfono a la vista no es PHONE


def test_looking_down_without_phone_stays_looking_down() -> None:
    rig = Rig(phone_score=0.1)  # bajo min_score (0.5): cuaderno o teclado
    rig.monitor.set_active(True)
    rig.analyzer.observation = DOWN_FACE
    rig.step(4)
    assert rig.states() == [S.LOOKING_DOWN]


def test_run_loop_in_a_thread_stops_and_releases_camera() -> None:
    camera = FakeCamera()
    transitions: list[AttentionTransition] = []
    config = AttentionConfig(process_fps=30)
    monitor = AttentionMonitor(
        config,
        camera,
        lambda: AttentionPipeline(config, DEFAULT_ZONE, FakeFaceAnalyzer(FOCUSED_FACE), None),
        transitions.append,
    )
    monitor.set_active(True)
    thread = threading.Thread(target=monitor.run)
    thread.start()
    deadline = time.monotonic() + 3
    while not transitions and time.monotonic() < deadline:
        time.sleep(0.01)
    monitor.stop()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert transitions and transitions[0].state == S.FOCUSED
    assert not camera.is_open


# --- Privacidad (PRD sección 16, punto 7) -------------------------------------------


def test_privacy_no_frames_written_or_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> bool:
        raise AssertionError("cv2.imwrite no debe llamarse nunca")

    monkeypatch.setattr(cv2, "imwrite", forbidden)
    monkeypatch.chdir(tmp_path)  # cualquier archivo relativo caería aquí
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    rig = Rig(phone_score=0.9)
    rig.monitor.set_active(True)
    for observation in (FOCUSED_FACE, AWAY_FACE, DOWN_FACE, None):
        rig.analyzer.observation = observation
        rig.step(3)

    assert rig.analyzer.frames_seen > 50
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []  # ningún archivo creado
    # Ni el monitor ni el pipeline guardan arrays de imagen en sus atributos.
    for obj in (rig.monitor, rig.monitor._pipeline, rig.monitor.machine):
        assert not any(isinstance(value, np.ndarray) for value in vars(obj).values())
    # Lo único que sale del monitor son estados con timestamps.
    for transition in rig.transitions:
        assert not any(isinstance(value, np.ndarray) for value in vars(transition).values())
