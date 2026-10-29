"""Timers (FR-20) y rules engine: daily_limit y schedule (FR-21)."""

from datetime import date, datetime, timedelta, timezone

import pytest
from helpers import make_window

from nublock.classifier import Classification
from nublock.config import DailyLimitRule, RuleTarget, ScheduleRule
from nublock.events import ActivityEvent
from nublock.rules import DailyTimers, RulesEngine, is_within_schedule, matches_target

SANTIAGO = timezone(timedelta(hours=-3))
THURSDAY_10AM = datetime(2026, 10, 29, 10, 0, tzinfo=SANTIAGO)  # 2026-10-29 es jueves
SOCIAL = Classification("distracting", "social")
DEV = Classification("productive", "dev")


def event(
    classification: Classification,
    process: str = "Safari",
    seconds: float = 1.0,
    is_idle: bool = False,
) -> ActivityEvent:
    return ActivityEvent(
        at=THURSDAY_10AM,
        seconds=seconds,
        window=make_window(process),
        classification=classification,
        is_idle=is_idle,
    )


def daily_limit(limit_minutes: float = 1, **target: str) -> DailyLimitRule:
    return DailyLimitRule.model_validate(
        {
            "id": "limit",
            "type": "daily_limit",
            "target": target or {"subcategory": "social"},
            "limit_minutes": limit_minutes,
        }
    )


def schedule(
    start: str = "09:00", end: str = "13:00", days: list[str] | None = None
) -> ScheduleRule:
    return ScheduleRule.model_validate(
        {
            "id": "focus",
            "type": "schedule",
            "days": days or ["mon", "tue", "wed", "thu", "fri"],
            "start": start,
            "end": end,
            "target": {"productivity": "distracting"},
        }
    )


class Simulation:
    """Alimenta timers + engine como lo hace NublockApp, un tick por segundo."""

    def __init__(self, engine: RulesEngine, start: datetime = THURSDAY_10AM) -> None:
        self.engine = engine
        self.timers = DailyTimers()
        self.now = start
        self.fired: list[tuple[float, str]] = []  # (segundos desde el inicio, rule_id)
        self._start = start

    def run(self, classification: Classification, seconds: int, process: str = "Safari") -> None:
        for _ in range(seconds):
            self.now += timedelta(seconds=1)
            ev = event(classification, process)
            self.timers.add_event(self.now.date(), ev)
            for violation in self.engine.evaluate(ev, self.timers, self.now):
                elapsed = (self.now - self._start).total_seconds()
                self.fired.append((elapsed, violation.rule_id))


# --- Timers --------------------------------------------------------------------


def test_matches_target_requires_all_keys() -> None:
    target = RuleTarget(process="safari", subcategory="social")
    assert matches_target(target, "Safari", "distracting", "social")
    assert not matches_target(target, "Google Chrome", "distracting", "social")
    assert not matches_target(target, "Safari", "distracting", "video")


def test_timers_accumulate_by_target_and_ignore_idle() -> None:
    timers = DailyTimers()
    day = date(2026, 10, 29)
    timers.add_event(day, event(SOCIAL, "Safari", seconds=30))
    timers.add_event(day, event(SOCIAL, "Google Chrome", seconds=20))
    timers.add_event(day, event(DEV, "Code", seconds=100))
    timers.add_event(day, event(SOCIAL, "Safari", seconds=999, is_idle=True))
    assert timers.seconds_for(RuleTarget(subcategory="social")) == 50
    assert timers.seconds_for(RuleTarget(process="safari")) == 30
    assert timers.seconds_for(RuleTarget(productivity="productive")) == 100
    assert timers.seconds_for(RuleTarget(productivity="neutral")) == 0


def test_timers_reset_on_new_day() -> None:
    timers = DailyTimers()
    timers.add_event(date(2026, 10, 29), event(SOCIAL, seconds=500))
    timers.add_event(date(2026, 10, 30), event(SOCIAL, seconds=5))
    assert timers.seconds_for(RuleTarget(subcategory="social")) == 5


# --- daily_limit -----------------------------------------------------------------


def test_daily_limit_fires_once_when_limit_is_reached() -> None:
    sim = Simulation(RulesEngine([daily_limit(limit_minutes=1)]))
    sim.run(SOCIAL, 59)
    assert sim.fired == []
    sim.run(SOCIAL, 120)  # sigue en social: no se repite en cada tick
    assert sim.fired == [(60, "limit")]


