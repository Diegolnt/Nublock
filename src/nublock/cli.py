"""Command-Line Interface con `argparse` (stdlib)."""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from nublock import __version__
from nublock.config import Config, ConfigError, load_config
from nublock.logging_setup import setup_logging
from nublock.paths import (
    default_app_path,
    default_calibration_path,
    default_config_path,
    default_db_path,
    default_log_dir,
    legacy_app_path,
    project_root,
    resolve_models_dir,
)
from nublock.report import build_daily_report, format_report
from nublock.storage import Repository

if TYPE_CHECKING:
    from nublock.site_blocking import SiteBlocker
from nublock.timeutils import local_day_bounds

LOCAL_HOST = "127.0.0.1"  # el dashboard solo escucha en este host (ver dashboard/server.py)
NOTIFICATION_SETTINGS_URL = "x-apple.systempreferences:com.apple.Notifications-Settings.extension"
LOGIN_ITEMS_SETTINGS_URL = "x-apple.systempreferences:com.apple.LoginItems-Settings.extension"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nublock",
        description="Nublock: activity tracking local-first para recuperar el control de tu día.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--config",
        type=Path,
        help=f"ruta a config.yaml (default: {default_config_path()} si existe)",
    )
    parser.add_argument(
        "--db", type=Path, help=f"ruta a la base de datos SQLite (default: {default_db_path()})"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="más detalle en consola/log")

    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    run = commands.add_parser(
        "run", help="iniciar Nublock: tracker, cámara, tray y dashboard (Ctrl+C para detener)"
    )
    run.add_argument(
        "--duration", type=float, metavar="SECONDS", help="detenerse solo después de N segundos"
    )
    run.add_argument("--no-tray", action="store_true", help="sin ícono en la barra de menú")
    run.add_argument("--no-camera", action="store_true", help="sin attention monitor")
    run.add_argument("--no-dashboard", action="store_true", help="sin dashboard web local")
    run.set_defaults(handler=_cmd_run)

    report = commands.add_parser("report", help="imprimir tiempo por categoría y top apps")
    report.add_argument("period", choices=["today"], nargs="?", default="today")
    report.set_defaults(handler=_cmd_report)

    config = commands.add_parser("config", help="validar la config y mostrar rutas")
    config.set_defaults(handler=_cmd_config)

    calibrate = commands.add_parser("calibrate", help="calibrar la zona 'mirando la pantalla'")
    calibrate.add_argument(
        "--monitors", type=int, help="monitores a calibrar (default: attention.monitors)"
    )
    calibrate.add_argument(
        "--gui", action="store_true", help="en una ventana con vista previa (sin terminal)"
    )
    calibrate.set_defaults(handler=_cmd_calibrate)

    debug = commands.add_parser(
        "attention-debug", help="ventana en vivo con landmarks y estado (sin grabar)"
    )
    debug.set_defaults(handler=_cmd_attention_debug)

    dashboard = commands.add_parser(
        "dashboard", help="solo el dashboard (ver datos sin correr el tracker)"
    )
    dashboard.set_defaults(handler=_cmd_dashboard)

    setup = commands.add_parser(
        "setup-notifications",
        help="crear Nublock.app para notificaciones nativas con ícono (macOS)",
    )
    setup.set_defaults(handler=_cmd_setup_notifications)

    sites = commands.add_parser(
        "sites", help="bloqueo de sitios vía /etc/hosts: setup | remove | status (macOS)"
    )
    sites.add_argument("action", choices=["setup", "remove", "status"])
    sites.set_defaults(handler=_cmd_sites)

    app = commands.add_parser(
        "app",
        help="la app de macOS: install | status | open | autostart-on | autostart-off",
    )
    app.add_argument(
        "action",
        choices=["install", "status", "open", "permissions", "autostart-on", "autostart-off"],
    )
    app.set_defaults(handler=_cmd_app)

    doctor = commands.add_parser("doctor", help="revisar permisos, modelos y configuración")
    doctor.add_argument(
        "--fix", action="store_true", help="pedir los permisos que falten (diálogos de macOS)"
    )
    doctor.set_defaults(handler=_cmd_doctor)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log_file = setup_logging(default_log_dir(), verbose=args.verbose)
    config_path = _resolve_config_path(args.config)
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    db_path: Path = args.db or default_db_path()
    context = _Context(config=config, config_path=config_path, db_path=db_path, log_file=log_file)
    return int(args.handler(args, context))


