"""Head pose (euler_from_matrix) y clasificación de cada frame contra la zona calibrada."""

import math

import numpy as np
import pytest

from nublock.attention.face import FaceObservation, euler_from_matrix
from nublock.attention.states import AttentionState as S
from nublock.attention.zone import CalibrationZone, classify_observation
from nublock.config import AttentionConfig

# yaw_margin 8, pitch_margin 6, hysteresis 3, gaze_down_threshold 0.6
CONFIG = AttentionConfig()
ZONE = CalibrationZone(yaw_min=-15, yaw_max=15, pitch_min=-10, pitch_max=10, down_sign=1)


def face(yaw: float = 0, pitch: float = 0, gaze_down: float = 0.1) -> FaceObservation:
    return FaceObservation(yaw=yaw, pitch=pitch, roll=0, gaze_down=gaze_down)


def rotation(axis: str, degrees: float) -> np.ndarray:
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    matrices = {
        "x": [[1, 0, 0], [0, c, -s], [0, s, c]],
        "y": [[c, 0, s], [0, 1, 0], [-s, 0, c]],
        "z": [[c, -s, 0], [s, c, 0], [0, 0, 1]],
    }
    full = np.eye(4)
    full[:3, :3] = matrices[axis]
    return full


@pytest.mark.parametrize(
    ("axis", "expected"), [("y", (25, 0, 0)), ("x", (0, 25, 0)), ("z", (0, 0, 25))]
)
def test_euler_from_matrix(axis: str, expected: tuple[float, float, float]) -> None:
    assert euler_from_matrix(rotation(axis, 25)) == pytest.approx(expected, abs=1e-9)


def test_euler_identity_is_looking_straight() -> None:
    assert euler_from_matrix(np.eye(4)) == pytest.approx((0, 0, 0))


def classify(
    observation: FaceObservation | None,
    previous: S | None = S.FOCUSED,
    zone: CalibrationZone = ZONE,
) -> S:
    return classify_observation(observation, zone, CONFIG, previous)


def test_no_face_is_absent() -> None:
    assert classify(None) == S.ABSENT


def test_inside_zone_is_focused() -> None:
    assert classify(face(yaw=10, pitch=-5)) == S.FOCUSED


def test_margin_extends_the_zone() -> None:
    assert classify(face(yaw=22)) == S.FOCUSED  # 15 + 8 de margen
    assert classify(face(yaw=24)) == S.LOOKING_AWAY
    assert classify(face(yaw=-24)) == S.LOOKING_AWAY


def test_pitch_below_zone_is_looking_down_and_above_is_away() -> None:
    assert classify(face(pitch=17)) == S.LOOKING_DOWN  # 10 + 6 de margen
    assert classify(face(pitch=-17)) == S.LOOKING_AWAY


def test_down_sign_from_calibration_flips_pitch() -> None:
    flipped = CalibrationZone(yaw_min=-15, yaw_max=15, pitch_min=-10, pitch_max=10, down_sign=-1)
    assert classify(face(pitch=-17), zone=flipped) == S.LOOKING_DOWN
    assert classify(face(pitch=17), zone=flipped) == S.LOOKING_AWAY


def test_eyes_down_with_head_forward_is_looking_down() -> None:
    assert classify(face(gaze_down=0.7)) == S.LOOKING_DOWN
    assert classify(face(gaze_down=0.5)) == S.FOCUSED


def test_hysteresis_requires_going_further_inside_to_return() -> None:
    near_edge = face(yaw=21)  # dentro del margen (23) pero no del margen - hysteresis (20)
    assert classify(near_edge, previous=S.FOCUSED) == S.FOCUSED
    assert classify(near_edge, previous=S.LOOKING_AWAY) == S.LOOKING_AWAY
    assert classify(face(yaw=19), previous=S.LOOKING_AWAY) == S.FOCUSED


def test_gaze_hysteresis() -> None:
    assert classify(face(gaze_down=0.55), previous=S.LOOKING_DOWN) == S.LOOKING_DOWN
    assert classify(face(gaze_down=0.55), previous=S.FOCUSED) == S.FOCUSED
