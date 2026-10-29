"""M8: instancia única, Info.plist de la app, `nublock doctor` y modelos sin depender del cwd."""

import sys
from pathlib import Path

import pytest

from nublock import cli
from nublock.config import Config, SiteConfig
from nublock.doctor import Check, format_checks, run_checks
from nublock.instance import ALREADY_RUNNING_EXIT_CODE, InstanceLock
from nublock.interventions.app_bundle import executable_path, info_plist
from nublock.paths import resolve_models_dir


def test_only_one_instance_per_lock(tmp_path: Path) -> None:
    first, second = InstanceLock(tmp_path / "n.lock"), InstanceLock(tmp_path / "n.lock")
    assert first.acquire()
    assert not second.acquire()
    assert second.held_by_other()
    first.release()
    assert not second.held_by_other()
    assert second.acquire()
    second.release()


def test_run_exits_with_code_3_when_already_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "default_log_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(cli, "default_config_path", lambda: tmp_path / "missing.yaml")
    db = tmp_path / "nublock.db"
    other = InstanceLock(db.with_suffix(".lock"))
    assert other.acquire()  # "otra" instancia
    assert cli.main(["--db", str(db), "run", "--no-camera"]) == ALREADY_RUNNING_EXIT_CODE
    assert "ya está corriendo" in capsys.readouterr().err
    other.release()


def test_app_info_plist_has_camera_text_and_launcher_keys() -> None:
    plist = info_plist(python="/venv/bin/python", dashboard_url="http://127.0.0.1:9000")
    assert "Nunca graba" in str(plist["NSCameraUsageDescription"])
    assert plist["NublockPython"] == "/venv/bin/python"
    assert plist["NublockDashboard"] == "http://127.0.0.1:9000"
    assert info_plist()["NublockPython"] == sys.executable


def test_models_dir_is_found_from_any_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not (Path(__file__).resolve().parents[1] / "models" / "face_landmarker.task").exists():
        pytest.skip("modelos no descargados (ver README)")
    monkeypatch.chdir(tmp_path)  # Nublock.app arranca desde el home, no desde el repo
    resolved = resolve_models_dir(Path("models"))
    assert resolved.is_dir() and (resolved / "face_landmarker.task").exists()
    assert resolve_models_dir(Path("/abs/models")) == Path("/abs/models")


def checks_for(tmp_path: Path, status: dict[str, str] | None, **kwargs: object) -> list[Check]:
    app = tmp_path / "Nublock.app"
    executable = executable_path(app)
    executable.parent.mkdir(parents=True)
    executable.write_text("")
    defaults: dict[str, object] = {
        "config": Config(sites=[SiteConfig(domain="youtube.com")]),
        "config_path": tmp_path / "config.yaml",
        "app": app,
        "status": status,
        "calibration_path": tmp_path / "missing.json",
        "sites_installed": False,
        "running": False,
    }
    defaults.update(kwargs)
    return run_checks(**defaults)  # type: ignore[arg-type]


def test_doctor_reports_missing_permissions_with_fixes(tmp_path: Path) -> None:
    status = {
        "notifications": "granted",
        "camera": "not_determined",
        "screen_recording": "not_granted",
        "login_item": "not_registered",
    }
    by_name = {check.name: check for check in checks_for(tmp_path, status)}
    assert by_name["Notificaciones de Nublock"].ok
    camera = by_name["Cámara para Nublock"]
    assert not camera.ok and camera.fix == "python -m nublock doctor --fix" and not camera.optional
    assert by_name["Abrir al iniciar sesión"].optional
    assert by_name["Bloqueo de sitios (/etc/hosts)"].fix == "python -m nublock sites setup"
    text = format_checks(list(by_name.values()))
    assert "✓ Notificaciones de Nublock: granted" in text
    assert (
        "✗ Cámara para Nublock: not_determined" in text
        and "→ python -m nublock doctor --fix" in text
    )
    assert "· Calibración de la cámara" in text  # opcional


def test_doctor_all_good(tmp_path: Path) -> None:
    status = dict.fromkeys(("notifications", "camera", "screen_recording"), "granted")
    status["login_item"] = "enabled"
    calibration = tmp_path / "calibration.json"
    calibration.write_text("{}")
    checks = checks_for(
        tmp_path, status, calibration_path=calibration, sites_installed=True, running=True
    )
    python_check = next(c for c in checks if c.name == "Python de la app")
    assert not python_check.ok  # el Info.plist falso no apunta a este venv
    others = [c for c in checks if c.name != "Python de la app"]
    assert format_checks(others).endswith("Todo listo.")


def test_launch_agent_opens_the_app_through_launch_services() -> None:
    from nublock.autostart import LABEL, launch_agent_plist

    plist = launch_agent_plist(Path("/Users/x/Applications/Nublock.app"))
    assert plist == {
        "Label": LABEL,
        "ProgramArguments": ["/usr/bin/open", "-a", "/Users/x/Applications/Nublock.app"],
        "RunAtLoad": True,
    }


def test_doctor_counts_launch_agent_as_autostart(tmp_path: Path) -> None:
    status = {"login_item": "not_found"}
    login = next(c for c in checks_for(tmp_path, status, launch_agent=True) if "iniciar" in c.name)
    assert login.ok and login.detail == "enabled (LaunchAgent)"