@dataclass(frozen=True)
class _Context:
    """Lo que todos los subcomandos necesitan, ya resuelto."""

    config: Config
    config_path: Path | None
    db_path: Path
    log_file: Path


def _resolve_config_path(cli_path: Path | None) -> Path | None:
    if cli_path is not None:
        return cli_path
    default = default_config_path()
    return default if default.exists() else None


def _cmd_run(args: argparse.Namespace, ctx: _Context) -> int:
    from nublock.instance import ALREADY_RUNNING_EXIT_CODE, InstanceLock

    lock = InstanceLock(ctx.db_path.with_suffix(".lock"))
    if not lock.acquire():
        print("Nublock ya está corriendo.", file=sys.stderr)
        return ALREADY_RUNNING_EXIT_CODE
    try:
        return _run(args, ctx)
    finally:
        lock.release()


def _run(args: argparse.Namespace, ctx: _Context) -> int:
    # Imports tardíos: `report` y `--help` no necesitan cargar pyobjc, OpenCV ni FastAPI.
    from nublock.app import BackgroundService, NublockApp
    from nublock.attention.monitor import AttentionMonitor
    from nublock.blocking import Enforcer
    from nublock.events import EventBus
    from nublock.interventions import SubprocessOverlay, get_notifier
    from nublock.tracker.platform import get_app_blocker, get_window_provider

    config = ctx.config
    try:
        provider = get_window_provider()
    except NotImplementedError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    bus = EventBus()
    monitor: AttentionMonitor | None = None
    if config.attention.enabled and not args.no_camera:
        from nublock.attention.factory import build_monitor

        monitor = build_monitor(config.attention, default_calibration_path(), bus.publish)
    repository = Repository(ctx.db_path)
    tracker_repository = Repository(ctx.db_path)  # una conexión por thread
    with_dashboard = config.dashboard.enabled and not args.no_dashboard
    dashboard_url = f"http://{LOCAL_HOST}:{config.dashboard.port}" if with_dashboard else None
    notifier = get_notifier(default_app_path(), dashboard_url)
    enforcer = Enforcer(get_app_blocker(), config.blocking)
    site_blocker = _site_blocker(config)
    app = NublockApp(
        config,
        provider,
        repository,
        notifier,
        bus=bus,
        overlay=SubprocessOverlay(),
        monitor=monitor,
        tracker_repository=tracker_repository,
        enforcer=enforcer,
        site_blocker=site_blocker,
    )
    services: list[BackgroundService] = []
    if with_dashboard:
        from nublock.dashboard.server import DashboardServer, create_app
        from nublock.friction import FrictionGate

        services.append(
            DashboardServer(
                create_app(
                    ctx.db_path, bus.publish, app.live, config, FrictionGate(config.blocking)
                ),
                config.dashboard.port,
            )
        )

    mode = "observe-only (no interviene)" if config.general.observe_only else "activo"
    print(f"Nublock — modo {mode}. DB: {ctx.db_path}")
    if dashboard_url:
        print(f"Dashboard: {dashboard_url}")
    if monitor is not None and config.attention.only_during_focus:
        print(
            "Cámara: se enciende solo durante focus sessions "
            "(inícialas desde el tray o el dashboard)."
        )
    print("Ctrl+C para detener." if args.duration is None else f"Corriendo {args.duration:g} s...")

    ui = None
    if not args.no_tray:
        from nublock.ui.tray import Tray

        tray = Tray(app.live, bus.publish, dashboard_url, config.focus_session.default_minutes)
        ui = tray.run
    try:
        app.run(args.duration, ui=ui, services=services)
    finally:
        repository.close()
        tracker_repository.close()
    print("Nublock detenido. Mira el resultado con: python -m nublock report today")
    return 0


