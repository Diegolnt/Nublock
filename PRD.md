# Nublock — Product Requirements Document (PRD)

| Campo | Valor |
|---|---|
| Producto | **Nublock** |
| Versión del documento | 0.1 (Draft) |
| Fecha | 2026-10-29 |
| Owner | (tu nombre) |
| Estado | v1 = app local, single-user (solo para mí) |

> **PRD (Product Requirements Document):** documento que define *qué* se construye, *para quién* y *por qué*, con requisitos medibles. No es un diseño técnico detallado, aunque este incluye una propuesta de arquitectura para que Claude Code pueda empezar.

---

## 0. Instrucciones para Claude Code

1. Lee este documento completo antes de escribir código.
2. **Antes de empezar, pregúntame:**
   - Sistema operativo: Windows, macOS o Linux (y si Linux, **X11** o **Wayland**).
   - Versión de Python instalada (`python --version`).
   - Si tengo webcam y si uso más de un monitor.
3. Implementa **por milestones** (sección 13), uno a la vez. Al terminar cada uno: corre los tests, muéstrame cómo probarlo manualmente y espera mi OK antes de seguir.
4. **Soy estudiante y estoy aprendiendo.** Cada vez que introduzcas una librería, clase o función nueva, explícala como documentación: qué hace, qué argumentos recibe, qué retorna. Usa los términos técnicos en inglés (nombre completo de las siglas).
5. **Reglas de privacidad inviolables** (ver sección 16):
   - Ningún frame de la cámara se escribe a disco, se loguea, se serializa ni sale de la RAM del proceso.
   - Cero network calls en v1 (excepto el dashboard en `127.0.0.1`).
6. Prefiere código simple y legible a abstracciones prematuras. Type hints en todo. Tests con `pytest`.

---

## 1. Resumen (Executive Summary)

Nublock es una aplicación de escritorio **local-first** que ayuda a una persona a recuperar el control de su día reduciendo distracciones. Combina dos fuentes de señal:

1. **Activity Tracking (pantalla):** detecta qué aplicación/ventana está activa, la clasifica en categorías de productividad, mide el tiempo en cada una y aplica reglas definidas por el usuario (límites diarios, horarios de foco, bloqueos).
2. **Attention Monitoring (cámara):** usando computer vision **procesada localmente**, estima si la persona mira la pantalla, mira hacia abajo (probable teléfono), mira a otro lado o no está. Si la distracción se prolonga, emite una **intervention** (notificación, sonido) para que vuelva al trabajo rápido.

El video **nunca se guarda**: solo se almacenan eventos derivados (ej. `LOOKING_AWAY` de 10:02:13 a 10:02:41).

---

## 2. Problema

- Las distracciones (redes sociales, video, juegos, notificaciones, teléfono) fragmentan la atención; volver a concentrarse después de cada interrupción cuesta tiempo.
- Los bloqueadores existentes solo ven la pantalla: **no detectan el teléfono**, que es la distracción más común y está fuera del computador.
- Las apps de tracking muestran estadísticas *después*; el problema necesita intervención **en el momento**.
- Herramientas en la nube con cámara generan desconfianza (privacidad) y riesgo legal.

---

## 3. Goals / Non-goals

### Goals (v1)
- **G1:** Saber con precisión en qué se fue mi tiempo cada día, por app y por categoría.
- **G2:** Definir reglas propias (límites, horarios de foco) y que la app las haga cumplir.
- **G3:** Detectar distracciones físicas (teléfono, mirar a otro lado, ausencia) y acortarlas con interventions.
- **G4:** Todo el procesamiento ocurre on-device; nada sale del computador.
- **G5:** Consumo bajo de recursos para poder dejarla corriendo todo el día.

### Non-goals (v1)
- No es una herramienta de vigilancia de empleados ni de terceros. Es **self-monitoring** (uno se monitorea a sí mismo). Esto es una decisión de producto y también reduce riesgo legal.
- No reconoce *quién* es la persona (no face recognition / identificación).
- No graba ni hace screenshots de la pantalla.
- No hay cuentas, cloud ni sync en v1.
- No soporta mobile en v1.

---

## 4. Usuario objetivo (User Persona)

**Primario (v1):** yo — estudiante universitario que trabaja/estudia en el computador, se distrae con redes, video y el teléfono, y quiere un sistema que lo ayude a cumplir sus propias reglas.

**Futuro:** estudiantes y knowledge workers que buscan productividad personal con fuerte garantía de privacidad.

### User Stories
- *Como usuario, quiero ver cuánto tiempo pasé hoy en apps distractoras, para darme cuenta de mis patrones.*
- *Como usuario, quiero ponerme un límite de 30 min diarios en redes sociales, y que al cumplirse la app me bloquee.*
- *Como usuario, quiero iniciar una focus session de 50 min durante la cual cualquier distracción me alerte.*
- *Como usuario, quiero que si tomo el teléfono más de unos segundos durante una focus session, suene un aviso.*
- *Como usuario, quiero marcar una alerta como "falsa alarma" para que el sistema mejore su calibración.*
- *Como usuario, quiero pausar la cámara con un clic, y saber siempre si está activa.*

