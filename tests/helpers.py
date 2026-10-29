"""Helpers compartidos por los tests (no son fixtures, se importan directo)."""

from datetime import UTC, date, datetime, timedelta

from nublock.attention.face import FaceObservation
from nublock.timeutils import local_day_bounds
from nublock.tracker.platform.base import WindowInfo

# Mediodía local del jueves 2026-10-29: lejos de medianoche en cualquier timezone del sistema.
NOON = local_day_bounds(date(2026, 10, 29))[0] + timedelta(hours=12)
assert NOON.tzinfo is UTC


def make_window(
    process: str, title: str | None = None, *, app: str | None = None, pid: int = 100
) -> WindowInfo:
    return WindowInfo(process_name=process, pid=pid, app_name=app or process, window_title=title)


def at(seconds: float) -> datetime:
    """NOON + N segundos."""
    return NOON + timedelta(seconds=seconds)


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class RecordingNotifier:
    """Notifier falso que guarda lo que se le pidió notificar."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.sounds: list[str | None] = []
        self.false_alarm_buttons: list[bool] = []

    def notify(
        self,
        title: str,
        message: str,
        sound: str | None = None,
        false_alarm_button: bool = False,
    ) -> None:
        self.messages.append((title, message))
        self.sounds.append(sound)
        self.false_alarm_buttons.append(false_alarm_button)


FOCUSED_FACE = FaceObservation(yaw=0.0, pitch=0.0, roll=0.0, gaze_down=0.1)
AWAY_FACE = FaceObservation(yaw=45.0, pitch=0.0, roll=0.0, gaze_down=0.1)
# Cara centrada, ocupando del 25 % al 60 % del alto del frame.
DOWN_FACE = FaceObservation(
    yaw=0.0, pitch=35.0, roll=0.0, gaze_down=0.8, face_box=(0.4, 0.25, 0.6, 0.6)
)
