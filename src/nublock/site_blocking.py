"""Bloqueo de sitios por DNS con /etc/hosts (M7, versión sin extensión de browser).

Si `/etc/hosts` dice `0.0.0.0 youtube.com`, ningún browser ni app puede conectarse a
youtube.com. Editar /etc/hosts requiere root, así que se instala UNA vez (con tu contraseña
de administrador) un helper mínimo:

    1. Nublock (tu usuario) escribe la lista:
       /Library/Application Support/Nublock/blocked_domains.txt
    2. launchd ve el cambio (WatchPaths) y corre el helper como root.
    3. El helper reescribe solo su sección de /etc/hosts y vacía el caché de DNS.

Seguridad: el helper y su plist son de root (tu usuario no puede modificarlos), y el helper
solo acepta dominios válidos y solo escribe entradas que *bloquean* (0.0.0.0 / ::), nunca IPs
arbitrarias. La carpeta de la lista es de root: tu usuario puede escribir el archivo pero no
reemplazarlo por un symlink.
"""

import logging
import os
import plistlib
import pwd
import shlex
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path

from nublock.config import DOMAIN_PATTERN

logger = logging.getLogger(__name__)

LABEL = "local.nublock.hosts"
SHARED_DIR = Path("/Library/Application Support/Nublock")
LIST_PATH = SHARED_DIR / "blocked_domains.txt"
HELPER_PATH = Path("/Library/PrivilegedHelperTools") / f"{LABEL}.sh"
PLIST_PATH = Path("/Library/LaunchDaemons") / f"{LABEL}.plist"
HOSTS_PATH = Path("/etc/hosts")
BEGIN_MARKER = "# >>> nublock: sitios bloqueados (no editar a mano) >>>"
END_MARKER = "# <<< nublock <<<"
MAX_DOMAINS = 2000

# Script POSIX sh: corre como root. Argumentos: $1 = lista, $2 = hosts (opcional, para tests).
HELPER_SCRIPT = f"""#!/bin/sh
# Instalado por Nublock. launchd lo ejecuta como root cada vez que cambia la lista.
set -eu
LIST="$1"
HOSTS="${{2:-/etc/hosts}}"
BEGIN='{BEGIN_MARKER}'
END='{END_MARKER}'
# Solo un archivo normal: nunca seguir un symlink (podría apuntar a un archivo de root).
if [ ! -f "$LIST" ] || [ -L "$LIST" ]; then exit 0; fi
TMP="$(mktemp "$(dirname "$HOSTS")/.hosts.nublock.XXXXXX")"
trap 'rm -f "$TMP"' EXIT
# 1) /etc/hosts sin la sección anterior de Nublock
awk -v b="$BEGIN" -v e="$END" \\
  '$0 == b {{skip = 1; next}} $0 == e {{skip = 0; next}} !skip' "$HOSTS" > "$TMP"
# 2) solo líneas que son dominios válidos, máximo {MAX_DOMAINS}
DOMAINS="$(LC_ALL=C grep -E '{DOMAIN_PATTERN.pattern}' "$LIST" | head -n {MAX_DOMAINS} || true)"
if [ -n "$DOMAINS" ]; then
  {{
    echo "$BEGIN"
    for d in $DOMAINS; do echo "0.0.0.0 $d"; echo ":: $d"; done
    echo "$END"
  }} >> "$TMP"
fi
# 3) reemplazar /etc/hosts solo si cambió, y vaciar el caché de DNS
if ! cmp -s "$TMP" "$HOSTS"; then
  chmod 644 "$TMP"
  if [ "$(id -u)" -eq 0 ]; then
    chown root:wheel "$TMP"
    mv "$TMP" "$HOSTS"
    dscacheutil -flushcache || true
    killall -HUP mDNSResponder 2>/dev/null || true
  else
    mv "$TMP" "$HOSTS"
  fi
fi
"""


def expand_domains(domains: Iterable[str], subdomains: Iterable[str]) -> list[str]:
    """youtube.com -> youtube.com, www.youtube.com, m.youtube.com... (en hosts no hay comodines)."""
    prefixes = list(subdomains)
    result = set()
    for domain in domains:
        result.add(domain)
        result.update(f"{prefix}.{domain}" for prefix in prefixes)
    return sorted(result)


