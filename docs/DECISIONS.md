# Decisiones de implementación (M0–M8)

Este archivo registra lo que el PRD dejaba ambiguo y cómo se resolvió. Regla usada: ante la duda,
**la opción más simple**, anotada aquí. Las instrucciones de la sección 0 del PRD ("pregúntame y
espera mi OK") fueron reemplazadas por el goal: se implementó M0, M1 y M2 de corrido.

## Contexto (respuestas a las Open Questions de la sección 0 / 17)

| Pregunta | Respuesta | Efecto |
|---|---|---|
| OS | macOS (26.5) | Solo se implementó el adapter `tracker/platform/macos.py` |
| Python | 3.11.7 (python.org, `/Library/Frameworks/...`) | `requires-python = ">=3.11"` |
| Monitores | 2 | No afecta M0–M2 (importa en la calibración de M3) |
| Webcam | no se preguntó | No aplica: M3+ está fuera de alcance |

## M0 — Setup

1. **`venv` + `pip`**, no `uv` (no está instalado). `pip install -e ".[dev]"`.
2. **Build backend `hatchling`** con *src layout* (`src/nublock`). Detecta el paquete solo e incluye
   `schema.sql` sin configuración extra.
3. **Dependencias de desarrollo** (`pytest`, `ruff`) como *optional dependency* `dev`, no mezcladas
   con las de runtime.
4. **Versiones**: cotas mínimas (`>=`) y no pins exactos. Versiones resueltas el 2026-10-29:
   PyYAML 6.0.3, pydantic 2.14.2, psutil 7.2.2, platformdirs 4.14.0, pyobjc 12.2.2,
   pytest 9.2.0, ruff 0.17.3, hatchling 1.33.0.
5. **pyobjc solo en macOS** vía *environment marker* `; sys_platform == 'darwin'`. `pywin32` y
   `python-xlib` no se declaran porque no hay adapter de Windows/Linux todavía.
6. **ruff** con `ANN` activado: obliga a poner type hints en todas las funciones (requisito del PRD).
   `ANN401` (prohibir `Any`) desactivado porque los validators de pydantic reciben `Any`.
7. **ruff excluye `*.md`**. Incidente: `ruff format .` también formatea bloques ```` ```python ````
   dentro de Markdown y re-alineó 4 comentarios del ejemplo de OpenCV en `PRD.md` (sección 10.2).
   Se restauraron esas 4 líneas al original (el archivo volvió a sus 39125 bytes y su fecha de
   modificación) y se agregó la exclusión para que no vuelva a pasar.
8. **CLI con `argparse`** (stdlib) en vez de click/typer: cero dependencias extra.
   Subcomandos: `run [--duration S]`, `report [today]`, `config` (este último no está en el PRD;
   valida la config y muestra rutas, útil para M0). `--duration` existe para poder probar el
   tracker real un tiempo fijo.
9. **Búsqueda de config**: `--config PATH` → `~/Library/Application Support/nublock/config.yaml`
   (si existe) → defaults del código. Los defaults no traen reglas: todo queda
   `neutral/uncategorized` hasta que crees tu `config.yaml`.
10. **Validación estricta**: keys desconocidas son error (`extra="forbid"`), para detectar typos.
    Las secciones de milestones futuros (`attention`, `interventions`, `focus_session`) se aceptan
    como `dict` sin validar todavía.
11. **Horas entre comillas**: en YAML 1.1 `13:00` sin comillas se lee como el entero 780 (base 60).
    El validador lo rechaza con un mensaje que pide comillas (`"13:00"`).
12. **`config/config.example.yaml`** usa nombres de proceso de macOS (`Code`, `iTerm2`,
    `Terminal`, `Discord`, `steam_osx`) en vez de los `.exe` del PRD. Se agregó un
    `README.md` breve y `pyproject.toml` apunta a él.
13. **Rutas** con `platformdirs`: DB en `~/Library/Application Support/nublock/nublock.db`, logs en
    `~/Library/Logs/nublock/nublock.log` (rotativo, 1 MB × 3 backups).
14. **Se hizo `git init`** (con `.gitignore`), sin commits: el PRD pide "Repo" en M0.

## M1 — Activity Tracker

15. **Ventana activa en macOS**: `NSWorkspace.frontmostApplication()` para la app (+ PID) y
    `CGWindowListCopyWindowInfo` para el título (primera ventana de *layer* 0 de ese PID).
    `process_name` = nombre del ejecutable vía `psutil.Process(pid).name()`; `app_name` =
    `localizedName()`.
16. **(Reemplazada en M5, ver #40)** **Todo corre en el main thread (sin threads ni event bus en M1–M2).** Se verificó que
    `frontmostApplication()` llamado desde un thread secundario queda congelado (en la prueba
    devolvió "Finder" 4 veces mientras se alternaba Finder/iTerm), incluso bombeando el run loop
    de ese thread. Desde el main thread, bombeando `NSRunLoop` ~10 ms por tick, se actualiza bien.
    El event bus con `queue.Queue` del PRD se agrega en M3 (cuando aparezca el thread de cámara);
    en M5 el tray también necesita el main thread, así que ahí habrá que reorganizar (el run loop
    de la UI mantendrá NSWorkspace actualizado).
17. **Sin permiso Screen Recording** los títulos son `None`: el tracker sigue funcionando, se
    loguea un warning una vez y las reglas `title_regex` simplemente no coinciden.
    `CGPreflightScreenCaptureAccess()` solo consulta el permiso, no abre el diálogo.
18. **Qué define una sesión**: se extiende mientras no cambie lo que se guardaría en la fila:
    `(process_name, app_name, window_title guardado, productivity, subcategory, is_idle)`. El PID
    no es parte de la key (no está en el schema). Con `store_window_titles: false`, cambios de
    título que no cambian la categoría no crean filas nuevas.
19. **Heartbeat de `ended_at` cada 10 s** mientras la sesión está abierta. Desviación menor del
    comentario del schema ("NULL mientras está abierta"): `ended_at` es NULL solo los primeros 10 s.
    Motivo: si la app se cae, la sesión queda con una duración casi correcta en vez de abierta para
    siempre, y `report` puede leer la sesión en curso. El reporte trata `NULL` como duración 0.
20. **Gaps / sleep**: si entre dos ticks pasan más de `max(10 s, 5 × poll_interval)` (o el reloj va
    hacia atrás), la sesión se cierra en el último tick visto y ese tiempo no se cuenta.
21. **Idle retroactivo**: al cruzar `idle_threshold_seconds`, la sesión idle empieza donde fue el
    último input (`now - idle_seconds`, nunca antes del inicio de la sesión actual). Sin cámara
    (M3) no se distingue `AFK` de "viendo un video": todo es idle.
22. **El tiempo idle no cuenta** en el reporte por categoría ni en los timers de reglas; el reporte
    lo muestra aparte. Limitación conocida: los timers *en vivo* ya sumaron los segundos que luego
    se re-etiquetan como idle (≤ `idle_threshold_seconds` por episodio); se corrige al reiniciar
    porque al arrancar los timers se recalculan desde SQLite.
23. **Schema**: se crean todas las tablas de la sección 11 con `IF NOT EXISTS` (también las de
    M3+, vacías). Sin sistema de migraciones todavía.
24. **Fechas**: ISO 8601 UTC con milisegundos y sufijo `Z` (`2026-10-29T18:42:27.262Z`). "Hoy" usa
    la timezone local del sistema (el PRD menciona America/Santiago; se toma la del sistema).
25. **Retención** (`data_retention_days`): al iniciar `run` se borran sesiones más antiguas.
26. **Logs**: nunca se loguean títulos de ventana (más simple que condicionarlo a
    `store_window_titles`).
27. **Top apps** agrupa por `app_name` y muestra la categoría donde esa app tuvo más tiempo.

## M2 — Classification + Rules

28. **Matcher `process`**: igualdad exacta case-insensitive (`str.casefold`) contra `process_name`
    (no contra `app_name`). **`title_regex`** usa `re.search` (coincide en cualquier parte del
    título). Cada `match` debe tener exactamente una key. `domain` se rechaza hasta M7.
29. **Overrides** (`classification_overrides`): la tabla existe pero no se lee todavía; se llena
    desde el dashboard en M5.
30. **`target` con varias keys** = AND (todas deben cumplirse). Al menos una key es obligatoria.
31. **Violaciones edge-triggered + cooldown de 30 s por regla**: se avisa cuando una regla pasa a
    violarse, no en cada tick; volver al target antes de 30 s no repite el aviso. El valor 30 es el
    default de `interventions.cooldown_seconds`, pero esa sección se lee recién en M4.
32. **`daily_limit`** solo se viola mientras estás usando el target (pasado el límite, abrir otra
    cosa no avisa). **`schedule`**: `start` inclusivo, `end` exclusivo, soporta rangos que cruzan
    medianoche; los días se evalúan con la hora local. Nada se viola mientras estás idle.
33. **Acciones**: en M2 `notify`, `warn` y `block` se ejecutan como `notify` (warn/block son M6) y
    se loguea la acción pendiente. `mode` (soft/strict) se valida pero no se usa hasta M6.
34. **`observe_only: true`** (default): las violaciones se registran en el log (INFO) pero no hay
    notificación ni fila en `interventions`. Con `false`: notificación + fila en `interventions`
    (`trigger = "rule:<id>"`, `level = 1`).
35. **Notificaciones con `osascript`** (viene con macOS, se llama vía `subprocess`) en vez de
    `desktop-notifier`: cero dependencias, sin `asyncio`. La notificación aparece como de
    "Script Editor"; puede que macOS pida permitir notificaciones para él. En M4 (botón
    "Falsa alarma") hay que reevaluar `desktop-notifier`, que sí soporta botones.

## Prueba real de 60 s (durante esta sesión)

36. Como el usuario llevaba >6 min sin tocar teclado/mouse, con el umbral de 120 s toda la corrida
    habría sido idle. Se usó una **copia temporal** del config de ejemplo (fuera del repo) con
    `idle_threshold_seconds: 600`, `observe_only: false` y una regla demo
    `daily_limit` de 12 s sobre `iTerm2`, y se alternó Finder → Chrome → iTerm con `osascript`.
    Esos datos quedaron en la DB real por defecto; si no los quieres, borra
    `~/Library/Application Support/nublock/nublock.db`.

## M3–M5 (segunda sesión, mismo día)

37. **Sin preguntas otra vez:** "Sigue con todo. Hasta el M5" reemplaza el "espera mi OK" entre
    milestones de la sección 0 del PRD. Se implementaron M3, M4 y M5 seguidos.

### M3 — Attention Monitor

38. **Versiones nuevas**: MediaPipe **1.2.0** y OpenCV **5.0.0** (el PRD asume MediaPipe 0.10).
    Se verificó que la Tasks API (`FaceLandmarkerOptions`, `ObjectDetectorOptions`,
    `detect_for_video`, `mp.Image`) tiene las mismas firmas. numpy 2.4, Pillow 13, pystray 0.19.5,
    FastAPI 0.162, uvicorn 0.54, Jinja2 3.1.6, python-multipart 0.0.32, httpx 0.28 (dev).
39. **Modelos** descargados con `curl` a `models/` (está en `.gitignore`): `face_landmarker.task`
    (float16, v1, sha256 `64184e22…`) y `efficientdet_lite0.tflite` (int8, v1, sha256 `0720bf24…`).
    Es la única descarga aparte de pip; la app nunca descarga nada (README tiene los comandos).
40. **Arquitectura de threads + event bus (`queue.Queue`) como en el PRD.** Se verificó que
    `frontmostApplication` *sí* se actualiza en un thread secundario si el **main thread hace
    girar su run loop**. Main thread = tray (pystray) o, con `--no-tray`, `run_main_loop()`.
    Threads: tracker, attention, core (consume el bus), dashboard (uvicorn). Se quitó el
    "bombeo" del run loop que el provider hacía en cada lectura.
41. **Head pose**: ángulos de Euler (Z-Y-X) de la matriz 4×4 de MediaPipe con `math`
    (sin scipy). No se asume hacia dónde crece el pitch: la calibración lo mide (`down_sign`,
    comparando puntos superiores vs inferiores). Sin calibrar se usa una zona genérica
    (yaw ±20°, pitch ±12°, `down_sign=+1`), **no verificada con cámara real**.
42. **Calibración**: 5 puntos por monitor (centro + 4 esquinas), 2 s cada uno, mediana por punto.
    Zona = rango de las medianas; los márgenes se suman al evaluar. `attention.monitors` (2 en el
    config de ejemplo, porque tienes 2 monitores). Se guarda en JSON, solo ángulos.
43. **Hysteresis**: volver a FOCUSED exige estar `hysteresis_deg` (3°) más adentro de la zona;
    para la mirada, el umbral baja 0,1 al salir de LOOKING_DOWN. Se aplica sobre el estado raw.
44. **Debounce**: `PAUSED` y `CAMERA_UNAVAILABLE` son inmediatos; los demás esperan
    `state_debounce_seconds`. `started_at` es cuándo empezó el candidato (no cuándo terminó el
    debounce), así los grace periods cuentan desde el inicio real.
45. **`confidence`** (attention_events) = fracción de frames que coincidían con el estado.
46. **Cámara solo durante focus sessions** (open question 3; `only_during_focus: true`). Fuera de
    ellas el estado es `PAUSED` y la cámara está liberada. También se libera con una app de
    `attention_exempt` activa (zoom.us, FaceTime): así se cumple FR-36 sin depender de detectar
    si "otra app la pide". Si abrir/leer falla → `CAMERA_UNAVAILABLE` y reintento cada
    `camera_retry_seconds`. Si falta un modelo, también `CAMERA_UNAVAILABLE` (y error en el log).
47. **Debug view** como comando aparte (`attention-debug`): en macOS `cv2.imshow` exige el main
    thread, que en `run` usa el tray. Dibuja 1 de cada 4 landmarks. No graba.
48. **La cámara real no se usó en esta sesión**: encenderla habría pedido permiso y te habría
    filmado sin que estuvieras (la pantalla estaba bloqueada). El pipeline real (modelos
    MediaPipe) se probó con un frame sintético: sin cara → `ABSENT`, ~2,9 ms/frame.

### M4 — Phone + Interventions

49. **Phone detection** solo cuando el estado raw es LOOKING_DOWN/PHONE, a `phone_detection.fps`.
    `PHONE` = mirando abajo + teléfono visto en los últimos 2 s (el detector corre a 1 FPS).
    Un teléfono sostenido frente a la cara no se detecta (FR-33 lo limita a LOOKING_DOWN).
50. **Episodes**: el grace period cuenta desde que empezó el estado actual; la escalation, desde
    el nivel 1. **El cooldown solo limita el nivel 1 de un episode nuevo**: si limitara
    todo, los niveles 2 (+10 s) y 3 (+20 s) de FR-41 nunca ocurrirían con un cooldown de 30 s
    (FR-45 y FR-41 chocan).
51. **Niveles**: 1 = notificación silenciosa, 2 = con sonido (`sound name` de AppleScript;
    open question 4 → sonido del sistema "Glass", configurable), 3 = overlay (solo en focus
    session strict).
52. **Overlay** en un **proceso aparte** con tkinter (el main thread de Nublock es del tray).
    Cubre la pantalla principal, semitransparente; se cierra con el botón, Esc o al volver a
    FOCUSED.
53. **"Falsa alarma"**: las notificaciones de `osascript` no tienen botones, así que está en el
    menú del tray y en el dashboard; marca la última intervention de los últimos 10 min.
    Recalibración: grace × (1 + 0,25 × falsas alarmas de ese estado en 7 días), máximo ×2.
54. **refocus_seconds** se guarda en cada intervention del episode al volver a FOCUSED. Si el
    episode termina en ABSENT/PAUSED no hay refocus.
55. **Observe-only + focus session**: una focus session activa las interventions aunque
    `observe_only` sea true (es un pedido explícito). Fuera de una focus session, observe-only
    sigue sin intervenir.
56. **Focus sessions** se inician desde el tray o el dashboard (no hay comando CLI: no hay IPC
    con el proceso que corre). Al cerrar Nublock la sesión termina con `completed=0`
    (open question 5: en v1 no sobrevive a reiniciar). Al completarse: notificación + break de
    `break_minutes` sin interventions ni cámara. `block_distracting` → aviso al entrar a una app
    distracting (edge-triggered, 30 s de cooldown; `trigger='focus:distracting'`); el bloqueo
    real es M6.
57. **"Pausar todo 15 min"**: sin interventions y con la cámara apagada; el tracking sigue.
58. **Retención y crash**: la retención también borra attention_events, interventions y
    focus_sessions. Al arrancar, las filas que quedaron abiertas (crash) se cierran con duración 0.

### M5 — Tray + Dashboard

59. **Señales con tray** (bug encontrado en la prueba real): pystray registra con
    `PyObjCTools.MachSignals` un handler de SIGINT que llama `NSApplication.terminate_`, que
    termina el proceso sin pasar por la limpieza. Además, los handlers normales de Python no
    corren mientras el main thread está en el run loop de Cocoa. Solución: el tray reemplaza
    los handlers de SIGINT/SIGTERM vía MachSignals por uno que solo activa `stop`; sin tray basta
    `signal.signal`. Verificado: tray+SIGTERM, tray+SIGINT y `--no-tray`+SIGINT terminan en
    menos de 0,5 s con todas las filas cerradas.
60. **Dashboard sin Chart.js**: cargarlo desde un CDN sería una network call y vendorearlo agrega
    un archivo de terceros. Barras con CSS y timeline con `div`s posicionados; se recarga cada 60 s.
61. **Seguridad del dashboard**: escucha solo en `127.0.0.1`; `TrustedHostMiddleware` (contra DNS
    rebinding) y chequeo del header `Origin` en todo POST (contra CSRF, *Cross-Site Request
    Forgery*: otra página web enviando formularios a tu localhost). Borrar el historial exige
    escribir "BORRAR"; los overrides de clasificación se conservan.
62. **Clasificar desde el dashboard** crea un override `process` (el más reciente gana, antes que
    las reglas del config) y publica `ReloadClassifier` → las sesiones nuevas usan la categoría
    nueva (FR-13 AC, testeado).
63. **`nublock dashboard`**: muestra los datos sin el tracker; clasificar funciona, los controles
    responden 409 ("Nublock no está corriendo").
64. **Starlette** recomienda `httpx2` para su TestClient. Instalarlo fue bloqueado por el sistema
    de permisos (paquete desconocido), así que se mantiene `httpx` y el warning se filtra en
    pytest.
65. **Tray**: con la cámara encendida, el color sigue al estado de atención; sin cámara, a la
    categoría de la app activa. Punto rojo = cámara encendida (FR-71; macOS además muestra su
    indicador verde). El menú muestra en vivo focus, cámara, app y timers del día (FR-20).
66. **Estado compartido**: `LiveState` guarda un `Snapshot` inmutable protegido con un `Lock`.
    SQLite: `check_same_thread=False` y una conexión por thread (core, tracker y una por request
    del dashboard).
67. **Fuera de alcance**: FR-62 (export CSV/JSON), M6+ (bloqueo real, fricción strict, browser
    extension, packaging/autostart).

## Mejoras pedidas después de M5 (notificaciones propias y detección de teléfono)

68. **Diagnóstico de notificaciones invisibles**: Nublock sí disparaba las alertas (5 interventions
    reales en la DB a las 17:34–17:37), pero `osascript` las atribuye a "Script Editor", que nunca
    estuvo autorizado: macOS las descartaba y `osascript` igual terminaba con código 0.
69. **Notificaciones a nombre de "Nublock"**: macOS atribuye cada notificación a la *app bundle*
    que la envía, así que se compila un `Nublock.app` mínimo en Swift (`UNUserNotificationCenter`,
    la API actual) con Info.plist e ícono propios. Bundle id `local.nublock.app` (prefijo `local.`
    para no usar el dominio de nadie), firma *ad-hoc*, `LSUIElement` (sin ícono en el Dock), en
    `~/Library/Application Support/nublock/Nublock.app`. Se crea con
    `python -m nublock setup-notifications`; si no existe, se vuelve a `osascript` con un warning.
    Alternativas descartadas: `desktop-notifier` y pyobjc notifican como "Python" (el bundle del
    intérprete); `terminal-notifier` es una herramienta externa.
70. **Botón "Falsa alarma" en la notificación** (FR-43, antes solo en tray/dashboard): las alertas
    de atención (niveles 1 y 2) lo traen; hace `POST http://127.0.0.1:<port>/feedback/false-alarm`.
    Click en la notificación → abre el dashboard. Info.plist permite HTTP solo a direcciones
    locales (`NSAllowsLocalNetworking`).
71. **Títulos**: como el encabezado ya dice "Nublock" con el ícono, el título describe la alerta
    ("Vuelve al foco", "Regla de Nublock", "Focus session").
72. **Primer permiso**: el aviso de permiso sí aparece (verificado en el log de `usernoted`), pero
    si nadie lo responde macOS no vuelve a preguntar y deniega. `setup-notifications` lo explica y
    abre System Settings → Notifications para activarlo a mano.
73. **Windows (toast abajo a la derecha)**: queda pendiente junto con el platform adapter de
    Windows; la interfaz `Notifier` ya permite agregar esa implementación.
74. **Diagnóstico del teléfono**: con renders de iPhone de macOS sobre frames sintéticos (sin
    encender la cámara), el modelo original (EfficientDet-Lite0 int8 sobre el frame completo a
    640 px) daba scores de 0.00–0.40: **nunca** superaba `min_score: 0.5`. Causa: el detector
    reduce el frame 16:9 a 320×320 y el teléfono queda diminuto.
75. **Nueva estrategia de detección** (medida con los mismos frames): se recorta un cuadrado bajo
    la cara (2,2 × el alto de la cara, mínimo medio frame) desde la imagen **a resolución de
    captura** y se usa **EfficientDet-Lite2 int8** (entrada 448). Scores: 0.55–0.91 para
    teléfonos de 60–260 px de alto, 0.00 sin teléfono. Costo: ~45 ms por inferencia, solo
    mientras miras hacia abajo.
76. **Config**: `capture_width: 1280` (cámara) separado de `frame_width: 640` (análisis de cara);
    `phone_detection.fps: 2` (antes 1), `min_score: 0.4` (antes 0.5), `model` configurable. La
    calibración también captura a `capture_width` para medir con el mismo encuadre.
77. **Debug view** muestra siempre el score del teléfono, el rectángulo donde se busca (rojo si lo
    ve) y al salir imprime el score máximo, para ajustar `min_score` con datos reales. Mirando la
    pantalla con un teléfono a la vista el estado sigue FOCUSED.
78. **Límite conocido**: si el teléfono está fuera del campo de la cámara (ej. en las piernas),
    no se puede ver; en ese caso alerta `LOOKING_DOWN` (grace de 15 s en vez de 3 s).

## M6 — Blocking + strict mode (y FR-62 export)

79. **Ocultar en vez de minimizar** (soft): en macOS, minimizar una ventana de otra app exige el
    permiso Accessibility; `NSRunningApplication.hide()` (Cmd+H) saca la app de la pantalla sin
    permisos. **Strict** usa `terminate()` (Cmd+Q, la app puede preguntar si guardar). Sin
    `forceTerminate`, para no perder trabajo.
80. `hide()` **puede retornar NO aunque oculta la app** (medido en macOS 26 con la Calculadora en
    primer plano): se ignora su valor de retorno.
81. **Nunca se bloquean** Finder, loginwindow, Dock, SystemUIServer, WindowServer ni el propio
    proceso de Nublock. Los **browsers solo se ocultan**, incluso en strict
    (`blocking.never_terminate`): cerrarlos cerraría todas las pestañas; bloquear sitios es M7.
82. **Acciones (FR-22)**: `notify` avisa; `block` avisa y bloquea de inmediato, y vuelve a
    bloquear cada vez que reabres la app mientras la regla se siga violando (máximo una vez cada
    2 s por app); `warn` avisa con `grace_seconds` (default 30, por regla) y bloquea si sigues ahí
    al vencer. Salir antes cancela el bloqueo; volver a entrar da un grace nuevo.
83. **Focus session + `block_distracting`**: las apps `distracting` se ocultan (soft) o cierran
    (strict) durante la sesión, aunque `observe_only` sea true (igual que las alertas, #55).
84. **Fricción del modo strict (FR-23)**: pausar todo (si hay reglas strict activas o una focus
    session strict), terminar una focus session strict o desactivar una regla strict exige
    esperar `friction_seconds` (60) y escribir `confirmation_phrase` en el dashboard (no se
    puede pegar). El tray abre esa página. El Core rechaza los comandos sin `confirmed=True`,
    así que no basta con saltarse la página. La solicitud expira a los 10 min y sirve una sola vez.
85. **Pausar la cámara nunca tiene fricción**: el PRD exige poder pausarla con un clic (privacidad).
86. **Desactivar una regla** dura hasta el fin del día local y no sobrevive a reiniciar Nublock
    (reiniciar la reactiva: más estricto, no menos).
87. **Estadística "veces que desactivaste"** (riesgo de la sección 15): tabla nueva
    `disable_events` (no está en el schema del PRD); se muestra en el dashboard.
88. **Límite conocido**: editar `config.yaml` para borrar una regla strict sigue siendo posible.
    La fricción es un *commitment device*, no un candado.
89. **FR-62 export**: `/export.csv` y `/export.json` (`?days=1..365`): segundos por día, app,
    categoría e idle. Nunca incluye títulos de ventana ni timestamps finos.
90. **Prueba real del DoD de M6**: con una regla `block` de 6 s sobre la Calculadora, Nublock la
    ocultó a los 6 s de uso (tracker, reglas y blocker reales). Ojo para futuras pruebas:
    `osascript ... activate` no desoculta una app oculta; `open -a` sí.

## M7 — Bloqueo de sitios (versión /etc/hosts, sin extensión)

91. **Cambio respecto al PRD**: el PRD planteaba M7 como una browser extension. El usuario
    prefirió bloquear dominios a nivel de computador, así que M7 bloquea por DNS con
    `/etc/hosts`. Funciona en todos los browsers y apps sin instalar nada en ellos.
92. **Por qué no por IP**: los sitios grandes comparten IPs de CDN con otros servicios (bloquear
    las de YouTube puede romper otros servicios de Google) y esas IPs cambian. Bloquear el
    nombre (DNS) es preciso.
93. **Helper de root instalado una vez** (`python -m nublock sites setup`, pide la contraseña con
    el diálogo de macOS): script POSIX sh en `/Library/PrivilegedHelperTools/` + LaunchDaemon con
    `WatchPaths` sobre `/Library/Application Support/Nublock/blocked_domains.txt`. Nublock (tu
    usuario) solo escribe esa lista; launchd ejecuta el helper como root cuando cambia. No hay
    proceso de root corriendo todo el tiempo.
94. **Seguridad del helper**: archivos de root (tu usuario no puede modificarlos, así no hay
    escalada de privilegios); solo acepta líneas que son dominios válidos (máx. 2000); solo
    escribe `0.0.0.0`/`::` (bloquear), nunca IPs arbitrarias; ignora la lista si es un symlink;
    la carpeta de la lista es de root (no se puede reemplazar el archivo por un symlink); solo
    reescribe su sección marcada de /etc/hosts y vacía el caché de DNS. Probado ejecutando el
    script real con entradas maliciosas (`evil.com 6.6.6.6`, `*.reddit.com`, `../../etc/passwd`).
95. **Qué se bloquea**: sitios de `sites:` en el config: `always: true` siempre (salvo "Pausar
    todo"); los `distracting` durante una focus session; y los que coinciden con el target
    (`productivity`/`subcategory`, nunca `process`) de una regla `block`/`warn` activa (límite
    superado u horario). Observe-only desactiva las reglas pero no `always` ni la focus session.
    Al cerrar Nublock se libera todo (igual que la focus session, no sobrevive al cierre).
96. **Subdominios**: /etc/hosts no tiene comodines; se agregan `www`, `m`, `mobile` por dominio
    (configurable). Otros subdominios (ej. `music.youtube.com`) hay que listarlos.
97. **Límites frente a una extensión**: bloquea dominios completos, no rutas
    (`youtube.com/shorts`); no mide tiempo por sitio (eso sigue dependiendo de los títulos de
    ventana con permiso Screen Recording); una pestaña ya abierta puede seguir funcionando
    hasta ~1 min por el caché de DNS del browser o conexiones abiertas. Como admin, siempre
    puedes editar /etc/hosts o desinstalar: es un commitment device, no un candado. Con iCloud
    Private Relay en Safari, verificar que se respete (no probado).
98. **La instalación no se ejecutó en esta sesión**: pide tu contraseña de administrador y es un
    cambio del sistema que debes aprobar tú.

## M8 — App de macOS, permisos y arranque al iniciar sesión

99. **Nublock.app es la app principal** (en `~/Applications`, visible en Spotlight/Launchpad): el
    mismo programa Swift de las notificaciones ahora, sin argumentos, lanza y supervisa
    `python -m nublock run` (reintenta cada 5 s si se cae, máximo 5 veces en 10 min; termina si
    eliges "Salir"). Se mantuvo el bundle id `local.nublock.app`, así no se pierde el permiso de
    notificaciones ya dado. La copia vieja en Application Support se quita del registro y se borra.
100. **Por qué una app y no un `python -m` en el login**: macOS asigna cámara y Screen Recording al
     proceso *responsable* (la app que lanzó al resto). Desde la terminal ese proceso es iTerm2;
     desde Nublock.app es "Nublock", y los diálogos de permiso dicen "Nublock". El Info.plist
     incluye `NSCameraUsageDescription` (obligatorio para usar la cámara) y la ruta del Python
     del venv (`NublockPython`).
101. **Hallazgo**: ejecutar el binario de la app *directo* desde la terminal reporta los permisos de
     la terminal (dio "cámara: granted" cuando Nublock no lo tenía). `doctor`/`app status`/
     `--request-permissions` ejecutan la app con `open` (LaunchServices), que sí la evalúa
     como Nublock.
102. **Instancia única**: `nublock run` toma un `flock` sobre `<db>.lock`; si otro lo tiene, sale con
     código 3 y la app abre el dashboard en vez de lanzar otra copia. `flock` se libera solo si
     el proceso muere, así que nunca queda un lock "pegado".
103. **Directorio de trabajo**: la app arranca Python desde tu home, así que `attention.models_dir`
     relativo se busca en el directorio actual, en la carpeta de datos y en la raíz del repo.
     `app install` copia el config de ejemplo a `~/Library/Application Support/nublock/config.yaml`
     si no existía (la app no recibe `--config`).
104. **Arranque al iniciar sesión** (`app autostart-on`): primero `SMAppService.mainApp` (Login
     Items); si macOS no lo acepta (reportó `not_found`, probablemente por la firma ad-hoc), un
     LaunchAgent con `open -a Nublock.app`. **No se activó en esta sesión**: es un cambio
     persistente que decides tú (el sistema de permisos también lo bloqueó, correctamente).
105. **`nublock doctor [--fix]`**: config, modelos, calibración, app instalada y apuntando a este
     venv, permisos de Nublock (notificaciones, cámara, Screen Recording), arranque al iniciar
     sesión, helper de sitios e instancia corriendo. `--fix` pide los permisos con los diálogos de
     macOS y abre los paneles de System Settings de los que sigan faltando.
106. **El tray ya no muestra ícono en el Dock** (`NSApplicationActivationPolicyAccessory`).
107. **DoD del PRD ("instalar en un PC limpio, sin terminal") cumplido a medias**: en este Mac,
     Nublock funciona sin terminal. Para otro Mac falta: (a) empaquetar Python y las dependencias
     dentro de la app (PyInstaller/Briefcase; mediapipe y OpenCV son pesados y necesitan ajustes),
     y (b) firmar con un certificado *Developer ID* y **notarizar** con Apple (requiere el Apple
     Developer Program, US$99/año). Sin eso, Gatekeeper bloquea una app descargada. Además,
     con firma ad-hoc cada recompilación cambia la firma y macOS puede volver a pedir los
     permisos de cámara/Screen Recording: recompila solo cuando haga falta.
108. **Pendiente de verificar contigo**: que la cámara funcione cuando Nublock corre desde la app
     (permiso a nombre de Nublock, que hoy está `not_determined`): `python -m nublock doctor --fix`,
     luego una focus session desde el tray.

## Ventana de permisos y distribución para otros Macs

109. **Ventana "Permisos y configuración"** (AppKit, en Nublock.app): notificaciones, cámara,
     grabación de pantalla, calibración, bloqueo de sitios y abrir al iniciar sesión, cada uno
     con ✓/○/✗ y un botón (Permitir / Abrir Ajustes si se negó / Calibrar / Instalar /
     Activar). Se actualiza cada segundo. Aparece al abrir la app la primera vez o si falta un
     permiso obligatorio (notificaciones, cámara); siempre está en el menú del tray. Al cerrarla,
     si se activó Grabación de pantalla, la app reinicia el proceso de Python (ese permiso solo
     aplica a procesos nuevos).
110. **Calibración sin terminal**: `nublock calibrate --gui` abre una ventana de OpenCV con vista
     previa en espejo; ESPACIO mide cada punto, Esc cancela. Los textos de esa ventana van sin
     tildes porque las fuentes de OpenCV no las tienen.
111. **`--snapshot archivo.png`**: dibuja la ventana a un PNG sin mostrarla. Así se revisó el diseño
     sin capturar tu pantalla (eso habría requerido Grabación de pantalla para la terminal).
     Hallazgo: en modo oscuro el texto sale blanco sobre fondo transparente, por eso el snapshot
     fuerza la apariencia clara.
112. **Distribución sin Apple (decisión del usuario)**: sin App Store, sin Developer ID, sin
     notarizar. Se distribuye como repo o como zip en una página propia, instalado con
     `curl … | sh`. curl no marca la cuarentena (`com.apple.quarantine`), así que Gatekeeper no
     bloquea la app ad-hoc; igual `install.sh` quita la cuarentena y verifica el SHA-256.
     Probado con un zip marcado como descargado por Safari: queda sin cuarentena y con la firma
     íntegra.
113. **App autocontenida con python-build-standalone** (no PyInstaller ni py2app): un CPython
     relocatable (release fija `20261026`, Python 3.11.18, verificado con SHA256SUMS) dentro de
     `Contents/Resources/python`, con Nublock y sus dependencias instaladas con pip, más los
     modelos y el config de ejemplo. Todo funciona igual que en el venv (`python -m nublock`,
     tkinter para el overlay), sin análisis de imports ni hooks. Sin `NublockPython` en el
     Info.plist, el launcher usa ese Python, y pasa `NUBLOCK_APP` y `NUBLOCK_MODELS_DIR` al
     proceso.
114. **El build de la release no se ejecutó en esta sesión**: el sistema de permisos bloqueó
     descargar y ejecutar el runtime de Python desde GitHub (correcto: es código externo que
     apruebas tú). Lo corres con `python scripts/build_release.py`.
115. **Una arquitectura por build**: la release sirve para la arquitectura del Mac que la construye
     (arm64 en este Mac). Para Intel hay que construirla en un Mac Intel (o agregar
     cross-build). `install.sh` elige el zip según `uname -m`.
116. **`uninstall.sh [--all]`**: cierra Nublock, quita el arranque al iniciar sesión, desinstala el
     helper de sitios (limpia /etc/hosts) y borra la app (y con `--all` también el historial).
117. **Descargas del build con `curl`** (no `urllib`): al correr el build, el Python de python.org
     falló con `CERTIFICATE_VERIFY_FAILED` porque no usa los certificados de macOS (habría que
     correr su "Install Certificates.command"). curl usa los del sistema. pip no tiene el
     problema porque trae sus propios certificados.
118. **Build fuera del repo** (`~/Library/Caches/nublock-build`): la carpeta Documents está en
     iCloud Drive; el build (cientos de MB) se subía a la nube e iCloud agregaba atributos
     `com.apple.fileprovider.*` que `codesign` rechaza ("resource fork, Finder information, or
     similar detritus not allowed"). Además, antes de firmar: se borran `PyObjCTest` (tests de
     PyObjC) y los `.dSYM` (símbolos de debug), y `xattr -cr` limpia los atributos extendidos.