---

## 5. Principios de producto

1. **Privacy by design:** el diseño asume que los datos de cámara son sensibles. Minimizar, procesar en memoria, descartar.
2. **Local-first:** funciona 100% offline.
3. **Intervenir, no castigar:** escalar de suave a fuerte; el objetivo es reducir la *duración* de la distracción.
4. **Reglas del usuario, no de la app:** el usuario define qué es distractor para él.
5. **Fricción intencional:** desactivar reglas en modo estricto debe costar algo (commitment device).
6. **Observar antes de intervenir:** la primera semana corre en *observe-only mode* para obtener un baseline.

---

## 6. Glosario (English terms)

| Término | Nombre completo / significado |
|---|---|
| PRD | Product Requirements Document |
| MVP | Minimum Viable Product — versión mínima que entrega valor |
| FR / NFR | Functional Requirement / Non-Functional Requirement |
| UI / UX | User Interface / User Experience |
| API | Application Programming Interface |
| CLI | Command-Line Interface |
| CPU / RAM | Central Processing Unit / Random Access Memory |
| FPS | Frames Per Second |
| ML | Machine Learning |
| CV | Computer Vision |
| OS | Operating System |
| PID | Process Identifier — número que el OS asigna a cada proceso |
| IPC | Inter-Process Communication |
| SQL | Structured Query Language |
| ORM | Object-Relational Mapping |
| YAML | YAML Ain't Markup Language — formato de configuración |
| JSON | JavaScript Object Notation |
| URL | Uniform Resource Locator |
| HTTP | HyperText Transfer Protocol |
| UTC | Coordinated Universal Time |
| ISO 8601 | Estándar de formato de fechas (`2026-10-29T15:19:00Z`) |
| AFK | Away From Keyboard |
| Daemon / background service | Proceso que corre en segundo plano sin ventana |
| System tray | Área de íconos junto al reloj del OS |
| Landmark | Punto clave detectado en la cara (ej. punta de la nariz) |
| Head pose | Orientación de la cabeza: **yaw** (izq/der), **pitch** (arriba/abajo), **roll** (inclinación lateral) |
| Blendshape | Coeficiente 0–1 que describe una expresión/movimiento facial (ej. `eyeLookDownLeft`) |
| Debounce | Ignorar cambios muy breves; un estado debe durar X segundos para contar |
| Hysteresis | Usar umbrales distintos para entrar y salir de un estado, para evitar "parpadeo" entre estados |
| State machine | Modelo con estados finitos y transiciones definidas |
| Event bus | Canal por donde módulos publican y consumen eventos sin conocerse entre sí |
| Dependency injection | Pasar las dependencias de un objeto desde afuera (facilita tests con fakes) |
| Commitment device | Mecanismo que uno se impone para cumplir una meta futura |
| False positive | Alerta que se dispara cuando no debía |

---

## 7. Functional Requirements (FR)

Formato: **ID — descripción.** *Acceptance criteria* (criterios de aceptación) = cómo verificamos que está listo.

### 7.1 Activity Tracking (pantalla)

- **FR-01 — Detectar la ventana activa.** Cada `poll_interval_seconds` (default 1 s) obtener: `process_name`, `pid`, `app_name`, `window_title`.
  - *AC:* al cambiar de app, el cambio queda registrado en ≤ 2 s.
- **FR-02 — Agrupar en sesiones.** Mientras la ventana activa no cambie, extender la misma `activity_session`; al cambiar, cerrarla y abrir otra.
  - *AC:* no se crea una fila por segundo; se crea una fila por cada periodo continuo.
- **FR-03 — Idle detection.** Si no hay input de teclado/mouse por `idle_threshold_seconds` (default 120 s), marcar la sesión como idle. Combinado con la cámara: idle + sin cara = `AFK`.
  - *AC:* ver un video sin tocar el mouse **no** se marca AFK si la cámara detecta una cara mirando la pantalla.
- **FR-04 — Registro local.** Persistir sesiones en SQLite (sección 11).
- **FR-05 — Opción de no guardar títulos de ventana** (`store_window_titles: false`), porque pueden contener info privada (asuntos de correos, nombres de archivos). En ese caso solo se guarda la categoría.

### 7.2 Classification (categorías)

- **FR-10 — Categorías de 2 niveles:** `productivity` ∈ {`productive`, `neutral`, `distracting`} + `subcategory` libre (ej. `dev`, `study`, `social`, `video`, `games`, `messaging`).
- **FR-11 — Reglas de clasificación** definidas en `config.yaml`, evaluadas en orden; gana la primera que coincide. Matchers soportados:
  - `process`: nombre exacto del proceso (case-insensitive).
  - `title_regex`: regular expression sobre el título de la ventana.
  - `domain` (Milestone 7): dominio de la URL activa del browser.
