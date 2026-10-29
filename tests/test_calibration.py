from pathlib import Path

import pytest

from nublock.attention.calibration import (
    POINTS,
    CalibrationError,
    compute_zone,
    load_zone,
    run_calibration,
    save_zone,
)
from nublock.attention.face import FaceObservation
from nublock.attention.fake import FakeCamera, FakeFaceAnalyzer
from nublock.attention.zone import CalibrationZone


def test_zone_is_range_of_point_medians() -> None:
    samples = {
        "m1-center": [(0, 0), (1, 1), (50, 50)],  # la mediana ignora el valor raro
        "m1-top-left": [(-12, -8)],
        "m1-bottom-right": [(14, 9)],
    }
    zone = compute_zone(samples)
    assert zone == CalibrationZone(yaw_min=-12, yaw_max=14, pitch_min=-8, pitch_max=9, down_sign=1)


def test_down_sign_is_measured_from_top_and_bottom_points() -> None:
    samples = {"m1-top-left": [(0, 10)], "m1-bottom-left": [(0, -10)]}
    assert compute_zone(samples).down_sign == -1


def test_needs_at_least_two_points_with_face() -> None:
    with pytest.raises(CalibrationError):
        compute_zone({"m1-center": [(0, 0)], "m1-top-left": []})


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    zone = CalibrationZone(yaw_min=-30, yaw_max=25.5, pitch_min=-9, pitch_max=11, down_sign=-1)
    path = tmp_path / "calibration.json"
    save_zone(zone, path)
    assert load_zone(path) == zone
    assert load_zone(tmp_path / "missing.json") is None


def test_interactive_calibration_with_two_monitors() -> None:
    analyzer = FakeFaceAnalyzer()
    camera = FakeCamera()
    camera.open()
    # Segundo monitor a la derecha: yaw más alto.
    positions = {
        "CENTRO": (0, 0),
        "SUPERIOR IZQUIERDA": (-15, -8),
        "SUPERIOR DERECHA": (15, -8),
        "INFERIOR IZQUIERDA": (-15, 10),
        "INFERIOR DERECHA": (15, 10),
    }
    prompts: list[str] = []

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        yaw, pitch = next(value for key, value in positions.items() if key in prompt)
        if "monitor 2" in prompt:
            yaw += 40
        analyzer.observation = FaceObservation(yaw=yaw, pitch=pitch, roll=0, gaze_down=0)
        return ""

    zone = run_calibration(
        camera,
        analyzer,
        monitors=2,
        frame_width=640,
        ask=ask,
        say=lambda _: None,
        sample_seconds=0.01,
    )
    assert len(prompts) == 2 * len(POINTS)
    assert zone == CalibrationZone(yaw_min=-15, yaw_max=55, pitch_min=-8, pitch_max=10, down_sign=1)
