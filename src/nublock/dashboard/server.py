"""Dashboard local con FastAPI + Jinja2 (FR-61). Escucha solo en 127.0.0.1 (privacidad)."""

import csv
import io
import logging
import threading
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

import uvicorn
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from nublock.config import Config, Mode, Productivity
from nublock.dashboard.data import (
    EXPORT_FIELDS,
    build_rules,
    build_today,
    build_week,
    export_activity,
)
from nublock.events import (
    BusEvent,
    DisableRule,
    FalseAlarm,
    PauseAll,
    ReloadClassifier,
    SetCameraPaused,
    StartFocus,
    StopFocus,
)
from nublock.friction import FrictionAction, FrictionGate, FrictionRequest
from nublock.live_state import LiveState
from nublock.report import format_duration
from nublock.storage import Repository
from nublock.timeutils import local_day_bounds, utc_now

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"  # nunca 0.0.0.0: el dashboard no debe ser visible desde la red
LOCAL_HOSTNAMES = {"127.0.0.1", "localhost"}
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.filters["duration"] = format_duration


FRICTION_LABELS: dict[str, str] = {
    "pause_all": "Pausar todo {target} min",
    "stop_focus": "Terminar la focus session strict",
    "disable_rule": "Desactivar la regla {target} por hoy",
}


