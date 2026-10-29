"""Debounce de la state machine (FR-34)."""

from datetime import timedelta

from helpers import NOON, at

from nublock.attention.state_machine import AttentionStateMachine, AttentionTransition
from nublock.attention.states import AttentionState as S

FPS = 8


def feed(
    machine: AttentionStateMachine, raw: S, start: float, seconds: float
) -> list[AttentionTransition]:
    """Simula `seconds` de frames a 8 FPS con el mismo estado raw."""
    transitions = []
    for frame in range(round(seconds * FPS)):
        result = machine.update(raw, at(start + frame / FPS))
        if result is not None:
            transitions.append(result)
    return transitions


def test_first_observation_sets_state_immediately() -> None:
    machine = AttentionStateMachine(debounce_seconds=2)
    (transition,) = feed(machine, S.FOCUSED, 0, 1)
    assert (transition.previous, transition.state, transition.started_at) == (None, S.FOCUSED, NOON)


def test_blink_or_one_second_head_turn_does_not_transition() -> None:
    machine = AttentionStateMachine(debounce_seconds=2)
    feed(machine, S.FOCUSED, 0, 5)
    assert feed(machine, S.ABSENT, 5, 0.3) == []  # parpadeo / cara perdida un instante
    assert feed(machine, S.FOCUSED, 5.3, 2) == []
    assert feed(machine, S.LOOKING_AWAY, 7.3, 1) == []  # girar la cabeza 1 s
    assert feed(machine, S.FOCUSED, 8.3, 2) == []
    assert machine.state == S.FOCUSED


def test_state_held_for_debounce_transitions_with_real_start_time() -> None:
    machine = AttentionStateMachine(debounce_seconds=2)
    feed(machine, S.FOCUSED, 0, 5)
    transitions = feed(machine, S.LOOKING_AWAY, 5, 3)
    assert len(transitions) == 1
    transition = transitions[0]
    assert (transition.previous, transition.state) == (S.FOCUSED, S.LOOKING_AWAY)
    assert transition.started_at == at(5)  # cuándo empezó, no cuándo terminó el debounce
    assert machine.state_since == at(5)


def test_paused_and_camera_unavailable_skip_debounce() -> None:
    machine = AttentionStateMachine(debounce_seconds=2)
    feed(machine, S.FOCUSED, 0, 1)
    transition = machine.update(S.PAUSED, at(1))
    assert transition is not None and transition.state == S.PAUSED
    transition = machine.update(S.CAMERA_UNAVAILABLE, at(1.1))
    assert transition is not None and transition.state == S.CAMERA_UNAVAILABLE


def test_previous_confidence_is_fraction_of_matching_frames() -> None:
    machine = AttentionStateMachine(debounce_seconds=2)
    feed(machine, S.FOCUSED, 0, 1)  # 8 frames FOCUSED
    machine.update(S.ABSENT, at(1))  # 1 frame de ruido
    feed(machine, S.FOCUSED, 1.125, 0.125)  # 1 frame FOCUSED
    (transition,) = feed(machine, S.LOOKING_DOWN, 2, 2.125)
    # FOCUSED: 9 de 10 frames antes del cambio + 16 frames del candidato que no coincidían.
    assert transition.previous_confidence is not None
    assert 0 < transition.previous_confidence < 1
    assert transition.started_at - NOON == timedelta(seconds=2)
