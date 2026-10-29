from datetime import date, timedelta
from pathlib import Path

import pytest

from nublock import cli
from nublock.classifier import Classification
from nublock.storage import Repository
from nublock.timeutils import local_day_bounds

EXAMPLE = Path(__file__).resolve().parents[1] / "config" / "config.example.yaml"


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Los tests no deben escribir logs ni leer config en el home del usuario."""
    monkeypatch.setattr(cli, "default_log_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(cli, "default_config_path", lambda: tmp_path / "missing.yaml")


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])
    assert exc_info.value.code == 0
    assert "report" in capsys.readouterr().out


def test_report_today_reads_sqlite(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "nublock.db"
    repo = Repository(db)
    start = local_day_bounds(date.today())[0] + timedelta(minutes=1)
    session_id = repo.open_session(
        start, "Code", "Code", None, Classification("productive", "dev"), False
    )
    repo.set_session_end(session_id, start + timedelta(minutes=25))
    repo.close()
    assert cli.main(["--db", str(db), "report", "today"]) == 0
    out = capsys.readouterr().out
    assert "productive" in out and "25m 00s" in out and "1. Code" in out


def test_config_command_validates_example(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--config", str(EXAMPLE), "--db", str(tmp_path / "x.db"), "config"]) == 0
    assert "observe_only=True" in capsys.readouterr().out


def test_invalid_config_returns_error_code(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("general:\n  observe_only: maybe\n", encoding="utf-8")
    assert cli.main(["--config", str(bad), "config"]) == 2
