#!/bin/sh
# Instala Nublock en ~/Applications.
#
# Uso desde tu página:   curl -fsSL __BASE_URL__/install.sh | sh
#
# Se descarga con curl (no con el browser) a propósito: lo que baja el browser queda "en
# cuarentena" y macOS bloquea las apps sin firma de Apple. curl no marca la cuarentena.
#
# Variables opcionales: NUBLOCK_ZIP=archivo.zip (instalar un zip local, sin descargar),
# NUBLOCK_DEST=carpeta (en vez de ~/Applications), NUBLOCK_NO_OPEN=1 (no abrir al terminar).
set -eu
VERSION="__VERSION__"
BASE_URL="${NUBLOCK_BASE_URL:-__BASE_URL__}"
DEST="${NUBLOCK_DEST:-$HOME/Applications}"
ARCH="$(uname -m)"
ZIP_NAME="Nublock-$VERSION-macos-$ARCH.zip"

if [ "$(uname -s)" != "Darwin" ]; then echo "Nublock solo funciona en macOS." >&2; exit 1; fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [ -n "${NUBLOCK_ZIP:-}" ]; then
  ZIP="$NUBLOCK_ZIP"
else
  ZIP="$TMP/$ZIP_NAME"
  echo "Descargando Nublock $VERSION ($ARCH)..."
  curl -fL --progress-bar -o "$ZIP" "$BASE_URL/$ZIP_NAME" || {
    echo "No hay una versión para $ARCH en $BASE_URL" >&2; exit 1; }
  curl -fsSL -o "$TMP/$ZIP_NAME.sha256" "$BASE_URL/$ZIP_NAME.sha256"
  # Verifica que el archivo no se corrompió ni fue modificado en el camino.
  (cd "$TMP" && shasum -a 256 -c "$ZIP_NAME.sha256" >/dev/null) || {
    echo "El SHA-256 no coincide: descarga corrupta." >&2; exit 1; }
fi

# Si Nublock está abierto, se cierra antes de reemplazarlo.
pkill -f "Nublock.app/Contents/MacOS/Nublock" 2>/dev/null || true
pkill -f -- "-m nublock run" 2>/dev/null || true
sleep 1
mkdir -p "$DEST"
rm -rf "$DEST/Nublock.app"
ditto -x -k "$ZIP" "$DEST"  # ditto conserva permisos, symlinks y firma del bundle
xattr -dr com.apple.quarantine "$DEST/Nublock.app" 2>/dev/null || true
echo "Nublock instalado en $DEST/Nublock.app"

if [ -z "${NUBLOCK_NO_OPEN:-}" ]; then
  open "$DEST/Nublock.app"  # al abrir, Nublock muestra la ventana de permisos
fi
