"""M6 en el Core: acciones block/warn, focus sessions y fricción del modo strict."""

from dataclasses import dataclass
from datetime import timedelta

from helpers import NOON, FakeClock, RecordingNotifier, make_window

from nublock.app import NublockApp
from nublock.blocking import Enforcer
from nublock.config import Config
from nublock.events import DisableRule, PauseAll, SetCameraPaused, StartFocus, StopFocus
from nublock.storage import Repository
from nublock.tracker.platform.fake import FakeAppBlocker, FakeWindowProvider

INSTAGRAM = make_window("Instagram", pid=42)
CODE = make_window("Code", pid=7)


@dataclass
class Rig:
    app: NublockApp
    clock: FakeClock
    notifier: RecordingNotifier
    provider: FakeWindowProvider
    blocker: FakeAppBlocker

    def run(self, seconds: int) -> None:
        for _ in range(seconds):
            self.app.tick()
            self.clock.advance(1)


def make_rig(
    repo: Repository,
    action: str = "block",
    mode: str = "soft",
    observe_only: bool = False,
    limit_minutes: float = 1,
) -> Rig:
    config = Config.model_validate(
        {
            "general": {"observe_only": observe_only},
            "classification_rules": [
                {
                    "match": {"process": "Instagram"},
                    "productivity": "distracting",
                    "subcategory": "social",
                }
            ],
            "rules": [
                {
                    "id": "social-daily-limit",
                    "type": "daily_limit",
                    "target": {"subcategory": "social"},
                    "limit_minutes": limit_minutes,
                    "action": action,
                    "mode": mode,
                    "grace_seconds": 20,
                }
            ],
        }
    )
    clock = FakeClock(NOON)
    notifier = RecordingNotifier()
    blocker = FakeAppBlocker()
    provider = FakeWindowProvider(INSTAGRAM)
    enforcer = Enforcer(blocker, config.blocking, own_pid=1)
    app = NublockApp(config, provider, repo, notifier, clock=clock, enforcer=enforcer)
    app.startup()
    return Rig(app, clock, notifier, provider, blocker)


def test_dod_m6_exceeding_social_limit_hides_the_app(repo: Repository) -> None:
    """DoD M6: superar social-daily-limit cierra/minimiza la app."""
    rig = make_rig(repo, action="block", mode="soft")
    rig.run(60)
    assert rig.blocker.actions == []  # todavía bajo el límite
    rig.run(1)
    assert rig.blocker.actions == [("hide", 42)]
    assert "La app se ocultará" in rig.notifier.messages[0][1]
    triggers = [row.trigger for row in repo.interventions_between(NOON, NOON + timedelta(hours=1))]
    assert triggers == ["rule:social-daily-limit", "block:rule:social-daily-limit"]


def test_strict_block_terminates(repo: Repository) -> None:
    rig = make_rig(repo, action="block", mode="strict")
    rig.run(62)
    assert rig.blocker.actions[0] == ("terminate", 42)


def test_reopening_a_blocked_app_blocks_it_again(repo: Repository) -> None:
    rig = make_rig(repo)
    rig.run(61)
    rig.provider.window = CODE
    rig.run(5)
    rig.provider.window = INSTAGRAM  # la vuelve a abrir
    rig.run(1)
    assert rig.blocker.actions == [("hide", 42), ("hide", 42)]


def test_warn_gives_grace_then_blocks(repo: Repository) -> None:
    rig = make_rig(repo, action="warn")
    rig.run(61)
    assert rig.blocker.actions == []
    assert "Tienes 20 s para salir" in rig.notifier.messages[0][1]
    rig.run(19)
    assert rig.blocker.actions == []
    rig.run(2)
    assert rig.blocker.actions == [("hide", 42)]
    assert "Se acabó el tiempo" in rig.notifier.messages[-1][1]


def test_warn_is_cancelled_if_you_leave_in_time(repo: Repository) -> None:
    rig = make_rig(repo, action="warn")
    rig.run(65)
    rig.provider.window = CODE  # sale a tiempo
    rig.run(30)
    assert rig.blocker.actions == []


def test_observe_only_never_blocks(repo: Repository) -> None:
    rig = make_rig(repo, observe_only=True)
    rig.run(120)
    assert rig.blocker.actions == []


def test_focus_session_blocks_distracting_apps(repo: Repository) -> None:
    rig = make_rig(repo, observe_only=True, limit_minutes=600)
    rig.provider.window = CODE
    rig.app.bus.publish(StartFocus(mode="strict"))
    rig.run(2)
    rig.provider.window = INSTAGRAM
    rig.run(1)
    assert rig.blocker.actions == [("terminate", 42)]
    assert rig.notifier.messages[-1][1].endswith("Nublock la bloqueó.")


# --- Fricción del modo strict (FR-23) ---------------------------------------------------


def test_strict_pause_requires_confirmation(repo: Repository) -> None:
    rig = make_rig(repo, mode="strict")
    rig.app.bus.publish(PauseAll(15))  # desde un cliente que no pasó la fricción
    rig.run(1)
    assert rig.app.live.snapshot().paused_until is None
    rig.app.bus.publish(PauseAll(15, confirmed=True))
    rig.run(1)
    assert rig.app.live.snapshot().paused_until is not None
    assert repo.count_disable_events(NOON - timedelta(days=1)) == 1


def test_soft_rules_pause_freely(repo: Repository) -> None:
    rig = make_rig(repo, mode="soft")
    assert not rig.app.live.snapshot().strict_active
    rig.app.bus.publish(PauseAll(15))
    rig.run(1)
    assert rig.app.live.snapshot().paused_until is not None


def test_strict_focus_session_needs_confirmation_to_stop(repo: Repository) -> None:
    rig = make_rig(repo)
    rig.app.bus.publish(StartFocus(mode="strict"))
    rig.app.bus.publish(StopFocus())
    rig.run(1)
    assert rig.app.live.snapshot().focus_active
    rig.app.bus.publish(StopFocus(confirmed=True))
    rig.run(1)
    assert not rig.app.live.snapshot().focus_active


def test_camera_pause_never_needs_confirmation(repo: Repository) -> None:
    rig = make_rig(repo, mode="strict")
    rig.app.bus.publish(SetCameraPaused(True))
    rig.run(1)
    assert rig.app.live.snapshot().camera_paused


def test_disable_rule_until_end_of_day(repo: Repository) -> None:
    rig = make_rig(repo, mode="soft")
    rig.app.bus.publish(DisableRule("social-daily-limit"))
    rig.run(120)
    assert rig.blocker.actions == []
    assert "social-daily-limit" in rig.app.live.snapshot().disabled_rules
    strict = make_rig(Repository(":memory:"), mode="strict")
    strict.app.bus.publish(DisableRule("social-daily-limit"))
    strict.run(62)
    assert strict.blocker.actions  # sin confirmar no se desactivó
