#!/bin/sh
# Desinstala Nublock. Uso: sh uninstall.sh [--all]   (--all también borra tu historial)
#
# Qué crea Nublock en un Mac (y qué borra este script):
#   ~/Applications/Nublock.app                          la app                      (siempre)
#   ~/Library/Application Support/nublock/              config, historial, calib.   (--all)
#   ~/Library/Logs/nublock/                             logs                        (--all)
#   ~/Library/Preferences/local.nublock.app.plist       preferencias de la app      (siempre)
#   ~/Library/LaunchAgents/local.nublock.autostart.plist  abrir al iniciar sesión   (siempre)
#   /Library/PrivilegedHelperTools/local.nublock.hosts.sh, /Library/LaunchDaemons/...,
#   /Library/Application Support/Nublock/ y su sección de /etc/hosts  bloqueo de sitios (siempre)
#   Permisos de cámara y grabación de pantalla dados a "Nublock"                    (siempre)
set -u
APP="${NUBLOCK_DEST:-$HOME/Applications}/Nublock.app"
BUNDLE_ID="local.nublock.app"
pkill -f "Nublock.app/Contents/MacOS/Nublock" 2>/dev/null
pkill -f -- "-m nublock run" 2>/dev/null
# Abrir al iniciar sesión (LaunchAgent / Login Items)
if [ -x "$APP/Contents/MacOS/Nublock" ]; then "$APP/Contents/MacOS/Nublock" --login-item off >/dev/null 2>&1; fi
rm -f "$HOME/Library/LaunchAgents/local.nublock.autostart.plist"
# Bloqueo de sitios: quita el helper y limpia /etc/hosts (pide tu contraseña)
if [ -f /Library/PrivilegedHelperTools/local.nublock.hosts.sh ] && [ -x "$APP/Contents/Resources/python/bin/python3" ]; then
  "$APP/Contents/Resources/python/bin/python3" -m nublock sites remove
fi
rm -rf "$APP"
# Permisos (cámara, grabación de pantalla) y preferencias guardados a nombre de Nublock
tccutil reset All "$BUNDLE_ID" >/dev/null 2>&1
defaults delete "$BUNDLE_ID" >/dev/null 2>&1
if [ "${1:-}" = "--all" ]; then
  rm -rf "$HOME/Library/Application Support/nublock" "$HOME/Library/Logs/nublock"
  echo "Nublock y tu historial fueron borrados."
else
  echo "Nublock desinstalado (tu historial sigue en ~/Library/Application Support/nublock)."
fi
