"""Construye `Nublock.app`, la app de macOS de Nublock (M8).

macOS asigna nombre, ícono y permisos a la *app bundle* que corre un proceso. El bundle contiene
un programa Swift (`macos_app/Nublock.swift`) que lanza y supervisa `python -m nublock run`,
muestra las notificaciones nativas y pide los permisos. Se construye con
`python -m nublock app install`.
"""

import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path

from PIL import Image, ImageDraw

from nublock import __version__

BUNDLE_ID = "local.nublock.app"  # identificador único de la app para macOS
# macOS mínimo: lo exige numpy (sus binarios piden 14.0). Sin `-target`, swiftc usaría la
# versión del Mac que compila (ej. 26.0) y la app no abriría en Macs con macOS más antiguo.
MIN_MACOS = "14.0"
APP_NAME = "Nublock"
SOURCE = Path(__file__).parent / "macos_app" / "Nublock.swift"
SYSTEM_SOUNDS = Path("/System/Library/Sounds")
LSREGISTER = (
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/"
    "LaunchServices.framework/Support/lsregister"
)


class BuildError(Exception):
    pass


def executable_path(app: Path) -> Path:
    return app / "Contents" / "MacOS" / APP_NAME


def info_plist(
    python: str | None = sys.executable,
    dashboard_url: str = "http://127.0.0.1:8765",
    bundle_id: str = BUNDLE_ID,
) -> dict[str, object]:
    """Metadata del bundle (Contents/Info.plist)."""
    return {
        "CFBundleIdentifier": bundle_id,
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleExecutable": APP_NAME,
        "CFBundleIconFile": APP_NAME,  # Contents/Resources/Nublock.icns
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
        "LSMinimumSystemVersion": MIN_MACOS,
        "LSUIElement": True,  # sin ícono en el Dock ni menú propio
        # App Transport Security: permite HTTP solo a direcciones locales (el dashboard).
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        # Obligatorio para usar la cámara: es el texto del diálogo de permiso de macOS.
        "NSCameraUsageDescription": (
            "Nublock analiza tu atención en la memoria del computador durante las focus "
            "sessions. Nunca graba ni guarda imágenes."
        ),
        # Claves propias que lee Nublock.swift. Sin NublockPython (release), la app usa el
        # Python que trae dentro (Contents/Resources/python).
        **({"NublockPython": python} if python else {}),
        "NublockDashboard": dashboard_url,
    }


def make_app_icon(size: int = 1024) -> Image.Image:
    """Ícono: nube blanca sobre un cuadrado redondeado azul (estilo de íconos de macOS)."""
    scale = 2  # dibujamos al doble y reducimos: bordes suaves (antialiasing)
    big = size * scale
    top, bottom = (59, 130, 246), (30, 64, 175)
    gradient = Image.new("RGBA", (big, big))
    draw = ImageDraw.Draw(gradient)
    for y in range(big):
        t = y / (big - 1)
        color = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom, strict=True))
        draw.line([(0, y), (big, y)], fill=(*color, 255))
    # Máscara con la forma del ícono: margen de ~10 % y esquinas de ~22 %, como los de macOS.
    mask = Image.new("L", (big, big), 0)
    inset, radius = round(big * 0.1), round(big * 0.18)
    ImageDraw.Draw(mask).rounded_rectangle(
        (inset, inset, big - inset, big - inset), radius, fill=255
    )
    icon = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    icon.paste(gradient, (0, 0), mask)

    cloud = ImageDraw.Draw(icon)
    white = (255, 255, 255, 255)

    def circle(cx: float, cy: float, r: float) -> None:
        cloud.ellipse(((cx - r) * big, (cy - r) * big, (cx + r) * big, (cy + r) * big), fill=white)

    circle(0.50, 0.46, 0.165)
    circle(0.36, 0.53, 0.115)
    circle(0.64, 0.52, 0.13)
    cloud.rounded_rectangle(
        (0.25 * big, 0.53 * big, 0.77 * big, 0.645 * big), round(0.06 * big), fill=white
    )
    return icon.resize((size, size), Image.Resampling.LANCZOS)


