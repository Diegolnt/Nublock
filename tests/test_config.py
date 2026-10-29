from datetime import time
from pathlib import Path

import pytest

from nublock.config import Config, ConfigError, DailyLimitRule, ScheduleRule, load_config

EXAMPLE = Path(__file__).resolve().parents[1] / "config" / "config.example.yaml"


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_example_config_loads() -> None:
    config = load_config(EXAMPLE)
    assert config.general.observe_only is True
    assert config.general.poll_interval_seconds == 1
    assert config.classification_rules[0].match.process == "Code"
    limit, schedule = config.rules
    assert isinstance(limit, DailyLimitRule) and limit.limit_minutes == 30
    assert isinstance(schedule, ScheduleRule)
    assert (schedule.start, schedule.end) == (time(9, 0), time(13, 0))
    assert schedule.days == ["mon", "tue", "wed", "thu", "fri"]
    assert config.attention.monitors == 2 and config.attention.only_during_focus
    assert [m.process for m in config.attention.attention_exempt] == ["zoom.us", "FaceTime"]
    assert config.interventions.grace_seconds["PHONE"] == 3
    assert config.focus_session.default_minutes == 50
    assert config.dashboard.port == 8765


def test_no_path_returns_defaults() -> None:
    config = load_config(None)
    assert config == Config()
    assert config.general.observe_only is True  # observe-only por defecto (FR-24)
    assert config.general.idle_threshold_seconds == 120
    assert config.classification_rules == [] and config.rules == []


def test_empty_file_returns_defaults(tmp_path: Path) -> None:
    assert load_config(write(tmp_path, "")) == Config()


def test_partial_general_keeps_other_defaults(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, "general:\n  store_window_titles: false\n"))
    assert config.general.store_window_titles is False
    assert config.general.observe_only is True


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="no existe"):
        load_config(tmp_path / "nope.yaml")


def test_invalid_yaml_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="YAML inválido"):
        load_config(write(tmp_path, "general: [unclosed"))


@pytest.mark.parametrize(
    "text",
    [
        "general:\n  poll_interval_seconds: 0\n",  # debe ser > 0
        "general:\n  pol_interval_seconds: 1\n",  # typo: key desconocida
        "unknown_section: {}\n",
        "classification_rules:\n  - match: {process: x}\n    productivity: awesome\n",
        "classification_rules:\n  - match: {process: x, title_regex: y}\n"
        "    productivity: neutral\n",
        "classification_rules:\n  - match: {}\n    productivity: neutral\n",
        "classification_rules:\n  - match: {title_regex: '(unclosed'}\n    productivity: neutral\n",
        "rules:\n  - {id: a, type: daily_limit, target: {}, limit_minutes: 5}\n",
        "rules:\n  - {id: a, type: daily_limit, target: {subcategory: s}, limit_minutes: -1}\n",
        "rules:\n  - {id: a, type: focus, target: {subcategory: s}}\n",
        "rules:\n  - {id: a, type: schedule, days: [mon], start: '09:00', end: '10:00',"
        " target: {productivity: distracting}, action: explode}\n",
        "attention:\n  fps: 8\n",  # key desconocida (es process_fps)
        "attention:\n  phone_detection: {min_score: 1.5}\n",
        "interventions:\n  escalation_seconds: [20, 10, 0]\n",
        "interventions:\n  escalation_seconds: [0, 10]\n",
        "interventions:\n  grace_seconds: {PHONE: 3}\n",
        "focus_session:\n  mode: relaxed\n",
        "dashboard:\n  port: 80\n",
    ],
)
def test_invalid_values_raise(tmp_path: Path, text: str) -> None:
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, text))


def test_unquoted_yaml_time_gives_helpful_error(tmp_path: Path) -> None:
    text = (
        "rules:\n  - {id: a, type: schedule, days: [mon], start: '09:00', end: 13:00,"
        " target: {productivity: distracting}}\n"
    )
    with pytest.raises(ConfigError, match="comillas"):
        load_config(write(tmp_path, text))


def test_duplicate_rule_ids_raise(tmp_path: Path) -> None:
    rule = "  - {id: same, type: daily_limit, target: {subcategory: s}, limit_minutes: 5}\n"
    with pytest.raises(ConfigError, match="duplicados"):
        load_config(write(tmp_path, "rules:\n" + rule + rule))