def _cmd_report(args: argparse.Namespace, ctx: _Context) -> int:
    repository = Repository(ctx.db_path)
    try:
        today = date.today()
        day_start, day_end = local_day_bounds(today)
        sessions = repository.sessions_between(day_start, day_end)
    finally:
        repository.close()
    print(format_report(build_daily_report(today, sessions, day_start, day_end)))
    return 0


def _cmd_config(args: argparse.Namespace, ctx: _Context) -> int:
    general = ctx.config.general
    print(f"config:  {ctx.config_path or '(defaults; no hay config.yaml)'} — OK")
    print(f"db:      {ctx.db_path}")
    print(f"log:     {ctx.log_file}")
    print(f"calibración: {default_calibration_path()}")
    print(
        f"observe_only={general.observe_only}  store_window_titles={general.store_window_titles}  "
        f"poll={general.poll_interval_seconds:g}s  idle={general.idle_threshold_seconds:g}s"
    )
    print(
        f"{len(ctx.config.classification_rules)} reglas de clasificación, "
        f"{len(ctx.config.rules)} reglas (daily_limit/schedule)"
    )
    return 0


def _cmd_calibrate(args: argparse.Namespace, ctx: _Context) -> int:
    from nublock.attention.calibration import (
        CalibrationError,
        run_calibration,
        run_calibration_gui,
        save_zone,
    )
    from nublock.attention.camera import OpenCVCamera
    from nublock.attention.face import MediaPipeFaceAnalyzer
    from nublock.attention.factory import FACE_MODEL

    attention = ctx.config.attention
    monitors = args.monitors or attention.monitors
    camera = OpenCVCamera(attention.camera_index, attention.capture_width)
    try:
        analyzer = MediaPipeFaceAnalyzer(resolve_models_dir(attention.models_dir) / FACE_MODEL)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if not camera.open():
        print("Error: no se pudo abrir la cámara (revisa el permiso Camera).", file=sys.stderr)
        return 1
    print(f"Calibración de {monitors} monitor(es): siéntate como cuando trabajas.")
    try:
        if args.gui:
            gui_zone = run_calibration_gui(camera, analyzer, monitors, attention.frame_width)
            if gui_zone is None:
                print("Calibración cancelada.")
                return 1
            zone = gui_zone
        else:
            zone = run_calibration(camera, analyzer, monitors, attention.frame_width)
    except CalibrationError as exc:
        print(f"Error: {exc}. ¿La cámara te ve bien?", file=sys.stderr)
        return 1
    finally:
        camera.release()
        analyzer.close()
    path = default_calibration_path()
    save_zone(zone, path)
    print(
        f"Listo: yaw [{zone.yaw_min:.1f}, {zone.yaw_max:.1f}]°, "
        f"pitch [{zone.pitch_min:.1f}, {zone.pitch_max:.1f}]°, down_sign={zone.down_sign}. "
        f"Guardado en {path}"
    )
    return 0


def _cmd_attention_debug(args: argparse.Namespace, ctx: _Context) -> int:
    from nublock.attention.camera import OpenCVCamera
    from nublock.attention.debug_view import run_debug_view
    from nublock.attention.factory import build_pipeline, load_zone_or_default

    attention = ctx.config.attention
    zone = load_zone_or_default(default_calibration_path())
    try:
        pipeline = build_pipeline(attention, zone, debug=True)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    camera = OpenCVCamera(attention.camera_index, attention.capture_width)
    print("Debug view: q o Esc para salir. Nada se graba.")
    try:
        run_debug_view(attention, camera, pipeline)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_dashboard(args: argparse.Namespace, ctx: _Context) -> int:
    import uvicorn

    from nublock.dashboard.server import HOST, create_app

    port = ctx.config.dashboard.port
    print(f"Dashboard (solo lectura de datos) en http://{HOST}:{port} — Ctrl+C para salir")
    uvicorn.run(create_app(ctx.db_path), host=HOST, port=port, log_level="warning")
    return 0


