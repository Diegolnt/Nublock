# Nublock

App local-first de self-monitoring (ver `PRD.md`). Estado: **M0–M8**: activity tracker para macOS,
clasificación y reglas, attention monitor con cámara, interventions, focus sessions, tray,
dashboard local, bloqueo de apps con modo strict y bloqueo de sitios. Nada sale del computador y nunca se guardan
imágenes.

## Instalación (macOS, Python 3.11+)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Modelos de MediaPipe (una sola vez; es la única descarga, la app nunca usa internet)
mkdir -p models
curl -fL -o models/face_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
curl -fL -o models/efficientdet_lite2.tflite \
  https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite2/int8/1/efficientdet_lite2.tflite

# Notificaciones nativas de "Nublock" (con ícono). Compila una app mínima en Swift; necesita las
# Command Line Tools (`xcode-select --install`). Cuando macOS pregunte, elige *Permitir*.
python -m nublock setup-notifications
```

Copia el config a su lugar (o usa `--config config/config.example.yaml` en cada comando):

```bash
cp config/config.example.yaml ~/Library/Application\ Support/nublock/config.yaml
```

## Instalar en otro Mac (sin terminal ni repo)

Construye la release una vez (descarga un Python relocatable y las dependencias; tarda unos
minutos):

```bash
python scripts/build_release.py --base-url https://tu-pagina.com/nublock
```

Sube a esa URL los archivos de `dist/` (`Nublock-<versión>-macos-arm64.zip`, su `.sha256`,
`install.sh`, `uninstall.sh`). Quien quiera instalar Nublock corre:

```bash
curl -fsSL https://tu-pagina.com/nublock/install.sh | sh
```

La app trae Python, las librerías y los modelos adentro: el otro Mac no necesita nada instalado.
No está firmada por Apple; por eso se instala con `curl` (lo que baja el browser queda en
"cuarentena" y macOS lo bloquea). La release es para la arquitectura del Mac donde la
construyes (arm64 = Apple Silicon).

Al abrirse, Nublock muestra la ventana de permisos (también en el menú → *Permisos y
configuración…*):

![Ventana de permisos](docs/img/permisos.png)

## Nublock como app desde el repo (desarrollo)

```bash
python -m nublock app install        # compila ~/Applications/Nublock.app (necesita xcode-select --install)
python -m nublock doctor --fix       # revisa todo y pide los permisos a nombre de "Nublock"
open -a Nublock                      # o búscala en Spotlight; vive en la barra de menú
python -m nublock app autostart-on   # (opcional) abrirla al iniciar sesión
```

La app lanza y supervisa `python -m nublock run` (con el venv de este repo) y usa siempre
`~/Library/Application Support/nublock/config.yaml`. Logs: `~/Library/Logs/nublock/`.

## Uso

```bash
python -m nublock run              # tracker + tray + dashboard + cámara (en focus sessions)
python -m nublock report today     # reporte en la terminal
python -m nublock calibrate        # calibrar la zona "mirando la pantalla" (usa la cámara)
python -m nublock attention-debug  # ventana en vivo con landmarks y estado (q para salir)
python -m nublock dashboard        # solo el dashboard, sin tracker
python -m nublock config           # validar la config y ver rutas
python -m nublock setup-notifications  # (re)crear Nublock.app para notificaciones nativas
```

- Dashboard: http://127.0.0.1:8765 (solo local).
- Tray: ícono en la barra de menú. Verde = foco, amarillo = distraído, gris = pausado; un punto
  rojo indica que la cámara está encendida. Desde el menú: focus sessions, pausar cámara, pausar
  todo 15 min, "falsa alarma", abrir dashboard, salir.
- La cámara solo se enciende durante focus sessions (`attention.only_during_focus`).
- `observe_only: true` (default) registra todo sin intervenir, **salvo** durante una focus
  session, que es un pedido explícito de alertas.
- Bloqueo (M6): las reglas con `action: block`/`warn` ocultan (soft) o cierran (strict) la app;
  durante una focus session se bloquean las apps `distracting`. Los browsers solo se ocultan.
- Modo strict: pausar, terminar la focus session o desactivar una regla pide esperar 60 s y
  escribir una frase (en el dashboard). Pausar la cámara nunca tiene fricción.
- Export: `http://127.0.0.1:8765/export.csv?days=7` (o `.json`), sin títulos de ventana.
- Sitios (M7): `python -m nublock sites setup` (una vez, pide tu contraseña de administrador)
  instala un helper que bloquea los dominios de `sites:` vía `/etc/hosts`, en todos los browsers.
  `sites status` muestra qué está bloqueado; `sites remove` lo desinstala y limpia /etc/hosts.

### Permisos de macOS (System Settings → Privacy & Security)

| Permiso | Para qué | A quién |
|---|---|---|
| Screen Recording | Leer títulos de ventana (`title_regex`) | Tu terminal (iTerm2/Terminal) |
| Camera | Attention monitor, `calibrate`, `attention-debug` | Tu terminal |
| Notifications | Alertas con el ícono de Nublock (`setup-notifications`) | Nublock |

## Datos

- SQLite: `~/Library/Application Support/nublock/nublock.db`
- Calibración (solo ángulos): `~/Library/Application Support/nublock/calibration.json`
- Logs: `~/Library/Logs/nublock/nublock.log`

## Desarrollo

```bash
pytest
ruff check .
ruff format .
```

Documentación para aprender: `docs/learning/M0.md` … `M5.md`. Decisiones: `docs/DECISIONS.md`.

## Licencia

MIT (ver `LICENSE`). La release incluye software de terceros con sus propias licencias: los
modelos de MediaPipe (Apache 2.0), CPython de python-build-standalone (PSF y otras) y las
dependencias de `pyproject.toml`.
