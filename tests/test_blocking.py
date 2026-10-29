"""M6: Enforcer (ocultar/cerrar apps) y FrictionGate (fricción del modo strict)."""

from helpers import FakeClock, at, make_window

from nublock.blocking import Enforcer
from nublock.config import BlockingConfig
from nublock.friction import FrictionGate
from nublock.tracker.platform.fake import FakeAppBlocker

OWN_PID = 999


def enforcer() -> tuple[Enforcer, FakeAppBlocker]:
    blocker = FakeAppBlocker()
    return Enforcer(blocker, BlockingConfig(), own_pid=OWN_PID), blocker


def test_soft_hides_and_strict_terminates() -> None:
    enf, blocker = enforcer()
    assert enf.enforce(make_window("Instagram", pid=10), strict=False, now=at(0)) == "hide"
    assert enf.enforce(make_window("Discord", pid=11), strict=True, now=at(0)) == "terminate"
    assert blocker.actions == [("hide", 10), ("terminate", 11)]


def test_browsers_are_only_hidden_even_in_strict() -> None:
    enf, blocker = enforcer()
    assert enf.enforce(make_window("Google Chrome", pid=12), strict=True, now=at(0)) == "hide"
    assert blocker.actions == [("hide", 12)]


def test_protected_apps_and_nublock_itself_are_never_blocked() -> None:
    enf, blocker = enforcer()
    assert enf.enforce(make_window("Finder", pid=13), strict=True, now=at(0)) is None
    assert enf.enforce(make_window("loginwindow", pid=14), strict=True, now=at(0)) is None
    assert enf.enforce(make_window("Python", pid=OWN_PID), strict=True, now=at(0)) is None
    assert blocker.actions == []


def test_does_not_hammer_the_same_app() -> None:
    enf, blocker = enforcer()
    window = make_window("Instagram", pid=10)
    enf.enforce(window, strict=False, now=at(0))
    assert enf.enforce(window, strict=False, now=at(1)) is None  # < 2 s
    assert enf.enforce(window, strict=False, now=at(2.5)) == "hide"
    assert len(blocker.actions) == 2


# --- FrictionGate -------------------------------------------------------------------


def gate() -> tuple[FrictionGate, FakeClock]:
    clock = FakeClock(at(0))
    config = BlockingConfig(confirmation_phrase="Elijo distraerme ahora", friction_seconds=60)
    return FrictionGate(config, clock), clock


def test_confirmation_requires_waiting_and_the_exact_phrase() -> None:
    friction, clock = gate()
    request = friction.request("pause_all", "15")
    early = friction.confirm(request.token, "Elijo distraerme ahora")
    assert not early.ok and early.wait_seconds == 60
    clock.advance(30)
    assert friction.remaining(request) == 30
    clock.advance(30)
    wrong = friction.confirm(request.token, "elijo distraerme")
    assert not wrong.ok and wrong.error == "La frase no coincide."
    result = friction.confirm(request.token, "  Elijo distraerme ahora ")
    assert result.ok and result.request == request


def test_token_is_single_use_and_expires() -> None:
    friction, clock = gate()
    request = friction.request("stop_focus")
    clock.advance(60)
    assert friction.confirm(request.token, friction.phrase).ok
    assert not friction.confirm(request.token, friction.phrase).ok  # ya se usó
    old = friction.request("disable_rule", "social-daily-limit")
    clock.advance(11 * 60)
    assert friction.confirm(old.token, friction.phrase).error == "La solicitud no existe o expiró."


def test_unknown_token() -> None:
    friction, _ = gate()
    assert not friction.confirm("inventado", "x").ok
