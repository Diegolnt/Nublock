"""Construye la release autocontenida de Nublock: Nublock.app con Python y todo adentro.

Uso (desde el repo, con el venv activado):

    python scripts/build_release.py [--base-url https://tu-pagina/nublock]

Resultado en dist/:
    Nublock-<versión>-macos-<arch>.zip   la app (arm64 = Apple Silicon, x86_64 = Intel)
    Nublock-<versión>-macos-<arch>.zip.sha256
    install.sh / uninstall.sh            para publicar junto al zip

Sube esos archivos a tu página; los usuarios instalan con
`curl -fsSL <base-url>/install.sh | sh`. No requiere firma de Apple (ver docs/DECISIONS.md).

Este script SÍ usa internet (descargar Python y las dependencias); la app resultante nunca.
"""

import argparse
import hashlib
import platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nublock import __version__  # noqa: E402
from nublock.interventions.app_bundle import build_app  # noqa: E402

# python-build-standalone: builds de CPython relocatables (funcionan desde cualquier carpeta).
# Versión fija para que el build sea reproducible.
PBS_RELEASE = "20261026"
PYTHON_VERSION = "3.11.18"
PBS_BASE = f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_RELEASE}"
ARCHES = {"arm64": "aarch64", "x86_64": "x86_64"}
MODELS = ("face_landmarker.task", "efficientdet_lite2.tflite")
BUILD_DIR = Path.home() / "Library" / "Caches" / "nublock-build"


def download(url: str, dest: Path) -> Path:
    if not dest.exists():
        print(f"  descargando {url.rsplit('/', 1)[-1]}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        # curl y no urllib: el Python de python.org no usa los certificados de macOS y falla
        # con CERTIFICATE_VERIFY_FAILED; curl sí los usa. -f: error si la respuesta es 4xx/5xx.
        subprocess.run(["curl", "-fL", "--progress-bar", "-o", str(tmp), url], check=True)
        tmp.rename(dest)
    return dest


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_python(cache: Path, arch: str) -> Path:
    platform_tag = f"{ARCHES[arch]}-apple-darwin"
    name = f"cpython-{PYTHON_VERSION}+{PBS_RELEASE}-{platform_tag}-install_only_stripped.tar.gz"
    tarball = download(f"{PBS_BASE}/{name}", cache / name)
    sums = download(f"{PBS_BASE}/SHA256SUMS", cache / f"SHA256SUMS-{PBS_RELEASE}")
    expected = next(
        line.split()[0] for line in sums.read_text().splitlines() if line.endswith(name)
    )
    if sha256(tarball) != expected:
        tarball.unlink()
        raise SystemExit(f"SHA-256 de {name} no coincide: descarga corrupta (vuelve a intentar).")
    return tarball


def run(command: list[str]) -> None:
    print("  $ " + " ".join(command[:6]) + (" ..." if len(command) > 6 else ""))
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="https://TU-PAGINA/nublock")
    args = parser.parse_args()

    arch = platform.machine()
    if arch not in ARCHES:
        raise SystemExit(f"Arquitectura no soportada: {arch}")
    # El build va fuera del repo: si Documents está en iCloud Drive, cientos de MB se subirían a
    # la nube, y iCloud agrega atributos (com.apple.fileprovider.*) que codesign rechaza.
    build, dist = BUILD_DIR, ROOT / "dist"
    app = build / "Nublock.app"
    resources = app / "Contents" / "Resources"

    print(f"1/6 Python {PYTHON_VERSION} relocatable ({arch})")
    tarball = fetch_python(build / "cache", arch)

    print("2/6 Nublock.app (launcher en Swift, sin NublockPython: usa el Python de adentro)")
    build_app(app, sounds=("Glass",), python=None, register=False)
    with tarfile.open(tarball) as archive:
        archive.extractall(resources, filter="data")  # filter="data": extracción segura
    python = resources / "python" / "bin" / "python3"

    print("3/6 Nublock y sus dependencias dentro de la app")
    run([str(python), "-m", "pip", "install", "--quiet", "--no-warn-script-location", str(ROOT)])
    # Fuera lo que no se usa al ejecutar: la batería de tests de PyObjC y los símbolos de debug
    # (.dSYM), que además traen atributos del Finder que codesign no acepta.
    site_packages = resources / "python" / "lib" / "python3.11" / "site-packages"
    shutil.rmtree(site_packages / "PyObjCTest", ignore_errors=True)
    for dsym in list(resources.rglob("*.dSYM")):
        shutil.rmtree(dsym)

    print("4/6 Modelos y config de ejemplo")
    (resources / "models").mkdir(exist_ok=True)
    for model in MODELS:
        source = ROOT / "models" / model
        if not source.exists():
            raise SystemExit(f"Falta models/{model}: descárgalo con los comandos del README.")
        shutil.copy(source, resources / "models" / model)
    shutil.copy(ROOT / "config" / "config.example.yaml", resources / "config.example.yaml")

    print("5/6 Firma ad-hoc del bundle completo")
    # codesign rechaza atributos extendidos (Finder, iCloud, procedencia): se limpian todos.
    run(["xattr", "-cr", str(app)])
    run(["codesign", "--force", "--deep", "--sign", "-", str(app)])

    print("6/6 Zip + SHA-256 + scripts de instalación")
    dist.mkdir(exist_ok=True)
    zip_path = dist / f"Nublock-{__version__}-macos-{arch}.zip"
    zip_path.unlink(missing_ok=True)
    run(["ditto", "-c", "-k", "--keepParent", str(app), str(zip_path)])
    (dist / f"{zip_path.name}.sha256").write_text(f"{sha256(zip_path)}  {zip_path.name}\n")
    install = (ROOT / "scripts" / "install.sh").read_text()
    install = install.replace("__VERSION__", __version__).replace("__BASE_URL__", args.base_url)
    (dist / "install.sh").write_text(install)
    shutil.copy(ROOT / "scripts" / "uninstall.sh", dist / "uninstall.sh")

    size_app = sum(f.stat().st_size for f in app.rglob("*") if f.is_file()) / 1e6
    print(f"\nListo: {zip_path} ({zip_path.stat().st_size / 1e6:.0f} MB; app {size_app:.0f} MB)")
    print(f"Publica en {args.base_url}/ : {zip_path.name}, su .sha256, install.sh, uninstall.sh")


if __name__ == "__main__":
    main()
