"""Distribución sin firma de Apple: modo release de la app, rutas por entorno y scripts."""

import subprocess
from pathlib import Path

import pytest

from nublock.interventions.app_bundle import info_plist
from nublock.paths import default_app_path, resolve_models_dir

ROOT = Path(__file__).resolve().parents[1]


def test_release_app_uses_its_bundled_python() -> None:
    assert "NublockPython" not in info_plist(python=None)  # Swift usa Contents/Resources/python
    assert info_plist(python="/venv/bin/python")["NublockPython"] == "/venv/bin/python"


def test_paths_follow_the_app_that_launched_us(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NUBLOCK_APP", "/Applications/Nublock.app")
    assert default_app_path() == Path("/Applications/Nublock.app")
    monkeypatch.delenv("NUBLOCK_APP")
    assert default_app_path() == Path.home() / "Applications" / "Nublock.app"
    bundled = tmp_path / "Resources" / "models"
    bundled.mkdir(parents=True)
    monkeypatch.setenv("NUBLOCK_MODELS_DIR", str(bundled))
    assert resolve_models_dir(Path("models")) == bundled


@pytest.mark.parametrize("script", ["install.sh", "uninstall.sh"])
def test_shell_scripts_are_valid_posix_sh(script: str) -> None:
    subprocess.run(["sh", "-n", str(ROOT / "scripts" / script)], check=True)


def test_install_script_verifies_checksum_and_avoids_quarantine() -> None:
    text = (ROOT / "scripts" / "install.sh").read_text()
    assert "__VERSION__" in text and "__BASE_URL__" in text  # build_release.py los reemplaza
    assert "shasum -a 256 -c" in text
    assert "xattr -dr com.apple.quarantine" in text
    assert "ditto -x -k" in text