- **FR-12 — Browsers.** Un mismo proceso (`chrome.exe`) puede ser productivo (docs) o distractor (YouTube). En v1 se resuelve con `title_regex` sobre el título de la pestaña (ej. `" - YouTube"`). En M7 se agrega una browser extension que reporta la URL real.
- **FR-13 — Uncategorized.** Apps sin regla quedan como `neutral/uncategorized` y aparecen en el dashboard para que el usuario las clasifique con un clic (se guarda como override).
  - *AC:* tras clasificar una app desde el dashboard, sus nuevas sesiones usan la nueva categoría.

### 7.3 Timers & Rules (reglas del usuario)

- **FR-20 — Timers:** acumulados por día para cada app, subcategoría y categoría. Visibles en tiempo real en el tray menu.
- **FR-21 — Tipos de regla:**
  | `type` | Qué hace |
  |---|---|
  | `daily_limit` | Máximo de minutos al día para un target (app/subcategoría/categoría). |
  | `schedule` | Ventana horaria (ej. lun–vie 09:00–13:00) donde un target está prohibido. |
  | `focus_session` | Sesión manual tipo Pomodoro (ej. 50 min) con interventions de cámara activas y distractores bloqueados. |
- **FR-22 — Acciones al violar una regla:** `notify` → `warn` (aviso + `grace_seconds` para salir) → `block` (ver 7.6).
- **FR-23 — Modos:** `soft` (se puede desactivar libremente) y `strict` (desactivar requiere fricción: esperar 60 s y escribir una frase de confirmación).
- **FR-24 — Observe-only mode:** registra todo pero no interviene. Activo por defecto la primera semana para medir baseline.

### 7.4 Attention Monitor (cámara)

- **FR-30 — Captura local** desde la webcam a `process_fps` (default 8) y resolución reducida (default 640 px de ancho). Los frames se procesan y se descartan inmediatamente.
- **FR-31 — Face landmarks + head pose:** por frame obtener presencia de cara, yaw/pitch/roll y blendshapes de los ojos.
- **FR-32 — Calibración:** al primer uso (y cuando el usuario quiera), mirar el centro de la pantalla y sus esquinas (y el segundo monitor si existe) para definir la **zona "mirando la pantalla"** como rangos de yaw/pitch relativos al baseline.
  - *AC:* tras calibrar, mirar cualquier zona del monitor se clasifica `FOCUSED` en ≥ 90% de los frames.
- **FR-33 — Phone detection:** detector de objetos (clase COCO `cell phone`) corriendo a baja frecuencia (1–2 FPS) **solo** cuando el estado es `LOOKING_DOWN`, para ahorrar CPU.
- **FR-34 — Attention states** (state machine con debounce e hysteresis):
  | State | Condición |
  |---|---|
  | `FOCUSED` | Cara presente y head pose/gaze dentro de la zona calibrada |
  | `LOOKING_AWAY` | Cara presente, yaw fuera de zona (izq/der) |
  | `LOOKING_DOWN` | Cara presente, pitch bajo la zona (puede ser teclado, cuaderno o teléfono) |
  | `PHONE` | Phone detection positivo, o `LOOKING_DOWN` sostenido + teléfono visible |
  | `ABSENT` | Sin cara detectada |
  | `PAUSED` | Usuario pausó la cámara |
  | `CAMERA_UNAVAILABLE` | Cámara ocupada (ej. en una videollamada) o sin permiso |
  - Un estado debe mantenerse `state_debounce_seconds` (default 2 s) para considerarse.
  - *AC:* parpadear o girar la cabeza 1 s **no** genera transición.
- **FR-35 — Debug view (opcional, opt-in):** ventana que muestra la cámara con landmarks y estado actual, solo en vivo, sin grabación. Útil para desarrollar y calibrar.
- **FR-36 — Liberar la cámara** si otra app la necesita (videollamadas) y reintentar cada N segundos.

### 7.5 Interventions (alertas)

- **FR-40 — Grace periods por estado** antes de intervenir (defaults): `LOOKING_AWAY` 10 s, `LOOKING_DOWN` 15 s, `PHONE` 3 s, `ABSENT` sin alerta (se registra como pausa).
- **FR-41 — Escalation:**
  1. Nivel 1: notificación nativa del OS silenciosa.
  2. Nivel 2 (+10 s): notificación con sonido.
  3. Nivel 3 (+20 s, solo en focus session strict): overlay a pantalla completa semitransparente con "Vuelve: te quedan X min de sesión".
- **FR-42 — Contexto:** no intervenir si la app activa está en una lista `attention_exempt` (ej. reuniones, lectura en papel) o si el usuario está en modo `break`.
- **FR-43 — Feedback:** la notificación tiene un botón "Falsa alarma". Se registra y se usa para recalibrar umbrales.
- **FR-44 — Métrica de refocus:** medir segundos entre la intervention y el regreso a `FOCUSED` (`refocus_seconds`).
- **FR-45 — Quiet hours / cooldown:** máximo una intervention cada `cooldown_seconds` (default 30 s) para no saturar.

### 7.6 Blocking