def _install_app(ctx: _Context) -> Path | None:
    """Compila Nublock.app en ~/Applications (y quita la copia vieja de antes de M8)."""
    import shutil

    from nublock.interventions.app_bundle import BuildError, build_app, unregister

    if sys.platform != "darwin":
        print("Solo disponible en macOS por ahora.", file=sys.stderr)
        return None
    sounds = {"Glass", ctx.config.interventions.sound_name}
    dashboard_url = f"http://{LOCAL_HOST}:{ctx.config.dashboard.port}"
    print("Compilando Nublock.app (Swift)...")
    try:
        app = build_app(default_app_path(), sounds, sys.executable, dashboard_url)
    except BuildError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return None
    legacy = legacy_app_path()
    if legacy.exists():
        unregister(legacy)
        shutil.rmtree(legacy)
    print(f"Listo: {app}")
    # La app no recibe --config: usa el config.yaml estándar. Si no existe, copiamos el ejemplo.
    user_config = default_config_path()
    example = project_root() / "config" / "config.example.yaml"
    if not user_config.exists() and example.exists():
        user_config.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(example, user_config)
        print(f"Config copiado a {user_config} (edítalo ahí; la app lo usa siempre).")
    return app


def _cmd_setup_notifications(args: argparse.Namespace, ctx: _Context) -> int:
    import subprocess

    from nublock.interventions.app_bundle import executable_path

    app = _install_app(ctx)
    if app is None:
        return 1
    print(
        "Enviando una notificación de prueba. La primera vez macOS muestra un aviso arriba a la "
        "derecha: haz click en *Permitir* (o en Opciones > Permitir). Espero hasta 2 minutos..."
    )
    result = subprocess.run(
        [
            str(executable_path(app)),
            "--notify",
            "--title",
            "Notificaciones activadas",
            "--message",
            "Así se verán las alertas de Nublock.",
            "--sound",
            "Glass",
            "--timeout",
            "120",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"La notificación falló: {result.stderr.strip()}", file=sys.stderr)
        print(
            "Activa el permiso a mano: System Settings > Notifications > Nublock > "
            "Allow notifications. Abriendo ese panel...",
            file=sys.stderr,
        )
        subprocess.run(["open", NOTIFICATION_SETTINGS_URL], check=False)
        return 1
    print("Notificación enviada. Ajusta el estilo en System Settings > Notifications > Nublock.")
    return 0


def _site_blocker(config: Config) -> "SiteBlocker | None":
    from nublock.site_blocking import SiteBlocker, is_installed

    if not config.sites or not config.site_blocking.enabled:
        return None
    if not is_installed():
        print("Sitios: el bloqueo por /etc/hosts no está instalado. Actívalo con:")
        print("  python -m nublock sites setup")
        return None
    return SiteBlocker(config.site_blocking.subdomains)


def _cmd_sites(args: argparse.Namespace, ctx: _Context) -> int:
    from nublock import site_blocking

    if sys.platform != "darwin":
        print("Solo disponible en macOS por ahora.", file=sys.stderr)
        return 1
    if args.action == "status":
        installed = site_blocking.is_installed()
        print(f"helper instalado: {'sí' if installed else 'no'}")
        print(
            f"sitios en tu config: {', '.join(s.domain for s in ctx.config.sites) or '(ninguno)'}"
        )
        blocked = sorted(set(site_blocking.blocked_in_hosts()))
        print(f"bloqueados ahora en /etc/hosts: {', '.join(blocked) or '(ninguno)'}")
        return 0
    if args.action == "setup":
        print(
            "Se instalará un helper mínimo (como root) que solo puede agregar dominios "
            "bloqueados a /etc/hosts.\nmacOS te pedirá tu contraseña de administrador..."
        )
        result = site_blocking.install()
    else:
        print("Quitando el helper y la sección de Nublock de /etc/hosts...")
        result = site_blocking.uninstall()
    if result.returncode != 0:
        print(f"Error: {result.stderr.strip() or 'cancelado'}", file=sys.stderr)
        return 1
    print(
        "Listo." + (" Nublock bloqueará sitios mientras corre." if args.action == "setup" else "")
    )
    return 0


def _cmd_app(args: argparse.Namespace, ctx: _Context) -> int:
    import subprocess

    from nublock.doctor import app_status
    from nublock.interventions.app_bundle import executable_path

    app = default_app_path()
    if args.action == "install":
        if _install_app(ctx) is None:
            return 1
        print("Ábrela desde Spotlight/Launchpad o con: open -a Nublock")
        print("Después revisa los permisos con: python -m nublock doctor --fix")
        return 0
    if not executable_path(app).exists():
        print(
            "Nublock.app no está instalada. Corre: python -m nublock app install", file=sys.stderr
        )
        return 1
    if args.action == "status":
        status = app_status(app)
        if status is None:
            print("No se pudo consultar a Nublock.app.", file=sys.stderr)
            return 1
        for key, value in sorted(status.items()):
            print(f"{key:<18}{value}")
        return 0
    if args.action == "open":
        return subprocess.run(["open", str(app)], check=False).returncode
    if args.action == "permissions":
        return open_permissions_window(app)
    from nublock import autostart
    from nublock.interventions.app_bundle import run_app

    if args.action == "autostart-off":
        run_app(app, "--login-item", "off")
        autostart.disable_launch_agent()
        print("Abrir al iniciar sesión: desactivado")
        return 0
    stdout, stderr = run_app(app, "--login-item", "on")
    state = stdout.strip()
    if state in ("enabled", "requires_approval"):
        print(f"Abrir al iniciar sesión: {state} (Login Items)")
        if state == "requires_approval":
            print("macOS pide aprobarlo en System Settings > General > Login Items.")
            subprocess.run(["open", LOGIN_ITEMS_SETTINGS_URL], check=False)
        return 0
    # SMAppService no lo aceptó (ej. app firmada ad-hoc): usamos un LaunchAgent.
    reason = state or stderr.strip() or "sin respuesta"
    print(f"Login Items no disponible ({reason}); uso un LaunchAgent.")
    if not autostart.enable_launch_agent(app):
        print("Error: no se pudo cargar el LaunchAgent.", file=sys.stderr)
        return 1
    print(f"Abrir al iniciar sesión: activado ({autostart.launch_agent_path()})")
    return 0


def _cmd_doctor(args: argparse.Namespace, ctx: _Context) -> int:
    from nublock import autostart, doctor
    from nublock.instance import InstanceLock
    from nublock.site_blocking import is_installed

    app = default_app_path()
    status = doctor.app_status(app)
    if args.fix and status is not None:
        print("Pidiendo permisos: responde los diálogos de macOS (a nombre de Nublock)...")
        status = doctor.fix_permissions(app)
    running = InstanceLock(ctx.db_path.with_suffix(".lock")).held_by_other()
    checks = doctor.run_checks(
        ctx.config,
        ctx.config_path,
        app,
        status,
        default_calibration_path(),
        is_installed(),
        running,
        autostart.launch_agent_installed(),
    )
    print(doctor.format_checks(checks))
    return 0 if all(check.ok or check.optional for check in checks) else 1


def open_permissions_window(app: Path) -> int:
    """La ventana "Permisos y configuración" de Nublock.app (instancia aparte: `open -n`)."""
    import subprocess

    command = ["open", "-n", "-a", str(app), "--args", "--onboarding"]
    return subprocess.run(command, check=False).returncode
