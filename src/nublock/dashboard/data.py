"""Arma los datos (view models) que muestran las páginas del dashboard (FR-61)."""

import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from nublock.attention.states import DISTRACTED_STATES
from nublock.config import DailyLimitRule, Rule
from nublock.report import DailyReport, build_daily_report
from nublock.rules import DailyTimers, describe_target
from nublock.storage import FocusSessionRow, InterventionRow, Repository
from nublock.timeutils import local_day_bounds, overlap_seconds


@dataclass(frozen=True)
class TimelineBlock:
    left_pct: float  # posición dentro del día (0–100)
    width_pct: float
    kind: str  # productive / neutral / distracting / idle
    label: str  # tooltip


@dataclass(frozen=True)
class TodayView:
    day: date
    report: DailyReport
    timeline: list[TimelineBlock]
    uncategorized: list[tuple[str, float]]  # (process_name, segundos)
    distractions: int  # episodios LOOKING_AWAY / LOOKING_DOWN / PHONE
    attention_seconds: dict[str, float]  # segundos por estado de atención
    interventions: list[InterventionRow]
    avg_refocus_seconds: float | None
    false_alarms: int
    focus_sessions: list[FocusSessionRow]


@dataclass(frozen=True)
class DayTotals:
    day: date
    seconds: dict[str, float]  # por productivity

    @property
    def total(self) -> float:
        return sum(self.seconds.values())


def build_today(repository: Repository, day: date, now: datetime) -> TodayView:
    day_start, day_end = local_day_bounds(day)
    window_end = min(day_end, now)
    sessions = repository.sessions_between(day_start, day_end)
    report = build_daily_report(day, sessions, day_start, day_end)

    timeline: list[TimelineBlock] = []
    uncategorized: defaultdict[str, float] = defaultdict(float)
    day_seconds = (day_end - day_start).total_seconds()
    for session in sessions:
        start = max(session.started_at, day_start)
        end = min(session.ended_at or session.started_at, day_end)
        if end <= start:
            continue
        kind = "idle" if session.is_idle else session.productivity
        local_start, local_end = start.astimezone(), end.astimezone()
        timeline.append(
            TimelineBlock(
                left_pct=100 * (start - day_start).total_seconds() / day_seconds,
                width_pct=100 * (end - start).total_seconds() / day_seconds,
                kind=kind,
                label=f"{local_start:%H:%M}–{local_end:%H:%M} "
                f"{session.app_name or session.process_name} ({kind}/{session.subcategory})",
            )
        )
        if not session.is_idle and session.subcategory == "uncategorized":
            uncategorized[session.process_name] += (end - start).total_seconds()

    attention_seconds: defaultdict[str, float] = defaultdict(float)
    distractions = 0
    for event in repository.attention_events_between(day_start, day_end):
        end = event.ended_at or window_end
        attention_seconds[event.state] += overlap_seconds(
            event.started_at, end, day_start, window_end
        )
        if event.state in DISTRACTED_STATES:
            distractions += 1

    interventions = repository.interventions_between(day_start, day_end)
    refocus = [row.refocus_seconds for row in interventions if row.refocus_seconds is not None]
    return TodayView(
        day=day,
        report=report,
        timeline=timeline,
        uncategorized=sorted(uncategorized.items(), key=lambda item: item[1], reverse=True),
        distractions=distractions,
        attention_seconds=dict(attention_seconds),
        interventions=interventions,
        avg_refocus_seconds=statistics.mean(refocus) if refocus else None,
        false_alarms=sum(1 for row in interventions if row.user_feedback == "false_alarm"),
        focus_sessions=repository.focus_sessions_between(day_start, day_end),
    )


def build_week(repository: Repository, last_day: date, days: int = 7) -> list[DayTotals]:
    result = []
    for offset in range(days - 1, -1, -1):
        day = last_day - timedelta(days=offset)
        day_start, day_end = local_day_bounds(day)
        report = build_daily_report(
            day, repository.sessions_between(day_start, day_end), day_start, day_end
        )
        result.append(DayTotals(day=day, seconds=report.by_productivity))
    return result


@dataclass(frozen=True)
class RuleRow:
    id: str
    summary: str
    action: str
    mode: str
    used_minutes: float | None  # solo daily_limit
    limit_minutes: float | None


def build_rules(rules: Sequence[Rule], repository: Repository, day: date) -> list[RuleRow]:
    """Reglas del config con su uso de hoy (para la sección "Reglas" del dashboard)."""
    day_start, day_end = local_day_bounds(day)
    timers = DailyTimers()
    timers.load_sessions(day, repository.sessions_between(day_start, day_end), day_start, day_end)
    rows = []
    for rule in rules:
        target = describe_target(rule.target)
        if isinstance(rule, DailyLimitRule):
            rows.append(
                RuleRow(
                    id=rule.id,
                    summary=f"máximo {rule.limit_minutes:g} min al día · {target}",
                    action=rule.action,
                    mode=rule.mode,
                    used_minutes=timers.seconds_for(rule.target) / 60,
                    limit_minutes=rule.limit_minutes,
                )
            )
        else:
            days = ", ".join(rule.days)
            summary = f"{days} {rule.start:%H:%M}–{rule.end:%H:%M} · {target}"
            rows.append(RuleRow(rule.id, summary, rule.action, rule.mode, None, None))
    return rows


EXPORT_FIELDS = (
    "date",
    "process_name",
    "app_name",
    "productivity",
    "subcategory",
    "is_idle",
    "seconds",
)


def export_activity(repository: Repository, last_day: date, days: int) -> list[dict[str, object]]:
    """FR-62: tiempo agregado por día y app (sin títulos de ventana ni timestamps finos)."""
    rows: list[dict[str, object]] = []
    for offset in range(days - 1, -1, -1):
        day = last_day - timedelta(days=offset)
        day_start, day_end = local_day_bounds(day)
        totals: defaultdict[tuple[str, str | None, str, str | None, bool], float] = defaultdict(
            float
        )
        for session in repository.sessions_between(day_start, day_end):
            end = session.ended_at or session.started_at
            seconds = overlap_seconds(session.started_at, end, day_start, day_end)
            key = (
                session.process_name,
                session.app_name,
                session.productivity,
                session.subcategory,
                session.is_idle,
            )
            totals[key] += seconds
        for (process, app, productivity, subcategory, is_idle), seconds in sorted(totals.items()):
            if seconds > 0:
                values = (
                    day.isoformat(),
                    process,
                    app,
                    productivity,
                    subcategory,
                    is_idle,
                    round(seconds, 1),
                )
                rows.append(dict(zip(EXPORT_FIELDS, values, strict=True)))
    return rows