- **FR-50 — Bloquear app:** al violar una regla con acción `block`, minimizar la ventana (soft) o terminar el proceso (strict) y mostrar notificación con el motivo.
- **FR-51 — Bloquear sitios** (M7): vía browser extension, redirigir la pestaña a una página local de Nublock.
- **FR-52 — Bloquear notificaciones del OS** (futuro): activar Do Not Disturb / Focus Assist del OS durante focus sessions, si el OS lo permite vía API.

### 7.7 Dashboard & Reports

- **FR-60 — CLI report** (M1): `nublock report today` imprime tiempo por categoría y top apps.
- **FR-61 — Dashboard local** en `http://127.0.0.1:<port>`: hoy / semana; tiempo por categoría; timeline del día; número de distracciones físicas; refocus time promedio; lista de apps sin clasificar.
- **FR-62 — Export** de datos agregados a CSV/JSON.

### 7.8 Control & Privacy UI

- **FR-70 — System tray icon** con color por estado (verde focus, amarillo distraído, gris pausado) y menú: iniciar focus session, pausar cámara, pausar todo 15 min, abrir dashboard, salir.
- **FR-71 — Indicador de cámara** siempre visible en el tray cuando está activa.
- **FR-72 — Borrar datos:** botón para borrar todo el historial; retención automática de `data_retention_days`.
- **FR-73 — Autostart** al iniciar sesión en el OS (opcional, M8).

---

## 8. Non-Functional Requirements (NFR)

| ID | Requisito | Target |
|---|---|---|
| NFR-01 | CPU promedio con cámara activa | < 10% en un laptop moderno |
| NFR-02 | CPU sin cámara | < 2% |
| NFR-03 | RAM | < 400 MB |
| NFR-04 | Latencia de detección de estado (cámara) | < 1 s + debounce |
| NFR-05 | Privacidad | 0 frames en disco; 0 requests a internet |
| NFR-06 | Robustez | Si falla la cámara, el tracking de pantalla sigue funcionando |
| NFR-07 | Portabilidad | Código del OS aislado en adapters (`platform/`) |
| NFR-08 | Testability | Lógica (classifier, rules, state machine) testeable sin cámara ni OS real |
| NFR-09 | Observability | Logs con el módulo `logging` a archivo rotativo; nunca loguear frames ni títulos si `store_window_titles=false` |

---

## 9. Arquitectura

Un solo proceso Python con varios **threads** que se comunican por un **event bus** (`queue.Queue`).

```
┌──────────────────────────── Nublock process ────────────────────────────┐
│                                                                          │
│  ┌──────────────────┐   ActivityEvent   ┌──────────────┐                 │
│  │ Activity Tracker │ ───────────────▶ │              │   RuleViolation  │
│  │ (thread, 1 Hz)   │                   │              │ ───────────┐     │
│  │  └ platform/     │                   │  Event Bus   │            ▼     │
│  │    adapter (OS)  │                   │ (queue.Queue)│   ┌──────────────┐│
│  └──────────────────┘                   │              │──▶│ Rules Engine ││
│                                         │              │   └──────────────┘│
│  ┌──────────────────┐  AttentionEvent   │              │   ┌──────────────┐│
│  │ Attention Monitor│ ───────────────▶ │              │──▶│ Intervention ││
│  │ (thread, ~8 FPS) │                   │              │   │   Manager    ││
│  │  ├ camera        │                   └──────┬───────┘   └──────┬───────┘│
│  │  ├ face landmarks│                          │                  │        │
│  │  ├ phone detector│                          ▼                  ▼        │
│  │  └ state machine │                   ┌──────────────┐   notifications,  │
│  └──────────────────┘                   │   Storage    │   sound, block    │
│      frames: solo RAM,                  │  (SQLite)    │                   │
│      nunca salen del thread             └──────┬───────┘                   │
│                                                │                           │
│  ┌──────────────────┐                   ┌──────▼───────┐                   │
│  │ Tray UI (main    │                   │ Dashboard    │◀── browser en     │
│  │ thread)          │                   │ (FastAPI,    │    127.0.0.1      │
│  └──────────────────┘                   │  thread)     │                   │
└──────────────────────────────────────────────────────────────────────────┘
```

**Decisiones clave:**
- **Threads en vez de procesos:** más simple de aprender. OpenCV y MediaPipe ejecutan su trabajo pesado en C++ y liberan el GIL (Global Interpreter Lock), así que los threads no se bloquean entre sí de forma importante.
- **Tray en el main thread:** en macOS la UI debe correr en el main thread.
- **Platform adapters:** una interfaz común `ActiveWindowProvider` con implementaciones `windows.py`, `macos.py`, `linux_x11.py`. El resto del código no sabe en qué OS corre.
- **Fakes para tests:** `FakeWindowProvider` y `FakeCamera` inyectados por dependency injection.

### Estructura de carpetas propuesta