def helper_plist() -> dict[str, object]:
    return {
        "Label": LABEL,
        "ProgramArguments": ["/bin/sh", str(HELPER_PATH), str(LIST_PATH)],
        "WatchPaths": [str(LIST_PATH)],  # launchd lo ejecuta cuando ese archivo cambia
        "RunAtLoad": True,
    }


def is_installed() -> bool:
    """El helper está instalado y nuestro usuario puede escribir la lista."""
    return HELPER_PATH.exists() and PLIST_PATH.exists() and os.access(LIST_PATH, os.W_OK)


def blocked_in_hosts(hosts_path: Path = HOSTS_PATH) -> list[str]:
    """Dominios que la sección de Nublock bloquea hoy en /etc/hosts (para `sites status`)."""
    domains: list[str] = []
    inside = False
    for line in hosts_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line == BEGIN_MARKER:
            inside = True
        elif line == END_MARKER:
            inside = False
        elif inside and line.startswith("0.0.0.0 "):
            domains.append(line.split()[1])
    return domains


class SiteBlocker:
    """Escribe la lista de dominios a bloquear; el helper de root la aplica a /etc/hosts."""

    def __init__(self, subdomains: Iterable[str], list_path: Path = LIST_PATH) -> None:
        self._subdomains = list(subdomains)
        self._list_path = list_path
        self._current: list[str] | None = None  # lo último escrito (None = aún no escribimos)

    def apply(self, domains: Iterable[str]) -> bool:
        """Deja bloqueados exactamente `domains`. Retorna True si la lista cambió."""
        wanted = expand_domains(domains, self._subdomains)
        if wanted == self._current:
            return False
        try:
            # Escritura in-place: la carpeta es de root, no podemos crear archivos temporales ahí.
            self._list_path.write_text("".join(f"{d}\n" for d in wanted), encoding="utf-8")
        except OSError as exc:
            logger.warning("No se pudo actualizar la lista de sitios bloqueados: %s", exc)
            return False
        self._current = wanted
        logger.info("Sitios bloqueados: %s", ", ".join(sorted(set(domains))) or "(ninguno)")
        return True


def _run_as_admin(shell_command: str) -> subprocess.CompletedProcess[str]:
    """Ejecuta un comando como root pidiendo la contraseña con el diálogo estándar de macOS."""
    script = "on run argv\ndo shell script (item 1 of argv) with administrator privileges\nend run"
    return subprocess.run(
        ["osascript", "-e", script, shell_command], capture_output=True, text=True, check=False
    )


def install() -> subprocess.CompletedProcess[str]:
    """Instala el helper (pide la contraseña de administrador una vez)."""
    user = pwd.getpwuid(os.getuid()).pw_name
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "helper.sh"
        script.write_text(HELPER_SCRIPT, encoding="utf-8")
        plist = Path(tmp) / "helper.plist"
        with plist.open("wb") as file:
            plistlib.dump(helper_plist(), file)
        q = shlex.quote  # cita cada ruta para el shell (algunas tienen espacios)
        command = " && ".join(
            [
                f"install -d -o root -g wheel -m 755 {q(str(SHARED_DIR))} "
                f"{q(str(HELPER_PATH.parent))}",
                f"install -o root -g wheel -m 755 {q(str(script))} {q(str(HELPER_PATH))}",
                f"touch {q(str(LIST_PATH))}",
                f"chown {q(user)} {q(str(LIST_PATH))}",
                f"chmod 644 {q(str(LIST_PATH))}",
                f"install -o root -g wheel -m 644 {q(str(plist))} {q(str(PLIST_PATH))}",
                f"(launchctl bootout system/{LABEL} 2>/dev/null || true)",
                f"launchctl bootstrap system {q(str(PLIST_PATH))}",
            ]
        )
        return _run_as_admin(command)


def uninstall() -> subprocess.CompletedProcess[str]:
    """Quita el helper y la sección de Nublock de /etc/hosts."""
    q = shlex.quote
    empty = f"{SHARED_DIR}/empty.txt"
    command = " && ".join(
        [
            f"(launchctl bootout system/{LABEL} 2>/dev/null || true)",
            f": > {q(empty)}",  # lista vacía -> el helper deja /etc/hosts sin la sección
            f"/bin/sh {q(str(HELPER_PATH))} {q(empty)}",
            f"rm -f {q(str(PLIST_PATH))} {q(str(HELPER_PATH))}",
            f"rm -rf {q(str(SHARED_DIR))}",
        ]
    )
    return _run_as_admin(command)
