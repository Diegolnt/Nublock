"""Classifier: asigna productivity/subcategory a una ventana según reglas ordenadas (FR-10..13)."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from nublock.config import ClassificationRule, MatchConfig, Productivity
from nublock.tracker.platform.base import WindowInfo


@dataclass(frozen=True)
class Classification:
    productivity: Productivity
    subcategory: str | None


# FR-13: lo que no coincide con ninguna regla.
UNCATEGORIZED = Classification(productivity="neutral", subcategory="uncategorized")


class WindowMatcher:
    """Un matcher `process` o `title_regex` ya compilado."""

    def __init__(self, match: MatchConfig) -> None:
        self._process = match.process.casefold() if match.process else None
        self._pattern = re.compile(match.title_regex) if match.title_regex else None

    def matches(self, window: WindowInfo) -> bool:
        if self._process is not None:
            return window.process_name.casefold() == self._process
        if self._pattern is not None and window.window_title is not None:
            # search(): la regex puede coincidir en cualquier parte del título.
            return self._pattern.search(window.window_title) is not None
        return False


def matches_any(matchers: Sequence[WindowMatcher], window: WindowInfo) -> bool:
    return any(matcher.matches(window) for matcher in matchers)


class Classifier:
    def __init__(
        self,
        rules: Sequence[ClassificationRule],
        overrides: Sequence[ClassificationRule] = (),
    ) -> None:
        # Los overrides (clasificados desde el dashboard) se evalúan antes que el config.
        # Compilamos una sola vez; classify() se llama cada segundo.
        self._rules = [
            (WindowMatcher(rule.match), Classification(rule.productivity, rule.subcategory))
            for rule in [*overrides, *rules]
        ]

    def classify(self, window: WindowInfo) -> Classification:
        """Retorna la clasificación de la primera regla que coincide (el orden importa)."""
        for matcher, classification in self._rules:
            if matcher.matches(window):
                return classification
        return UNCATEGORIZED