```
nublock/
├── PRD.md
├── pyproject.toml
├── config/
│   └── config.example.yaml
├── src/nublock/
│   ├── __main__.py          # entry point: python -m nublock
│   ├── app.py               # arma los módulos y arranca threads
│   ├── config.py            # carga y valida config.yaml (pydantic)
│   ├── events.py            # dataclasses de eventos + event bus
│   ├── tracker/
│   │   ├── tracker.py
│   │   └── platform/        # windows.py, macos.py, linux_x11.py, fake.py
│   ├── classifier/
│   ├── rules/
│   ├── attention/
│   │   ├── camera.py
│   │   ├── face.py          # landmarks + head pose
│   │   ├── phone.py         # object detection
│   │   ├── calibration.py
│   │   └── state_machine.py
│   ├── interventions/
│   ├── storage/             # schema.sql, repository.py
│   ├── ui/                  # tray.py
│   └── dashboard/           # FastAPI app + templates
├── models/                  # archivos .task de MediaPipe (descargados, no en git)
└── tests/
```

---

## 10. Tech Stack (con documentación)

> Claude Code: verifica versiones actuales y que las librerías sigan mantenidas antes de fijar dependencias en `pyproject.toml`.

| Componente | Tecnología | Por qué |
|---|---|---|
| Lenguaje | **Python 3.11+** | Ecosistema líder en CV/ML, ideal para aprender |
| Gestión de entorno | `venv` + `pip` (o `uv`) | Aislar dependencias del proyecto |
| Lint/format | `ruff` | Linter + formatter rápido |
| Tests | `pytest` | Estándar de facto en Python |
| Config | `PyYAML` + `pydantic` | Leer YAML y validarlo con tipos |
| Procesos | `psutil` | Info de procesos cross-platform (nombre, PID, terminar) |
| Ventana activa (Windows) | `pywin32` | Acceso a la Win32 API |
| Ventana activa (macOS) | `pyobjc` (AppKit, Quartz) | Acceso a APIs nativas de macOS |
| Ventana activa (Linux X11) | `python-xlib` | Protocolo X11 |
| Cámara | `opencv-python` (OpenCV) | Captura de video y procesamiento de imagen |
| Face landmarks / head pose | **MediaPipe Face Landmarker** | Modelo on-device, rápido en CPU, entrega landmarks, blendshapes y matriz de transformación |
| Phone detection | **MediaPipe Object Detector** (EfficientDet-Lite, entrenado en COCO) | Detecta la clase `cell phone`, licencia Apache 2.0 |
| Storage | `sqlite3` (stdlib) | Base de datos en un archivo, sin servidor; aprender SQL directo |
| Rutas de datos | `platformdirs` | Carpeta correcta de datos por OS |
| Notificaciones | `desktop-notifier` | Notificaciones nativas cross-platform con botones |
| Tray | `pystray` + `Pillow` | Ícono en system tray |
| Dashboard | `FastAPI` + `uvicorn` + Jinja2 + Chart.js | API local + páginas HTML simples |
| Packaging (M8) | `PyInstaller` o `Briefcase` | Generar ejecutable instalable |

### 10.1 Ventana activa por OS (referencia)

**Windows** (`pywin32`):
- `win32gui.GetForegroundWindow()` → retorna `hwnd` (window handle, un entero que identifica la ventana en primer plano).
- `win32gui.GetWindowText(hwnd)` → título de la ventana (`str`).
- `win32process.GetWindowThreadProcessId(hwnd)` → tupla `(thread_id, pid)`.
- Luego `psutil.Process(pid).name()` → nombre del ejecutable (ej. `"chrome.exe"`).
- Idle: `win32api.GetLastInputInfo()` → tick (ms) del último input; compararlo con `win32api.GetTickCount()`.

**macOS** (`pyobjc`):
- `NSWorkspace.sharedWorkspace().frontmostApplication()` → app activa (`.localizedName()`, `.processIdentifier()`).
- Título de ventana: `Quartz.CGWindowListCopyWindowInfo(...)`; requiere permiso **Screen Recording** en System Settings.
- Idle: `Quartz.CGEventSourceSecondsSinceLastEventType(...)`.

**Linux:**
- X11: leer la propiedad `_NET_ACTIVE_WINDOW` con `python-xlib`, luego `_NET_WM_NAME` y `_NET_WM_PID`.
- Wayland: por diseño de seguridad no permite a apps ver otras ventanas; requiere extensiones del compositor (ej. GNOME). **Riesgo** (sección 15).

### 10.2 Cámara con OpenCV

```python
import cv2

cap = cv2.VideoCapture(0)              # index: número de cámara (0 = la default)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640) # propId, value: pedir resolución menor
ok, frame = cap.read()                 # ok: bool; frame: numpy array BGR (alto, ancho, 3)
cap.release()                          # liberar la cámara para otras apps
```
- `frame` es un `numpy.ndarray`. OpenCV usa orden de colores **BGR**; MediaPipe espera **RGB** → `cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)`.
- **Nunca** llamar `cv2.imwrite` ni guardar `frame` fuera de la función que lo procesa.

### 10.3 MediaPipe Face Landmarker

