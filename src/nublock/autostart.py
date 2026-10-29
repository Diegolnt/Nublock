"""Abrir Nublock.app al iniciar sesión (FR-73).

Primero se intenta `SMAppService` (lo moderno: aparece en System Settings > General > Login
Items). Si macOS no lo acepta (puede pasar con apps firmadas ad-hoc), se usa un LaunchAgent:
un plist en ~/Library/LaunchAgents que, al iniciar sesión, ejecuta `open -a Nublock.app`.
"""

import os
import plistlib
import subprocess
from pathlib import Path

LABEL = "local.nublock.autostart"


def launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def launch_agent_plist(app: Path) -> dict[str, object]:
    # `open -a`: macOS la abre como app (LaunchServices), así los permisos son de "Nublock".
    return {
        "Label": LABEL,
        "ProgramArguments": ["/usr/bin/open", "-a", str(app)],
        "RunAtLoad": True,
    }


def launch_agent_installed() -> bool:
    return launch_agent_path().exists()


def enable_launch_agent(app: Path) -> bool:
    path = launch_agent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as file:
        plistlib.dump(launch_agent_plist(app), file)
    domain = f"gui/{os.getuid()}"  # la sesión gráfica de tu usuario
    subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], capture_output=True, check=False)
    result = subprocess.run(
        ["launchctl", "bootstrap", domain, str(path)], capture_output=True, check=False
    )
    return result.returncode == 0


def disable_launch_agent() -> None:
    subprocess.run(
        ["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True, check=False
    )
    launch_agent_path().unlink(missing_ok=True)