def create_app(
    db_path: Path,
    publish: Callable[[BusEvent], None] | None = None,
    live: LiveState | None = None,
    config: Config | None = None,
    friction: FrictionGate | None = None,
) -> FastAPI:
    """`publish`/`live`/`friction` existen solo si el dashboard corre dentro de `nublock run`."""
    app = FastAPI(title="Nublock", docs_url=None, redoc_url=None, openapi_url=None)
    # Rechaza requests cuyo header Host no sea local (protege contra DNS rebinding).
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=sorted(LOCAL_HOSTNAMES))

    def same_origin(request: Request) -> None:
        """Bloquea POSTs enviados por otras páginas web (CSRF, Cross-Site Request Forgery)."""
        origin = request.headers.get("origin")
        if origin and urlparse(origin).hostname not in LOCAL_HOSTNAMES:
            raise HTTPException(status_code=403, detail="origen no permitido")

    def send(event: BusEvent) -> RedirectResponse:
        if publish is None:
            raise HTTPException(status_code=409, detail="Nublock no está corriendo (`nublock run`)")
        publish(event)
        # 303 See Other: después de un POST, el navegador hace GET a la página (patrón PRG).
        return RedirectResponse("/", status_code=303)

    guarded = [Depends(same_origin)]

    def to_friction(action: FrictionAction, target: str | None = None) -> RedirectResponse:
        """Modo strict (FR-23): en vez de ejecutar, manda a la página de confirmación."""
        query = f"?action={action}" + (f"&target={target}" if target else "")
        return RedirectResponse("/friction" + query, status_code=303)

    def friction_page(
        request: Request, pending: FrictionRequest, error: str | None = None
    ) -> HTMLResponse:
        assert friction is not None
        label = FRICTION_LABELS[pending.action].format(target=pending.target)
        context = {
            "label": label,
            "token": pending.token,
            "wait": friction.remaining(pending),
            "phrase": friction.phrase,
            "error": error,
        }
        return TEMPLATES.TemplateResponse(request, "friction.html", context)

    @app.get("/", response_class=HTMLResponse)
    def today(request: Request) -> HTMLResponse:
        repository = Repository(db_path)
        try:
            view = build_today(repository, date.today(), utc_now())
            rules = build_rules(config.rules, repository, date.today()) if config else []
            day_start = local_day_bounds(date.today())[0]
            disabled_today = repository.count_disable_events(day_start)
            disabled_week = repository.count_disable_events(day_start - timedelta(days=6))
        finally:
            repository.close()
        context = {
            "view": view,
            "live": live.snapshot() if live else None,
            "running": publish is not None,
            "rules": rules,
            "disabled_today": disabled_today,
            "disabled_week": disabled_week,
        }
        return TEMPLATES.TemplateResponse(request, "today.html", context)

    @app.get("/week", response_class=HTMLResponse)
    def week(request: Request) -> HTMLResponse:
        repository = Repository(db_path)
        try:
            days = build_week(repository, date.today())
        finally:
            repository.close()
        max_total = max((day.total for day in days), default=0) or 1
        return TEMPLATES.TemplateResponse(
            request, "week.html", {"days": days, "max_total": max_total}
        )

    @app.get("/api/today")
    def api_today() -> dict[str, object]:
        repository = Repository(db_path)
        try:
            view = build_today(repository, date.today(), utc_now())
        finally:
            repository.close()
        return {
            "day": view.day.isoformat(),
            "active_seconds": view.report.active_seconds,
            "idle_seconds": view.report.idle_seconds,
            "by_productivity": view.report.by_productivity,
            "top_apps": [
                {"name": a.name, "seconds": a.seconds, "category": a.category}
                for a in view.report.top_apps
            ],
            "distractions": view.distractions,
            "avg_refocus_seconds": view.avg_refocus_seconds,
            "uncategorized": [{"process": p, "seconds": s} for p, s in view.uncategorized],
        }

    @app.post("/classify", dependencies=guarded)
    def classify(
        process_name: Annotated[str, Form(min_length=1)],
        productivity: Annotated[Productivity, Form()],
        subcategory: Annotated[str, Form()] = "",
    ) -> RedirectResponse:
        repository = Repository(db_path)
        try:
            repository.add_override(
                "process", process_name, productivity, subcategory.strip() or None, utc_now()
            )
        finally:
            repository.close()
        if publish is not None:
            publish(ReloadClassifier())
        return RedirectResponse("/", status_code=303)

    @app.post("/focus/start", dependencies=guarded)
    def focus_start(
        mode: Annotated[Mode, Form()] = "soft", minutes: Annotated[int | None, Form(ge=1)] = None
    ) -> RedirectResponse:
        return send(StartFocus(minutes=minutes, mode=mode))

    @app.post("/focus/stop", dependencies=guarded)
    def focus_stop() -> RedirectResponse:
        snapshot = live.snapshot() if live else None
        if snapshot and snapshot.focus_active and snapshot.focus_mode == "strict":
            return to_friction("stop_focus")
        return send(StopFocus())

    @app.post("/camera", dependencies=guarded)
    def camera(paused: Annotated[bool, Form()]) -> RedirectResponse:
        return send(SetCameraPaused(paused))

    @app.post("/pause", dependencies=guarded)
    def pause(minutes: Annotated[float, Form(ge=0)]) -> RedirectResponse:
        if minutes > 0 and live is not None and live.snapshot().strict_active:
            return to_friction("pause_all", f"{minutes:g}")
        return send(PauseAll(minutes))

    @app.post("/rules/disable", dependencies=guarded)
    def disable_rule(rule_id: Annotated[str, Form(min_length=1)]) -> RedirectResponse:
        rule = next((r for r in config.rules if r.id == rule_id), None) if config else None
        if rule is None:
            raise HTTPException(status_code=404, detail="regla desconocida")
        if rule.mode == "strict":
            return to_friction("disable_rule", rule_id)
        return send(DisableRule(rule_id))

    @app.get("/friction", response_class=HTMLResponse)
    def friction_start(
        request: Request, action: FrictionAction, target: str | None = None
    ) -> HTMLResponse:
        if friction is None or publish is None:
            raise HTTPException(status_code=409, detail="Nublock no está corriendo (`nublock run`)")
        return friction_page(request, friction.request(action, target))

    @app.post("/friction/confirm", dependencies=guarded, response_model=None)
    def friction_confirm(
        request: Request,
        token: Annotated[str, Form()],
        phrase: Annotated[str, Form()] = "",
    ) -> HTMLResponse | RedirectResponse:
        if friction is None:
            raise HTTPException(status_code=409, detail="Nublock no está corriendo (`nublock run`)")
        result = friction.confirm(token, phrase)
        if not result.ok:
            if result.request is None:
                raise HTTPException(status_code=410, detail=result.error)
            error = result.error or f"Todavía faltan {result.wait_seconds:.0f} s."
            return friction_page(request, result.request, error)
        assert result.request is not None
        action, target = result.request.action, result.request.target
        if action == "pause_all":
            return send(PauseAll(float(target or 0), confirmed=True))
        if action == "stop_focus":
            return send(StopFocus(confirmed=True))
        return send(DisableRule(target or "", confirmed=True))

    @app.get("/export.json")
    def export_json(days: Annotated[int, Query(ge=1, le=365)] = 7) -> dict[str, object]:
        """FR-62: datos agregados (tiempo por día y app), sin títulos de ventana."""
        repository = Repository(db_path)
        try:
            rows = export_activity(repository, date.today(), days)
        finally:
            repository.close()
        return {"generated_at": utc_now().isoformat(), "days": days, "activity": rows}

    @app.get("/export.csv")
    def export_csv(days: Annotated[int, Query(ge=1, le=365)] = 7) -> Response:
        repository = Repository(db_path)
        try:
            rows = export_activity(repository, date.today(), days)
        finally:
            repository.close()
        buffer = io.StringIO()  # un "archivo" de texto en memoria
        writer = csv.DictWriter(buffer, fieldnames=EXPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        filename = f"nublock-{date.today().isoformat()}-{days}d.csv"
        return Response(
            buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/feedback/false-alarm", dependencies=guarded)
    def false_alarm() -> RedirectResponse:
        return send(FalseAlarm())

    @app.post("/data/delete", dependencies=guarded)
    def delete_data(confirm: Annotated[Literal["BORRAR"], Form()]) -> RedirectResponse:
        # FR-72: `confirm` debe ser exactamente "BORRAR" (si no, FastAPI responde 422).
        repository = Repository(db_path)
        try:
            repository.delete_all_data()
        finally:
            repository.close()
        logger.warning("Historial borrado desde el dashboard")
        return RedirectResponse("/", status_code=303)

    return app


class DashboardServer:
    """Corre uvicorn en un thread propio (`start`/`stop`)."""

    def __init__(self, app: FastAPI, port: int) -> None:
        self.url = f"http://{HOST}:{port}"
        config = uvicorn.Config(app, host=HOST, port=port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._server.run, name="dashboard", daemon=True)
        self._thread.start()
        logger.info("Dashboard en %s", self.url)

    def stop(self) -> None:
        self._server.should_exit = True  # uvicorn revisa este flag y cierra limpio
        if self._thread is not None:
            self._thread.join(timeout=5)