```python
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

options = vision.FaceLandmarkerOptions(
    base_options=mp_python.BaseOptions(model_asset_path="models/face_landmarker.task"),
    running_mode=vision.RunningMode.VIDEO,
    num_faces=1,
    output_face_blendshapes=True,
    output_facial_transformation_matrixes=True,
    min_face_detection_confidence=0.5,
    min_face_presence_confidence=0.5,
    min_tracking_confidence=0.5,
)
landmarker = vision.FaceLandmarker.create_from_options(options)

mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
result = landmarker.detect_for_video(mp_image, timestamp_ms)
```

| Argumento | Qué hace |
|---|---|
| `base_options.model_asset_path` | Ruta al archivo del modelo `.task` (se descarga del sitio de MediaPipe) |
| `running_mode` | `IMAGE` (fotos sueltas), `VIDEO` (frames secuenciales, usa tracking entre frames), `LIVE_STREAM` (asíncrono con callback). Usar `VIDEO` |
| `num_faces` | Máximo de caras a detectar. 1 = solo el usuario |
| `output_face_blendshapes` | Si `True`, retorna 52 coeficientes (ej. `eyeLookDownLeft`, `eyeLookOutRight`, `eyeBlinkLeft`) útiles para estimar hacia dónde miran los ojos |
| `output_facial_transformation_matrixes` | Si `True`, retorna una matriz 4×4 con la rotación/traslación de la cabeza → de ahí se calculan yaw/pitch/roll |
| `min_face_detection_confidence` | Score mínimo (0–1) para considerar que se detectó una cara |
| `min_face_presence_confidence` | Score mínimo para mantener la cara como presente entre frames |
| `min_tracking_confidence` | Score mínimo para confiar en el tracking; si baja, vuelve a detectar desde cero |

- `detect_for_video(image, timestamp_ms)`: `timestamp_ms` debe ser creciente (usar `time.monotonic()` × 1000).
- `result.face_landmarks`: lista (una por cara) de 478 landmarks normalizados (x, y, z).
- `result.facial_transformation_matrixes[0]`: matriz 4×4; los ángulos de Euler se obtienen de su submatriz 3×3 de rotación (ej. con `cv2.RQDecomp3x3` o `scipy.spatial.transform.Rotation`).

**Estimación de atención (v1):** head pose (yaw/pitch) como señal principal + blendshapes de mirada como señal secundaria (ej. cabeza al frente pero ojos muy abajo → `LOOKING_DOWN`).

---

## 11. Data Model (SQLite)

Todas las fechas en ISO 8601 UTC (`TEXT`). La conversión a hora local (America/Santiago) se hace al mostrar.

```sql
CREATE TABLE activity_sessions (
    id            INTEGER PRIMARY KEY,
    started_at    TEXT    NOT NULL,
    ended_at      TEXT,                       -- NULL mientras la sesión está abierta
    process_name  TEXT    NOT NULL,
    app_name      TEXT,
    window_title  TEXT,                       -- NULL si store_window_titles = false
    url_domain    TEXT,                       -- M7 (browser extension)
    productivity  TEXT    NOT NULL CHECK (productivity IN ('productive','neutral','distracting')),
    subcategory   TEXT,
    is_idle       INTEGER NOT NULL DEFAULT 0  -- SQLite no tiene BOOLEAN: 0/1
);

CREATE TABLE attention_events (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    state       TEXT NOT NULL CHECK (state IN
                ('FOCUSED','LOOKING_AWAY','LOOKING_DOWN','PHONE','ABSENT','PAUSED','CAMERA_UNAVAILABLE')),
    confidence  REAL                          -- 0..1, promedio durante el evento
);

CREATE TABLE interventions (
    id               INTEGER PRIMARY KEY,
    at               TEXT NOT NULL,
    trigger          TEXT NOT NULL,           -- ej. 'attention:PHONE', 'rule:social-daily-limit'
    level            INTEGER NOT NULL,        -- 1, 2, 3 (escalation)
    rule_id          TEXT,
    user_feedback    TEXT,                    -- NULL | 'false_alarm' | 'dismissed'
    refocus_seconds  REAL                     -- tiempo hasta volver a FOCUSED
);

CREATE TABLE focus_sessions (
    id               INTEGER PRIMARY KEY,
    started_at       TEXT NOT NULL,
    ended_at         TEXT,
    planned_minutes  INTEGER NOT NULL,
    mode             TEXT NOT NULL CHECK (mode IN ('soft','strict')),
    completed        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE classification_overrides (
    id            INTEGER PRIMARY KEY,
    matcher_type  TEXT NOT NULL CHECK (matcher_type IN ('process','title_regex','domain')),
    pattern       TEXT NOT NULL,
    productivity  TEXT NOT NULL,
    subcategory   TEXT,
    created_at    TEXT NOT NULL
);

CREATE INDEX idx_activity_started ON activity_sessions(started_at);
CREATE INDEX idx_attention_started ON attention_events(started_at);
```

**Lo que NO existe en el schema a propósito:** imágenes, landmarks crudos, embeddings faciales. Solo eventos agregados.

---

## 12. Configuración (`config.yaml`)

