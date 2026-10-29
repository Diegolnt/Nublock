from datetime import timedelta

from helpers import NOON

from nublock.live_state import Snapshot
from nublock.ui.tray import GRAY, GREEN, RED, YELLOW, icon_color, make_icon, status_lines


def test_icon_color_follows_attention_state() -> None:
    assert icon_color(Snapshot(camera_open=True, attention_state="FOCUSED"), NOON) == GREEN
    assert icon_color(Snapshot(camera_open=True, attention_state="PHONE"), NOON) == YELLOW
    assert icon_color(Snapshot(camera_open=True, attention_state="ABSENT"), NOON) == GRAY


def test_icon_color_without_camera_follows_active_app() -> None:
    assert icon_color(Snapshot(current_category="productive/dev"), NOON) == GREEN
    assert icon_color(Snapshot(current_category="distracting/social"), NOON) == YELLOW
    assert icon_color(Snapshot(current_category="neutral/uncategorized"), NOON) == GRAY


def test_paused_is_gray() -> None:
    snapshot = Snapshot(
        camera_open=True, attention_state="FOCUSED", paused_until=NOON + timedelta(minutes=5)
    )
    assert icon_color(snapshot, NOON) == GRAY


def test_camera_indicator_dot() -> None:
    with_camera = make_icon(GREEN, camera_on=True)
    without = make_icon(GREEN, camera_on=False)
    assert with_camera.size == (64, 64)
    assert with_camera.getpixel((54, 10))[:3] == RED  # punto rojo arriba a la derecha (FR-71)
    assert without.getpixel((54, 10))[3] == 0  # transparente


def test_status_lines() -> None:
    snapshot = Snapshot(
        observe_only=False,
        camera_open=True,
        attention_state="FOCUSED",
        current_app="Code",
        current_category="productive/dev",
        focus_active=True,
        focus_mode="strict",
        focus_ends_at=NOON + timedelta(minutes=12),
        today_seconds={"productive": 3720, "distracting": 60},
    )
    assert status_lines(snapshot, NOON) == [
        "Focus (strict): quedan 12m 00s",
        "Cámara: activa · FOCUSED",
        "App: Code (productive/dev)",
        "Hoy: productive 1h 02m · neutral 0s · distracting 1m 00s",
    ]
