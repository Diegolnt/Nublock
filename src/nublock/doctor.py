"""`nublock doctor`: revisa que todo esté listo (onboarding de permisos, M8)."""

import json
import plistlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from nublock.config import Config
from nublock.interventions.app_bundle import executable_path, run_app
from nublock.paths import resolve_models_dir

FACE_MODEL = "face_landmarker.task"

# Paneles de System Settings (se abren con `open URL`).
SETTINGS = {
    "camera": "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera",
    "screen_recording": (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
    ),
    "notifications": "x-apple.systempreferences:com.apple.Notifications-Settings.extension",
}


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    fix: str | None = None  # qué hacer si no está OK
    optional: bool = False  # recomendado, pero Nublock funciona sin esto


def app_status(app: Path) -> dict[str, str] | None:
    """Permisos de Nublock.app según macOS (`Nublock --status`), o None si no se pudo."""
    if not executable_path(app).exists():
        return None
    stdout, _ = run_app(app, "--status", timeout=30)
    try:
        return dict(json.loads(stdout))
    except json.JSONDecodeError:
        return None


def app_python(app: Path) -> str | None:
    """El Python del venv que la app ejecuta (clave NublockPython del Info.plist)."""
    info = app / "Contents" / "Info.plist"
    if not info.exists():
        return None
    with info.open("rb") as file:
        return plistlib.load(file).get("NublockPython")


def run_checks(
    config: Config,
    config_path: Path | None,
    app: Path,
    status: dict[str, str] | None,
    calibration_path: Path,
    sites_installed: bool,
    running: bool,
    launch_agent: bool = False,
) -> list[Check]:
    checks = [
        Check(
            "Config",
            config_path is not None,
            str(config_path) if config_path else "sin config.yaml: se usan los defaults",
            "cp config/config.example.yaml ~/Library/Application\\ Support/nublock/config.yaml",
        )
    ]
    models = resolve_models_dir(config.attention.models_dir)
    missing = [
        name
        for name in (FACE_MODEL, config.attention.phone_detection.model)
        if not (models / name).exists()
    ]
    checks.append(
        Check(
            "Modelos de MediaPipe",
            not missing,
            f"en {models.resolve()}" if not missing else f"faltan: {', '.join(missing)}",
            "descárgalos con los comandos `curl` del README",
        )
    )
    checks.append(
        Check(
            "Calibración de la cámara",
            calibration_path.exists(),
            str(calibration_path) if calibration_path.exists() else "sin calibrar (zona genérica)",
            "python -m nublock calibrate",
            optional=True,
        )
    )
    installed = executable_path(app).exists()
    checks.append(
        Check(
            "Nublock.app",
            installed,
            str(app) if installed else "no instalada",
            "python -m nublock app install",
        )
    )
    if installed:
        python = app_python(app)
        checks.append(
            Check(
                "Python de la app",
                python == sys.executable,
                python or "?",
                "python -m nublock app install  (la app apunta a otro venv)",
            )
        )
    permissions = (
        ("notifications", "Notificaciones de Nublock", False),
        ("camera", "Cámara para Nublock", False),
        ("screen_recording", "Screen Recording para Nublock (títulos de ventana)", True),
    )
    for key, label, optional in permissions:
        value = status.get(key, "?") if status else "?"
        checks.append(
            Check(label, value == "granted", value, "python -m nublock doctor --fix", optional)
        )
    login = status.get("login_item", "?") if status else "?"
    if launch_agent:
        login = "enabled (LaunchAgent)"
    checks.append(
        Check(
            "Abrir al iniciar sesión",
            login.startswith("enabled"),
            login,
            "python -m nublock app autostart-on",
            optional=True,
        )
    )
    if config.sites:
        checks.append(
            Check(
                "Bloqueo de sitios (/etc/hosts)",
                sites_installed,
                "instalado" if sites_installed else "no instalado",
                "python -m nublock sites setup",
            )
        )
    checks.append(
        Check("Nublock corriendo", running, "sí" if running else "no", "open -a Nublock", True)
    )
    return checks


def format_checks(checks: list[Check]) -> str:
    lines = []
    for check in checks:
        mark = "✓" if check.ok else ("·" if check.optional else "✗")
        line = f"{mark} {check.name}: {check.detail}"
        if not check.ok and check.fix:
            line += f"\n    → {check.fix}"
        lines.append(line)
    problems = sum(1 for check in checks if not check.ok and not check.optional)
    lines.append("")
    lines.append(
        "Todo listo." if problems == 0 else f"{problems} cosa(s) por resolver (✗). · = opcional."
    )
    return "\n".join(lines)


def fix_permissions(app: Path) -> dict[str, str] | None:
    """Pide los permisos que faltan (diálogos de macOS a nombre de "Nublock").

    Si alguno sigue sin darse (ej. lo negaste antes, o Screen Recording, que solo pregunta
    una vez), abre su panel de System Settings. Retorna el estado final.
    """
    run_app(app, "--request-permissions", background=False, timeout=300)
    status = app_status(app)
    for key, url in SETTINGS.items():
        if status is not None and status.get(key) != "granted":
            subprocess.run(["open", url], check=False)
    return status