```yaml
general:
  poll_interval_seconds: 1
  idle_threshold_seconds: 120
  data_retention_days: 90
  store_window_titles: true
  observe_only: true            # primera semana: true

attention:
  enabled: true
  camera_index: 0
  process_fps: 8
  frame_width: 640
  state_debounce_seconds: 2
  yaw_margin_deg: 8             # margen extra sobre la zona calibrada
  pitch_margin_deg: 6
  phone_detection:
    enabled: true
    fps: 1
    min_score: 0.5
  attention_exempt:             # apps donde no se alerta por cámara
    - { process: "zoom.exe" }

interventions:
  grace_seconds:
    LOOKING_AWAY: 10
    LOOKING_DOWN: 15
    PHONE: 3
  escalation_seconds: [0, 10, 20]   # cuándo sube a nivel 1, 2, 3
  cooldown_seconds: 30
  sound: true

classification_rules:           # orden importa: gana la primera que coincide
  - match: { process: "code.exe" }
    productivity: productive
    subcategory: dev
  - match: { title_regex: "(?i) - YouTube" }
    productivity: distracting
    subcategory: video
  - match: { title_regex: "(?i)(instagram|tiktok|twitter|x\\.com|reddit)" }
    productivity: distracting
    subcategory: social
  - match: { process: "steam.exe" }
    productivity: distracting
    subcategory: games

rules:
  - id: social-daily-limit
    type: daily_limit
    target: { subcategory: social }
    limit_minutes: 30
    action: block
    mode: soft
  - id: morning-focus
    type: schedule
    days: [mon, tue, wed, thu, fri]
    start: "09:00"
    end: "13:00"
    target: { productivity: distracting }
    action: warn
    mode: strict

focus_session:
  default_minutes: 50
  break_minutes: 10
  block_distracting: true
```

| Campo | Tipo | Descripción |
|---|---|---|
| `general.poll_interval_seconds` | int | Cada cuántos segundos se consulta la ventana activa |
| `general.idle_threshold_seconds` | int | Segundos sin input para considerar idle |
| `general.data_retention_days` | int | Días antes de borrar historial automáticamente |
| `general.store_window_titles` | bool | Guardar o no los títulos de ventana |
| `general.observe_only` | bool | Si `true`, registra pero no interviene |
| `attention.camera_index` | int | Índice de cámara para `cv2.VideoCapture` |
| `attention.process_fps` | int | Frames procesados por segundo (más = más CPU) |
| `attention.frame_width` | int | Ancho al que se reduce el frame antes de procesar |
| `attention.state_debounce_seconds` | float | Tiempo mínimo que un estado debe durar |
| `attention.yaw_margin_deg` / `pitch_margin_deg` | float | Tolerancia en grados alrededor de la zona calibrada |
| `attention.phone_detection.min_score` | float 0–1 | Confianza mínima para aceptar un "cell phone" |
| `attention.attention_exempt` | list | Matchers de apps donde no se alerta por cámara |
| `interventions.grace_seconds` | map | Segundos tolerados por estado antes de alertar |
| `interventions.escalation_seconds` | list[int] | Segundos desde el inicio de la alerta para cada nivel |
| `interventions.cooldown_seconds` | int | Mínimo entre dos interventions |
| `classification_rules[].match` | map | `process`, `title_regex` o `domain` |
| `rules[].type` | enum | `daily_limit`, `schedule` |
| `rules[].target` | map | `process`, `subcategory` o `productivity` al que aplica |
| `rules[].action` | enum | `notify`, `warn`, `block` |
| `rules[].mode` | enum | `soft` o `strict` |

---

## 13. Milestones / Roadmap

Cada milestone tiene un **DoD (Definition of Done)**.

| # | Milestone | Contenido | DoD |
|---|---|---|---|
| **M0** | Setup | Repo, `pyproject.toml`, venv, `ruff`, `pytest`, `logging`, carga de config con pydantic | `pytest` pasa; `python -m nublock --help` funciona |
| **M1** | Activity Tracker | Platform adapter para mi OS, sesiones, idle, SQLite, `nublock report today` | Usar el PC 1 hora y el reporte cuadra con lo que hice |
| **M2** | Classification + Rules | Matchers, timers, `daily_limit` y `schedule` con acción `notify`, observe-only | Tests unitarios del classifier y rules engine con fakes; notificación al pasar un límite |
| **M3** | Attention Monitor | Cámara, Face Landmarker, head pose, calibración, state machine, debug view | En debug view los estados cambian correctamente al mirar pantalla/izq/abajo/salir |
| **M4** | Phone + Interventions | Object detector, grace periods, escalation, sonido, botón "falsa alarma", focus sessions | Tomar el teléfono en focus session → alerta en < 5 s |
| **M5** | Tray + Dashboard | `pystray`, FastAPI, gráficos, clasificar apps desde UI | Dashboard muestra el día; tray refleja el estado |
| **M6** | Blocking | Minimizar/terminar apps, strict mode con fricción | Superar `social-daily-limit` cierra/minimiza la app |
| **M7** | Browser Extension | WebExtension (Chrome/Firefox) que envía la URL activa al daemon por `127.0.0.1` | Clasificación por `domain`; bloqueo de sitios |
| **M8** | Packaging | Ejecutable, autostart, instalador, onboarding de permisos | Instalar en un PC limpio y funciona sin terminal |

