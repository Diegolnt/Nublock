"""Notificaciones: comando que se ejecuta y bundle Nublock.app (sin compilar ni notificar)."""

from pathlib import Path

from nublock.interventions.app_bundle import BUNDLE_ID, executable_path, info_plist, make_app_icon
from nublock.interventions.notifier import MacOSNotifier


def fake_app(tmp_path: Path) -> Path:
    app = tmp_path / "Nublock.app"
    executable = executable_path(app)
    executable.parent.mkdir(parents=True)
    executable.write_text("")
    return app


def test_uses_nublock_app_with_sound_dashboard_and_false_alarm(tmp_path: Path) -> None:
    app = fake_app(tmp_path)
    notifier = MacOSNotifier(app, dashboard_url="http://127.0.0.1:8765")
    command = notifier.command("Vuelve al foco", "Deja el teléfono", "Glass", True)
    assert command == [
        str(executable_path(app)),
        "--notify",
        "--title",
        "Vuelve al foco",
        "--message",
        "Deja el teléfono",
        "--sound",
        "Glass",
        "--dashboard",
        "http://127.0.0.1:8765",
        "--false-alarm",
    ]


def test_silent_notification_without_button(tmp_path: Path) -> None:
    command = MacOSNotifier(fake_app(tmp_path)).command("Regla", "Límite")
    assert "--sound" not in command and "--false-alarm" not in command


def test_falls_back_to_osascript_without_app(tmp_path: Path) -> None:
    command = MacOSNotifier(tmp_path / "missing.app").command("T", 'mensaje con "comillas"')
    assert command[0] == "osascript"
    assert command[-2:] == ['mensaje con "comillas"', ""]  # el texto va como argumento, no código


def test_info_plist_identifies_nublock() -> None:
    plist = info_plist()
    assert plist["CFBundleIdentifier"] == BUNDLE_ID
    assert plist["CFBundleName"] == plist["CFBundleExecutable"] == "Nublock"
    assert plist["LSUIElement"] is True  # sin ícono en el Dock
    assert plist["NSAppTransportSecurity"] == {"NSAllowsLocalNetworking": True}


def test_app_icon() -> None:
    icon = make_app_icon(256)
    assert icon.size == (256, 256) and icon.mode == "RGBA"
    assert icon.getpixel((2, 2))[3] == 0  # esquina transparente (forma redondeada)
    assert icon.getpixel((128, 128))[:3] == (255, 255, 255)  # nube blanca al centro
