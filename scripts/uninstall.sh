#!/bin/sh
# Desinstala Nublock. Uso: sh uninstall.sh [--all]   (--all también borra tu historial)
set -u
APP="${NUBLOCK_DEST:-$HOME/Applications}/Nublock.app"
pkill -f "Nublock.app/Contents/MacOS/Nublock" 2>/dev/null
pkill -f -- "-m nublock run" 2>/dev/null
# Abrir al iniciar sesión (LaunchAgent / Login Items)
if [ -x "$APP/Contents/MacOS/Nublock" ]; then "$APP/Contents/MacOS/Nublock" --login-item off >/dev/null 2>&1; fi
# Bloqueo de sitios: quita el helper y limpia /etc/hosts (pide tu contraseña)
if [ -f /Library/PrivilegedHelperTools/local.nublock.hosts.sh ] && [ -x "$APP/Contents/Resources/python/bin/python3" ]; then
  "$APP/Contents/Resources/python/bin/python3" -m nublock sites remove
fi
rm -rf "$APP"
if [ "${1:-}" = "--all" ]; then
  rm -rf "$HOME/Library/Application Support/nublock" "$HOME/Library/Logs/nublock"
  echo "Nublock y tu historial fueron borrados."
else
  echo "Nublock desinstalado (tu historial sigue en ~/Library/Application Support/nublock)."
fi
