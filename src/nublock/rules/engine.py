"""Rules Engine (FR-21): evalúa reglas `daily_limit` y `schedule` en cada tick.

Las violaciones son *edge-triggered*: se emiten cuando una regla pasa de
"se cumple" a "no se cumple", no en cada tick mientras siga sin cumplirse.
Además hay un cooldown por regla para no repetir avisos al hacer alt-tab.
"""

from collections.abc import Sequence
from datetime import datetime, time, timedelta

from nublock.config import WEEKDAYS, DailyLimitRule, Rule, RuleTarget, ScheduleRule
from nublock.events import ActivityEvent, RuleViolation
from nublock.rules.timers import DailyTimers, matches_target


class RulesEngine:
    def __init__(self, rules: Sequence[Rule], cooldown_seconds: float = 30.0) -> None:
        self._rules = list(rules)
        self._cooldown = timedelta(seconds=cooldown_seconds)
        self._violating: set[str] = set()  # ids de reglas violadas en el tick anterior
        self._last_fired: dict[str, datetime] = {}
        self._disabled_until: dict[str, datetime] = {}
        self.current_violations: list[Rule] = []  # reglas violadas en el último evaluate()

    @property
    def rules(self) -> list[Rule]:
        return list(self._rules)

    def get(self, rule_id: str) -> Rule | None:
        return next((rule for rule in self._rules if rule.id == rule_id), None)

    def disable(self, rule_id: str, until: datetime) -> None:
        """Desactiva una regla hasta `until` (ej. el fin del día)."""
        self._disabled_until[rule_id] = until

    def disabled_until(self, now: datetime) -> dict[str, datetime]:
        return {rule_id: until for rule_id, until in self._disabled_until.items() if now < until}

    def evaluate(
        self, event: ActivityEvent, timers: DailyTimers, now_local: datetime
    ) -> list[RuleViolation]:
        """Retorna las violaciones *nuevas* en este tick. `now_local` = hora local con timezone."""
        new_violations: list[RuleViolation] = []
        self.current_violations = []
        disabled = self.disabled_until(now_local)
        for rule in self._rules:
            violating = rule.id not in disabled and self._is_violating(
                rule, event, timers, now_local
            )
            if violating:
                self.current_violations.append(rule)
            was_violating = rule.id in self._violating
            if violating:
                self._violating.add(rule.id)
            else:
                self._violating.discard(rule.id)
            if not violating or was_violating:
                continue
            last = self._last_fired.get(rule.id)
            if last is not None and now_local - last < self._cooldown:
                continue
            self._last_fired[rule.id] = now_local
            new_violations.append(
                RuleViolation(
                    at=event.at,
                    rule_id=rule.id,
                    action=rule.action,
                    mode=rule.mode,
                    message=_message(rule, timers),
                )
            )
        return new_violations

    @staticmethod
    def _is_violating(
        rule: Rule, event: ActivityEvent, timers: DailyTimers, now_local: datetime
    ) -> bool:
        if event.is_idle:
            return False  # si no hay nadie usando el computador, no hay nada que avisar
        if not matches_target(
            rule.target,
            event.window.process_name,
            event.classification.productivity,
            event.classification.subcategory,
        ):
            return False
        return condition_met(rule, timers, now_local)


def condition_met(rule: Rule, timers: DailyTimers, now_local: datetime) -> bool:
    """¿La regla está "activa" ahora? (límite superado / dentro del horario), sin mirar la app."""
    if isinstance(rule, DailyLimitRule):
        return timers.seconds_for(rule.target) >= rule.limit_minutes * 60
    return is_within_schedule(rule, now_local)


def is_within_schedule(rule: ScheduleRule, now_local: datetime) -> bool:
    weekday = WEEKDAYS[now_local.weekday()]  # weekday(): lunes=0 ... domingo=6
    return weekday in rule.days and _time_in_range(now_local.time(), rule.start, rule.end)


def _time_in_range(moment: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= moment < end
    return moment >= start or moment < end  # rango que cruza medianoche, ej. 22:00–02:00


def describe_target(target: RuleTarget) -> str:
    parts = [
        f"{name}={value}"
        for name, value in (
            ("process", target.process),
            ("productivity", target.productivity),
            ("subcategory", target.subcategory),
        )
        if value is not None
    ]
    return ", ".join(parts)


def _message(rule: Rule, timers: DailyTimers) -> str:
    if isinstance(rule, DailyLimitRule):
        used = timers.seconds_for(rule.target) / 60
        return (
            f"Llegaste a tu límite diario de {rule.limit_minutes:g} min para "
            f"{describe_target(rule.target)} (llevas {used:.0f} min). [{rule.id}]"
        )
    return (
        f"{describe_target(rule.target)} no está permitido entre {rule.start:%H:%M} y "
        f"{rule.end:%H:%M}. [{rule.id}]"
    )
