"""Dashboard M6: reglas, fricción del modo strict y export (FR-62)."""

import csv
import io
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from helpers import FakeClock, at

from nublock.classifier import Classification
from nublock.config import Config
from nublock.dashboard.server import create_app
from nublock.events import BusEvent, DisableRule, PauseAll, StopFocus
from nublock.friction import FrictionGate
from nublock.live_state import LiveState
from nublock.storage import Repository
from nublock.timeutils import local_day_bounds

BASE = "http://127.0.0.1:8765"
CONFIG = Config.model_validate(
    {
        "rules": [
            {
                "id": "social-daily-limit",
                "type": "daily_limit",
                "target": {"subcategory": "social"},
                "limit_minutes": 30,
                "action": "block",
                "mode": "soft",
            },
            {
                "id": "morning-focus",
                "type": "schedule",
                "days": ["mon", "tue"],
                "start": "09:00",
                "end": "13:00",
                "target": {"productivity": "distracting"},
                "action": "warn",
                "mode": "strict",
            },
        ]
    }
)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "nublock.db"
    repo = Repository(path)
    start = local_day_bounds(date.today())[0] + timedelta(minutes=5)
    social = Classification("distracting", "social")
    session_id = repo.open_session(start, "Instagram", "Instagram", "secreto", social, False)
    repo.set_session_end(session_id, start + timedelta(minutes=12))
    repo.close()
    return path


class Env:
    def __init__(self, db: Path) -> None:
        self.published: list[BusEvent] = []
        self.live = LiveState(observe_only=False)
        self.clock = FakeClock(at(0))
        self.gate = FrictionGate(CONFIG.blocking, self.clock)
        self.client = TestClient(
            create_app(db, self.published.append, self.live, CONFIG, self.gate), base_url=BASE
        )


@pytest.fixture
def env(db: Path) -> Iterator[Env]:
    environment = Env(db)
    with environment.client:
        yield environment


def test_rules_section_shows_usage_and_disable_buttons(env: Env) -> None:
    html = env.client.get("/").text
    assert "social-daily-limit" in html and "12 / 30 min" in html
    assert "morning-focus" in html and "mon, tue 09:00–13:00" in html
    assert html.count('action="/rules/disable"') == 2


def test_soft_rule_disables_directly(env: Env) -> None:
    response = env.client.post(
        "/rules/disable", data={"rule_id": "social-daily-limit"}, follow_redirects=False
    )
    assert response.status_code == 303 and response.headers["location"] == "/"
    assert env.published == [DisableRule("social-daily-limit")]


def test_strict_rule_goes_through_friction(env: Env) -> None:
    response = env.client.post(
        "/rules/disable", data={"rule_id": "morning-focus"}, follow_redirects=False
    )
    assert response.headers["location"] == "/friction?action=disable_rule&target=morning-focus"
    page = env.client.get(response.headers["location"])
    assert "Desactivar la regla morning-focus por hoy" in page.text
    assert "Elijo distraerme ahora" in page.text and "disabled" in page.text
    token = page.text.split('name="token" value="')[1].split('"')[0]

    early = env.client.post(
        "/friction/confirm", data={"token": token, "phrase": "Elijo distraerme ahora"}
    )
    assert "Todavía faltan 60 s." in early.text and env.published == []

    env.clock.advance(60)
    wrong = env.client.post("/friction/confirm", data={"token": token, "phrase": "dale"})
    assert "La frase no coincide." in wrong.text and env.published == []

    ok = env.client.post(
        "/friction/confirm",
        data={"token": token, "phrase": "Elijo distraerme ahora"},
        follow_redirects=False,
    )
    assert ok.status_code == 303
    assert env.published == [DisableRule("morning-focus", confirmed=True)]


def test_pause_and_stop_focus_use_friction_when_strict(env: Env) -> None:
    env.live.update(strict_active=True, focus_active=True, focus_mode="strict")
    pause = env.client.post("/pause", data={"minutes": "15"}, follow_redirects=False)
    assert pause.headers["location"] == "/friction?action=pause_all&target=15"
    stop = env.client.post("/focus/stop", follow_redirects=False)
    assert stop.headers["location"] == "/friction?action=stop_focus"
    resume = env.client.post("/pause", data={"minutes": "0"}, follow_redirects=False)
    assert resume.headers["location"] == "/"  # reanudar nunca tiene fricción
    page = env.client.get("/friction?action=stop_focus")
    token = page.text.split('name="token" value="')[1].split('"')[0]
    env.clock.advance(61)
    env.client.post("/friction/confirm", data={"token": token, "phrase": env.gate.phrase})
    assert env.published == [PauseAll(0), StopFocus(confirmed=True)]


def test_export_json_and_csv_without_titles(env: Env) -> None:
    data = env.client.get("/export.json?days=2").json()
    (row,) = data["activity"]
    assert row["process_name"] == "Instagram" and row["seconds"] == 720
    assert row["date"] == date.today().isoformat() and "window_title" not in row
    response = env.client.get("/export.csv?days=2")
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows[0]["subcategory"] == "social" and rows[0]["seconds"] == "720.0"
    assert "secreto" not in response.text  # el título de ventana nunca se exporta
