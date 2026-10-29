"""Dashboard FastAPI con TestClient (sin abrir un puerto real)."""

from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nublock.classifier import Classification
from nublock.dashboard.server import DashboardServer, create_app
from nublock.events import BusEvent, ReloadClassifier, StartFocus
from nublock.live_state import LiveState
from nublock.storage import Repository
from nublock.timeutils import local_day_bounds

BASE = "http://127.0.0.1:8765"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "nublock.db"
    repo = Repository(path)
    start = local_day_bounds(date.today())[0] + timedelta(minutes=5)
    for offset, process, classification in (
        (0, "Code", Classification("productive", "dev")),
        (30, "Spotify", Classification("neutral", "uncategorized")),
    ):
        session_id = repo.open_session(
            start + timedelta(minutes=offset), process, process, None, classification, False
        )
        repo.set_session_end(session_id, start + timedelta(minutes=offset + 20))
    event_id = repo.open_attention_event(start, "PHONE")
    repo.close_attention_event(event_id, start + timedelta(seconds=40), 0.8)
    intervention_id = repo.record_intervention(
        start + timedelta(seconds=5), "attention:PHONE", 1, None
    )
    repo.set_refocus_seconds(intervention_id, 12)
    repo.close()
    return path


@pytest.fixture
def published() -> list[BusEvent]:
    return []


@pytest.fixture
def client(db: Path, published: list[BusEvent]) -> Iterator[TestClient]:
    app = create_app(db, published.append, LiveState(observe_only=True))
    with TestClient(app, base_url=BASE) as test_client:
        yield test_client


def test_today_page_shows_categories_timeline_and_uncategorized(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "Tiempo por categoría" in html and "Timeline del día" in html
    assert "Spotify" in html and 'action="/classify"' in html  # app sin clasificar con su form
    assert "20m 00s" in html
    assert "observe-only" in html


def test_week_page(client: TestClient) -> None:
    response = client.get("/week")
    assert response.status_code == 200 and "Últimos 7 días" in response.text


def test_api_today(client: TestClient) -> None:
    data = client.get("/api/today").json()
    assert data["active_seconds"] == 2400
    assert data["by_productivity"] == {"productive": 1200, "neutral": 1200}
    assert data["distractions"] == 1
    assert data["avg_refocus_seconds"] == 12
    assert data["uncategorized"] == [{"process": "Spotify", "seconds": 1200}]


def test_classify_saves_override_and_reloads(
    client: TestClient, db: Path, published: list[BusEvent]
) -> None:
    response = client.post(
        "/classify",
        data={"process_name": "Spotify", "productivity": "distracting", "subcategory": "music"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    repo = Repository(db)
    (override,) = repo.load_overrides()
    repo.close()
    assert (override.match.process, override.productivity, override.subcategory) == (
        "Spotify",
        "distracting",
        "music",
    )
    assert published == [ReloadClassifier()]


def test_controls_publish_commands(client: TestClient, published: list[BusEvent]) -> None:
    response = client.post(
        "/focus/start", data={"mode": "strict", "minutes": "25"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert published == [StartFocus(minutes=25, mode="strict")]


def test_controls_need_running_app(db: Path) -> None:
    with TestClient(create_app(db), base_url=BASE) as client:
        assert client.post("/focus/stop").status_code == 409
        assert "no está corriendo" in client.get("/").text


def test_rejects_cross_site_posts(client: TestClient, published: list[BusEvent]) -> None:
    response = client.post("/focus/stop", headers={"origin": "https://evil.example"})
    assert response.status_code == 403
    assert published == []


def test_rejects_non_local_host_header(db: Path) -> None:
    with TestClient(create_app(db), base_url="http://evil.example") as client:
        assert client.get("/").status_code == 400


def test_delete_requires_typed_confirmation(client: TestClient, db: Path) -> None:
    assert client.post("/data/delete", data={"confirm": "si"}).status_code == 422
    assert (
        client.post("/data/delete", data={"confirm": "BORRAR"}, follow_redirects=False).status_code
        == 303
    )
    assert client.get("/api/today").json()["active_seconds"] == 0


def test_server_only_listens_on_localhost(db: Path) -> None:
    assert DashboardServer(create_app(db), 8765).url == "http://127.0.0.1:8765"