**MVP = M0–M4.** Ahí ya cumple el objetivo central para uso personal.

---

## 14. Success Metrics

- **Distracting time / día:** −30% vs baseline (semana observe-only) después de 2 semanas.
- **Refocus time** (mediana `refocus_seconds`): < 15 s.
- **Duración media de distracción física** (`LOOKING_AWAY`/`PHONE`): tendencia a la baja semana a semana.
- **False positive rate** (alertas marcadas "falsa alarma" / total): < 10%.
- **Focus sessions completadas / iniciadas:** > 70%.
- **Recursos:** cumplir NFR-01 a NFR-03.

---

## 15. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Mirar el teclado o un cuaderno se confunde con mirar el teléfono | False positives molestos | `LOOKING_DOWN` tiene grace más largo; `PHONE` solo con detector; calibración de zona "cuaderno"; botón falsa alarma |
| Mala iluminación / lentes / ángulo de cámara | Detección inestable | Debounce + hysteresis; mostrar calidad de detección en debug view; estado `UNKNOWN` en vez de alertar |
| La cámara está en uso por una videollamada | Monitor caído | Estado `CAMERA_UNAVAILABLE`, sin alertas, reintentos |
| Wayland (Linux) no expone la ventana activa | Tracking no funciona | Recomendar sesión X11 en v1; investigar extensión de GNOME después |
| macOS requiere permisos (Screen Recording, Camera) | Onboarding confuso | Detectar permisos faltantes y explicar cómo darlos |
| Consumo de CPU alto | App molesta, se desinstala | FPS bajo, resolución reducida, phone detector condicional, pausar cámara si no hay focus session (opcional) |
| El usuario desactiva todo en un momento de debilidad | Producto inútil | Strict mode con fricción; estadística de "veces que desactivaste" |
| Licencias de dependencias | Problema al comercializar | Preferir Apache/MIT/BSD; **evitar** modelos AGPL (ej. Ultralytics YOLO) sin licencia comercial |

---

## 16. Privacidad y consideraciones legales

> Esto no es asesoría legal. Antes de distribuir Nublock a otras personas, consultar con un abogado.

**Garantías técnicas (v1):**
1. Los frames viven solo en una variable local dentro del thread de cámara; se sobreescriben en cada iteración.
2. Prohibido: `cv2.imwrite`, guardar arrays de imagen, loguear frames, pickle de frames, enviarlos por red.
3. Se persisten **solo** estados agregados con timestamps (tabla `attention_events`).
4. No hay face recognition: no se calculan ni guardan embeddings que identifiquen a la persona.
5. Cero network calls; el dashboard escucha solo en `127.0.0.1` (no en `0.0.0.0`).
6. La cámara se puede pausar en cualquier momento y su estado es siempre visible.
7. **Test de privacidad:** un test que corre el Attention Monitor con `FakeCamera` y verifica que no se crean archivos de imagen en el data dir.

**Al productizar:**
- Política de privacidad clara + consentimiento explícito antes de activar la cámara.
- Chile: revisar la Ley 19.628 y la nueva Ley 21.719 de protección de datos personales (datos sensibles/biométricos, principio de minimización). UE: GDPR. Que el procesamiento sea local y sin identificación reduce mucho el riesgo, pero hay que confirmarlo.
- Mantener el Non-goal de no ser herramienta de monitoreo de terceros (empleadores, etc.).

---

## 17. Open Questions

1. ¿Qué OS uso? (define el primer platform adapter)
2. ¿Tengo uno o más monitores? (afecta la calibración)
3. ¿Las alertas de cámara deben estar activas siempre o solo durante focus sessions? (propuesta: solo en focus sessions por defecto, configurable)
4. ¿Qué sonido usar para las alertas? ¿Uno propio o el del OS?
5. ¿Strict mode debe sobrevivir a reiniciar el PC / cerrar la app?

---

## 18. Futuro: de app local a producto

Importante: **una web app hosteada no puede ver las otras apps del computador ni usar la cámara en segundo plano.** Por eso Nublock siempre necesitará un **desktop agent** instalado localmente. "Hostear" significa agregar alrededor de ese agente:

- **Landing page + descargas** (sitio estático).
- **Cuentas y sync opcional (opt-in)** de *estadísticas agregadas* (nunca video) para ver el dashboard en varios dispositivos → backend (ej. FastAPI + PostgreSQL) en la nube.
- **Mobile companion** para bloquear apps del teléfono durante focus sessions (las APIs de Screen Time en iOS / Digital Wellbeing en Android tienen restricciones; investigar).
- **Auto-update** del agente.
- **Clasificación asistida por ML local** de apps/títulos desconocidos.
- **Accountability:** compartir resumen semanal con un amigo (opt-in).
- **Modelo de negocio:** freemium (tracking gratis, cámara y strict mode en plan pago) — a validar.
