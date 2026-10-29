"""Core: consume el event bus y coordina rules, interventions y focus sessions.

Corre en su propio thread (ver `app.py`), pero no sabe nada de threads: recibe eventos
con `handle()` y avanza el tiempo con `tick()`. Por eso se puede testear sin threads.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from nublock.attention.monitor import AttentionMonitor
from nublock.attention.state_machine import AttentionTransition
from nublock.blocking import Enforcer
from nublock.classifier import Classifier, WindowMatcher, matches_any
from nublock.config import Config
from nublock.events import (
    ActivityEvent,
    BusEvent,
    DisableRule,
    FalseAlarm,
    PauseAll,
    ReloadClassifier,
    RuleViolation,
    SetCameraPaused,
    StartFocus,
    StopFocus,
)
from nublock.focus import FocusSessionManager
from nublock.interventions.manager import InterventionContext, InterventionManager
from nublock.interventions.notifier import Notifier
from nublock.interventions.overlay import Overlay
from nublock.live_state import LiveState
from nublock.rules import DailyTimers, RulesEngine, condition_met, matches_target
from nublock.site_blocking import SiteBlocker
from nublock.storage import Repository
from nublock.timeutils import local_day_bounds, utc_now
from nublock.tracker.tracker import ActivityTracker

logger = logging.getLogger(__name__)

FALSE_ALARM_WINDOW = timedelta(minutes=10)  # "falsa alarma" aplica a la última alerta reciente


class Core:
    def __init__(
        self,
        config: Config,
        repository: Repository,
        notifier: Notifier,
        overlay: Overlay,
        live: LiveState,
        tracker: ActivityTracker,
        monitor: AttentionMonitor | None = None,
        clock: Callable[[], datetime] = utc_now,
        enforcer: Enforcer | None = None,
        site_blocker: SiteBlocker | None = None,
    ) -> None:
        self.config = config
        self.timers = DailyTimers()
        self.rules = RulesEngine(config.rules)
        self.interventions = InterventionManager(
            config.interventions, notifier, overlay, repository
        )
        self.focus = FocusSessionManager(config.focus_session, repository, notifier)
        self._exempt = [WindowMatcher(match) for match in config.attention.attention_exempt]
        self._repository = repository
        self._notifier = notifier
        self._overlay = overlay
        self._live = live
        self._tracker = tracker
        self._monitor = monitor
        self._clock = clock
        self._attention_event_id: int | None = None
        self._attention_state: str | None = None
        self._camera_paused = False
        self._paused_until: datetime | None = None
        self._exempt_active = False
        self._enforcer = enforcer  # None = no se bloquean apps (ej. tests de otras partes)
        self._warn_deadlines: dict[str, datetime] = {}  # rule_id -> cuándo se bloquea (warn)
        self._site_blocker = site_blocker  # None = helper de /etc/hosts no instalado

    # --- ciclo de vida ------------------------------------------------------------------

    def startup(self) -> None:
        """Retención de datos, timers de hoy, overrides y feedback previo."""
        now = self._clock()
        self._repository.close_dangling()
        cutoff = now - timedelta(days=self.config.general.data_retention_days)
        removed = self._repository.delete_data_before(cutoff)
        if removed:
            logger.info("Retención: %d filas antiguas borradas", removed)
        today = now.astimezone().date()
        day_start, day_end = local_day_bounds(today)
        sessions = self._repository.sessions_between(day_start, day_end)
        self.timers.load_sessions(today, sessions, day_start, day_end)
        self.reload_classifier()
        self.interventions.refresh_feedback(now)
        self._refresh(now)

    def shutdown(self) -> None:
        now = self._clock()
        if self.focus.active:
            self.focus.stop(now)  # una focus session no sobrevive a cerrar la app (v1)
        if self._attention_event_id is not None:
            self._repository.close_attention_event(self._attention_event_id, now, None)
            self._attention_event_id = None
        self._overlay.hide()
        if self._site_blocker is not None:
            self._site_blocker.apply([])  # sin Nublock corriendo no hay reglas que hacer cumplir

    def reload_classifier(self) -> None:
        """FR-13: los overrides del dashboard se aplican a las sesiones nuevas."""
        overrides = self._repository.load_overrides()
        self._tracker.classifier = Classifier(self.config.classification_rules, overrides)

    # --- eventos ------------------------------------------------------------------------

    def handle(self, event: BusEvent) -> None:
        now = self._clock()
        # `match` (structural pattern matching): elige el bloque según la clase del evento.
        match event:
            case ActivityEvent():
                self._on_activity(event)
            case AttentionTransition():
                self._on_attention(event)
            case StartFocus(minutes=minutes, mode=mode):
                self.focus.start(now, minutes, mode)
            case StopFocus(confirmed=confirmed):
                if self.focus.active:
                    strict = self.focus.strict
                    if self._allowed("stop_focus", strict, confirmed):
                        self.focus.stop(now)
                        self._repository.record_disable_event(now, "stop_focus", None, strict)
            case SetCameraPaused(paused=paused):
                # Sin fricción nunca: la cámara siempre se puede pausar con un clic (privacidad).
                self._camera_paused = paused
            case PauseAll(minutes=minutes, confirmed=confirmed):
                if minutes <= 0:
                    self._paused_until = None
                else:
                    strict = self.strict_active(now)
                    if self._allowed("pause_all", strict, confirmed):
                        self._paused_until = now + timedelta(minutes=minutes)
                        self._repository.record_disable_event(
                            now, "pause_all", f"{minutes:g}", strict
                        )
            case DisableRule(rule_id=rule_id, confirmed=confirmed):
                rule = self.rules.get(rule_id)
                strict = rule is not None and rule.mode == "strict"
                if rule is not None and self._allowed("disable_rule", strict, confirmed):
                    end_of_day = local_day_bounds(now.astimezone().date())[1]
                    self.rules.disable(rule_id, end_of_day)
                    self._warn_deadlines.pop(rule_id, None)
                    self._repository.record_disable_event(now, "disable_rule", rule_id, strict)
            case FalseAlarm():
                row = self._repository.mark_latest_false_alarm(now - FALSE_ALARM_WINDOW)
                logger.info(
                    "Falsa alarma marcada: %s", row.trigger if row else "(ninguna reciente)"
                )
                self.interventions.refresh_feedback(now)
            case ReloadClassifier():
                self.reload_classifier()
        self._refresh(now)

    def tick(self) -> None:
        """Avanza lo que depende del tiempo: fin de focus session y escalation."""
        now = self._clock()
        self.focus.tick(now)
        self.interventions.tick(now, self.intervention_context(now))
        if self._site_blocker is not None:
            self._site_blocker.apply(self.blocked_sites(now))  # solo escribe si cambió
        self._refresh(now)

    def paused(self, now: datetime) -> bool:
        return self._paused_until is not None and now < self._paused_until

    def strict_active(self, now: datetime) -> bool:
        """True si pausar todo requiere fricción: focus session strict o reglas strict activas."""
        disabled = self.rules.disabled_until(now)
        strict_rule = any(
            rule.mode == "strict" and rule.id not in disabled for rule in self.rules.rules
        )
        return self.focus.strict or strict_rule

    def blocked_sites(self, now: datetime) -> list[str]:
        """Dominios que deben estar bloqueados ahora en /etc/hosts (M7)."""
        if not self.config.site_blocking.enabled or self.paused(now):
            return []
        focus_blocks = self.focus.active and self.config.focus_session.block_distracting
        active_rules = []
        if not self.config.general.observe_only:
            local_now = now.astimezone()
            disabled = self.rules.disabled_until(now)
            active_rules = [
                rule
                for rule in self.rules.rules
                if rule.action in ("block", "warn")
                and rule.id not in disabled
                and condition_met(rule, self.timers, local_now)
            ]
        blocked = []
        for site in self.config.sites:
            # Un sitio no es un proceso: un target con `process` nunca coincide con un sitio.
            by_rule = any(
                matches_target(rule.target, "", site.productivity, site.subcategory)
                for rule in active_rules
            )
            by_focus = focus_blocks and site.productivity == "distracting"
            if site.always or by_focus or by_rule:
                blocked.append(site.domain)
        return blocked

    @staticmethod
    def _allowed(action: str, strict: bool, confirmed: bool) -> bool:
        """FR-23: en modo strict, desactivar exige haber pasado la fricción (FrictionGate)."""
        if strict and not confirmed:
            logger.warning("'%s' requiere confirmación (modo strict): se ignora", action)
            return False
        return True

    def intervention_context(self, now: datetime) -> InterventionContext:
        # Una focus session es un pedido explícito de interventions: aplica aunque
        # observe_only esté activo (ver DECISIONS.md).
        allowed = self.focus.active or not self.config.general.observe_only
        enabled = (
            allowed
            and not self.paused(now)
            and not self.focus.on_break(now)
            and not self._exempt_active
        )
        return InterventionContext(
            enabled=enabled,
            strict_focus=self.focus.strict,
            focus_remaining_minutes=self.focus.remaining_minutes(now),
        )

    def camera_should_run(self, now: datetime) -> bool:
        attention = self.config.attention
        return (
            attention.enabled
            and self._monitor is not None
            and not self._camera_paused
            and not self.paused(now)
            and not self.focus.on_break(now)
            and not self._exempt_active  # ej. videollamada: liberar la cámara (FR-36)
            and (self.focus.active or not attention.only_during_focus)
        )

    def _on_activity(self, event: ActivityEvent) -> None:
        local_now = event.at.astimezone()  # sin argumento: timezone local del sistema
        self.timers.add_event(local_now.date(), event)
        self._exempt_active = matches_any(self._exempt, event.window)
        for violation in self.rules.evaluate(event, self.timers, local_now):
            self._handle_violation(violation)
        self._enforce_rules(event)
        message = self.focus.check_activity(event, event.at)
        if self.focus.active and self.intervention_context(event.at).enabled:
            distracting = (
                self.config.focus_session.block_distracting
                and not event.is_idle
                and event.classification.productivity == "distracting"
            )
            blocked = distracting and self._block(event, self.focus.strict, "focus", None)
            if message:
                suffix = " Nublock la bloqueó." if blocked else ""
                self._notifier.notify("Focus session", message + suffix)
                if not blocked:
                    self._repository.record_intervention(event.at, "focus:distracting", 1, None)
        classification = event.classification
        self._live.update(
            current_app=event.window.app_name or event.window.process_name,
            current_category=f"{classification.productivity}/{classification.subcategory}"
            + (" (idle)" if event.is_idle else ""),
            today_seconds=self.timers.totals_by_productivity(),
        )

    def _rules_can_intervene(self, now: datetime) -> bool:
        return not self.config.general.observe_only and not self.paused(now)

    def _handle_violation(self, violation: RuleViolation) -> None:
        if not self._rules_can_intervene(violation.at):
            # FR-24: se registra en el log pero no se interviene.
            logger.info("observe-only/pausa: regla %s violada, no se interviene", violation.rule_id)
            return
        rule = self.rules.get(violation.rule_id)
        message = violation.message
        verb = "se cerrará" if violation.mode == "strict" else "se ocultará"
        if violation.action == "warn" and rule is not None:
            message += f" Tienes {rule.grace_seconds:g} s para salir o la app {verb}."
        elif violation.action == "block":
            message += f" La app {verb}."
        self._notifier.notify("Regla de Nublock", message)
        self._repository.record_intervention(
            violation.at, trigger=f"rule:{violation.rule_id}", level=1, rule_id=violation.rule_id
        )

    def _enforce_rules(self, event: ActivityEvent) -> None:
        """FR-22: `block` bloquea ya; `warn` bloquea si sigues ahí tras `grace_seconds`."""
        if not self._rules_can_intervene(event.at):
            self._warn_deadlines.clear()
            return
        violating = {rule.id: rule for rule in self.rules.current_violations}
        for rule_id in list(self._warn_deadlines):
            if rule_id not in violating:  # saliste de la app a tiempo: se cancela el bloqueo
                del self._warn_deadlines[rule_id]
        for rule in violating.values():
            strict = rule.mode == "strict"
            if rule.action == "block":
                self._block(event, strict, f"rule:{rule.id}", rule.id)
            elif rule.action == "warn":
                grace = timedelta(seconds=rule.grace_seconds)
                deadline = self._warn_deadlines.setdefault(rule.id, event.at + grace)
                if event.at >= deadline and self._block(event, strict, f"rule:{rule.id}", rule.id):
                    name = event.window.app_name or event.window.process_name
                    verb = "cerró" if strict else "ocultó"
                    self._notifier.notify(
                        "Regla de Nublock",
                        f"Se acabó el tiempo: Nublock {verb} {name}. [{rule.id}]",
                    )

    def _block(self, event: ActivityEvent, strict: bool, reason: str, rule_id: str | None) -> bool:
        """FR-50: oculta (soft) o cierra (strict) la app activa. Retorna True si lo hizo."""
        if self._enforcer is None:
            return False
        action = self._enforcer.enforce(event.window, strict, event.at)
        if action is None:
            return False
        self._repository.record_intervention(event.at, f"block:{reason}", 1, rule_id)
        return True

    def _on_attention(self, transition: AttentionTransition) -> None:
        if self._attention_event_id is not None:
            self._repository.close_attention_event(
                self._attention_event_id, transition.started_at, transition.previous_confidence
            )
        self._attention_event_id = self._repository.open_attention_event(
            transition.started_at, transition.state
        )
        self._attention_state = transition.state
        self.interventions.on_transition(transition)

    def _refresh(self, now: datetime) -> None:
        if self._monitor is not None:
            self._monitor.set_active(self.camera_should_run(now))
        status = self.focus.status(now)
        self._live.update(
            attention_state=self._attention_state,
            camera_open=self._monitor.camera_open if self._monitor else False,
            camera_paused=self._camera_paused,
            focus_active=status.active,
            focus_mode=status.mode,
            focus_ends_at=status.ends_at,
            on_break_until=status.on_break_until,
            paused_until=self._paused_until if self.paused(now) else None,
            strict_active=self.strict_active(now),
            disabled_rules=self.rules.disabled_until(now),
            blocked_sites=self.blocked_sites(now) if self._site_blocker else [],
        )
