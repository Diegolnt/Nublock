"""`nublock report today` (FR-60): tiempo por categoría y top apps, leído desde SQLite."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime

from nublock.storage import ActivitySession
from nublock.timeutils import overlap_seconds

PRODUCTIVITY_ORDER = ("productive", "neutral", "distracting")


@dataclass
class AppUsage:
    name: str
    seconds: float
    category: str  # "productivity/subcategory" con más tiempo en esta app


@dataclass
class DailyReport:
    day: date
    active_seconds: float = 0.0
    idle_seconds: float = 0.0
    by_productivity: dict[str, float] = field(default_factory=dict)
    by_subcategory: dict[tuple[str, str], float] = field(default_factory=dict)
    top_apps: list[AppUsage] = field(default_factory=list)


def build_daily_report(
    day: date,
    sessions: Iterable[ActivitySession],
    day_start: datetime,
    day_end: datetime,
    top_n: int = 10,
) -> DailyReport:
    """Agrega sesiones recortadas a [day_start, day_end). Idle se cuenta aparte."""
    report = DailyReport(day=day)
    by_productivity: defaultdict[str, float] = defaultdict(float)
    by_subcategory: defaultdict[tuple[str, str], float] = defaultdict(float)
    by_app: defaultdict[str, defaultdict[str, float]] = defaultdict(lambda: defaultdict(float))

    for session in sessions:
        # ended_at es NULL solo en los primeros segundos de una sesión (antes del heartbeat).
        end = session.ended_at or session.started_at
        seconds = overlap_seconds(session.started_at, end, day_start, day_end)
        if seconds <= 0:
            continue
        if session.is_idle:
            report.idle_seconds += seconds
            continue
        subcategory = session.subcategory or "-"
        report.active_seconds += seconds
        by_productivity[session.productivity] += seconds
        by_subcategory[(session.productivity, subcategory)] += seconds
        app = session.app_name or session.process_name
        by_app[app][f"{session.productivity}/{subcategory}"] += seconds

    report.by_productivity = dict(by_productivity)
    report.by_subcategory = dict(by_subcategory)
    apps = [
        AppUsage(name=app, seconds=sum(cats.values()), category=max(cats, key=cats.__getitem__))
        for app, cats in by_app.items()
    ]
    apps.sort(key=lambda usage: usage.seconds, reverse=True)
    report.top_apps = apps[:top_n]
    return report


def format_duration(seconds: float) -> str:
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def format_report(report: DailyReport) -> str:
    lines = [
        f"Nublock — reporte del {report.day.isoformat()}",
        f"Tiempo activo: {format_duration(report.active_seconds)}"
        f"   Idle: {format_duration(report.idle_seconds)}",
        "",
    ]
    if report.active_seconds == 0:
        lines.append("Sin actividad registrada hoy. Corre `python -m nublock run` para empezar.")
        return "\n".join(lines)

    lines.append("Tiempo por categoría:")
    for productivity in PRODUCTIVITY_ORDER:
        seconds = report.by_productivity.get(productivity, 0.0)
        share = 100 * seconds / report.active_seconds
        lines.append(f"  {productivity:<14}{format_duration(seconds):>9}  {share:5.1f}%")
        subcategories = sorted(
            (
                (sub, secs)
                for (prod, sub), secs in report.by_subcategory.items()
                if prod == productivity
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        for subcategory, secs in subcategories:
            # 4 + 14 + 7 = 25 columnas: alinea con la línea de productivity (2 + 14 + 9).
            lines.append(f"    {subcategory[:13]:<14}{format_duration(secs):>7}")

    lines += ["", "Top apps:"]
    for rank, usage in enumerate(report.top_apps, start=1):
        duration = format_duration(usage.seconds)
        lines.append(f"  {rank:>2}. {usage.name[:28]:<28}{duration:>9}  {usage.category}")
    return "\n".join(lines)
