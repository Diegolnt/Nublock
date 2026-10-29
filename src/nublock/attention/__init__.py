"""Attention Monitor (M3–M4): cámara -> face landmarks/head pose -> estados de atención."""

from nublock.attention.state_machine import AttentionTransition
from nublock.attention.states import DISTRACTED_STATES, AttentionState

__all__ = ["DISTRACTED_STATES", "AttentionState", "AttentionTransition"]