def build_app(
    dest: Path,
    sounds: Iterable[str] = ("Glass",),
    python: str | None = sys.executable,
    dashboard_url: str = "http://127.0.0.1:8765",
    bundle_id: str = BUNDLE_ID,
    register: bool = True,
) -> Path:
    """Compila y arma `dest` (ej. ~/Applications/Nublock.app). Reemplaza una versión anterior.

    `register=False` (tests): no la registra en LaunchServices.
    """
    if shutil.which("swiftc") is None:
        raise BuildError("Falta el compilador swiftc. Instálalo con: xcode-select --install")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        app = work / f"{APP_NAME}.app"
        resources = app / "Contents" / "Resources"
        resources.mkdir(parents=True)
        executable_path(app).parent.mkdir(parents=True)
        with (app / "Contents" / "Info.plist").open("wb") as file:
            plistlib.dump(info_plist(python, dashboard_url, bundle_id), file)

        iconset = work / f"{APP_NAME}.iconset"
        iconset.mkdir()
        icon = make_app_icon(1024)
        for points in (16, 32, 128, 256, 512):  # tamaños que exige iconutil (@1x y @2x)
            for factor, suffix in ((1, ""), (2, "@2x")):
                pixels = points * factor
                resized = icon.resize((pixels, pixels), Image.Resampling.LANCZOS)
                resized.save(iconset / f"icon_{points}x{points}{suffix}.png")
        _run(["iconutil", "-c", "icns", str(iconset), "-o", str(resources / f"{APP_NAME}.icns")])

        for sound in set(sounds):  # UNNotificationSound busca el sonido dentro del bundle
            source = SYSTEM_SOUNDS / f"{sound}.aiff"
            if source.exists():
                shutil.copy(source, resources / source.name)

        _run(
            [
                "swiftc",
                "-O",
                "-swift-version",
                "5",
                "-target",
                f"{platform.machine()}-apple-macos{MIN_MACOS}",
                str(SOURCE),
                "-o",
                str(executable_path(app)),
                *("-framework", "AppKit"),
                *("-framework", "AVFoundation"),
                *("-framework", "CoreGraphics"),
                *("-framework", "ServiceManagement"),
                *("-framework", "UserNotifications"),
            ]
        )
        # Firma "ad-hoc" (-s -): sin certificado de Apple, válida solo en este Mac.
        _run(["codesign", "--force", "--sign", "-", str(app)])

        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(app), dest)
    if register:
        # Registrarla en LaunchServices: macOS sabe abrirla (Spotlight, clicks en notificaciones).
        _run([LSREGISTER, "-f", str(dest)])
    return dest


def run_app(app: Path, *args: str, background: bool = True, timeout: float = 60) -> tuple[str, str]:
    """Ejecuta Nublock.app con `open` (LaunchServices) y retorna (stdout, stderr).

    Importante: si se ejecuta el binario directo desde una terminal, macOS evalúa la cámara y
    Screen Recording a nombre de la *terminal* (el proceso "responsable"). Con `open`, la app
    es responsable de sí misma y los permisos son los de "Nublock".
    """
    with tempfile.TemporaryDirectory() as tmp:
        out, err = Path(tmp) / "out", Path(tmp) / "err"
        command = ["open", "-W", "-n", "--stdout", str(out), "--stderr", str(err)]
        if background:
            command.append("-g")  # sin traer la app al frente
        command += ["-a", str(app), "--args", *args]
        try:
            subprocess.run(command, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            pass
        read = lambda path: path.read_text(encoding="utf-8") if path.exists() else ""  # noqa: E731
        return read(out), read(err)


def unregister(app: Path) -> None:
    """Quita una copia vieja del registro de LaunchServices (para no tener dos "Nublock")."""
    subprocess.run([LSREGISTER, "-u", str(app)], capture_output=True, check=False)


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise BuildError(f"{Path(command[0]).name} falló:\n{result.stderr.strip()}")