def test_daily_limit_ignores_time_outside_target() -> None:
    sim = Simulation(RulesEngine([daily_limit(limit_minutes=1)]))
    sim.run(DEV, 600)
    sim.run(SOCIAL, 30)
    assert sim.fired == []


def test_daily_limit_only_fires_while_using_the_target() -> None:
    sim = Simulation(RulesEngine([daily_limit(limit_minutes=1)], cooldown_seconds=30))
    sim.run(SOCIAL, 60)
    sim.run(DEV, 100)  # límite ya superado, pero estoy trabajando: no avisa
    assert sim.fired == [(60, "limit")]
    sim.run(SOCIAL, 1)  # vuelvo a social después del cooldown: avisa de nuevo
    assert sim.fired == [(60, "limit"), (161, "limit")]


def test_cooldown_prevents_repeat_on_quick_alt_tab() -> None:
    sim = Simulation(RulesEngine([daily_limit(limit_minutes=1)], cooldown_seconds=30))
    sim.run(SOCIAL, 60)
    sim.run(DEV, 5)
    sim.run(SOCIAL, 5)  # vuelve a los 5 s: dentro del cooldown
    assert sim.fired == [(60, "limit")]


def test_idle_activity_never_violates() -> None:
    engine = RulesEngine([daily_limit(limit_minutes=1)])
    timers = DailyTimers()
    timers.add_event(THURSDAY_10AM.date(), event(SOCIAL, seconds=3600))
    assert engine.evaluate(event(SOCIAL, is_idle=True), timers, THURSDAY_10AM) == []
    assert len(engine.evaluate(event(SOCIAL), timers, THURSDAY_10AM)) == 1


def test_violation_carries_rule_data_and_message() -> None:
    rule = daily_limit(limit_minutes=1).model_copy(update={"action": "block", "mode": "strict"})
    sim = Simulation(RulesEngine([rule]))
    timers = sim.timers
    timers.add_event(THURSDAY_10AM.date(), event(SOCIAL, seconds=61))
    (violation,) = sim.engine.evaluate(event(SOCIAL), timers, THURSDAY_10AM)
    assert (violation.rule_id, violation.action, violation.mode) == ("limit", "block", "strict")
    assert "límite diario de 1 min" in violation.message


# --- schedule ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("local_time", "expected"),
    [
        (datetime(2026, 10, 29, 10, 0, tzinfo=SANTIAGO), True),  # jueves dentro
        (datetime(2026, 10, 29, 9, 0, tzinfo=SANTIAGO), True),  # start es inclusivo
        (datetime(2026, 10, 29, 13, 0, tzinfo=SANTIAGO), False),  # end es exclusivo
        (datetime(2026, 10, 29, 8, 59, tzinfo=SANTIAGO), False),
        (datetime(2026, 10, 31, 10, 0, tzinfo=SANTIAGO), False),  # sábado
    ],
)
def test_schedule_window(local_time: datetime, expected: bool) -> None:
    assert is_within_schedule(schedule(), local_time) is expected


@pytest.mark.parametrize(("hour", "expected"), [(23, True), (1, True), (3, False), (21, False)])
def test_schedule_crossing_midnight(hour: int, expected: bool) -> None:
    rule = schedule("22:00", "02:00", days=["mon", "tue", "wed", "thu", "fri", "sat", "sun"])
    assert is_within_schedule(rule, datetime(2026, 10, 29, hour, 0, tzinfo=SANTIAGO)) is expected


def test_schedule_rule_fires_for_target_inside_window() -> None:
    sim = Simulation(RulesEngine([schedule()]))
    sim.run(DEV, 10)
    assert sim.fired == []
    sim.run(SOCIAL, 10)
    assert sim.fired == [(11, "focus")]


def test_schedule_rule_does_not_fire_outside_window() -> None:
    sim = Simulation(
        RulesEngine([schedule()]), start=datetime(2026, 10, 29, 14, 0, tzinfo=SANTIAGO)
    )
    sim.run(SOCIAL, 60)
    assert sim.fired == []


def test_schedule_rule_fires_when_window_starts() -> None:
    start = datetime(2026, 10, 29, 8, 59, 30, tzinfo=SANTIAGO)
    sim = Simulation(RulesEngine([schedule()]), start=start)
    sim.run(SOCIAL, 60)  # ya estaba en social cuando empieza el horario de foco
    assert sim.fired == [(30, "focus")]


def test_multiple_rules_are_independent() -> None:
    sim = Simulation(RulesEngine([daily_limit(limit_minutes=1), schedule()]))
    sim.run(SOCIAL, 61)
    assert sim.fired == [(1, "focus"), (60, "limit")]
