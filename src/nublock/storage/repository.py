"""Acceso a SQLite con `sqlite3` (stdlib) y SQL escrito a mano.

Regla: cada thread usa su propio `Repository` (una conexión cada uno). Se abre con
`check_same_thread=False` porque a veces se crea en el main thread y se usa en otro,
pero nunca se comparte una conexión entre dos threads a la vez.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Literal

from nublock.classifier import Classification
from nublock.config import ClassificationRule, MatchConfig, Mode, Productivity
from nublock.timeutils import from_iso, to_iso

MEMORY = ":memory:"  # DB temporal en RAM, útil para tests

MatcherType = Literal["process", "title_regex"]


@dataclass(frozen=True)
class ActivitySession:
    """Una fila de `activity_sessions`."""

    id: int
    started_at: datetime
    ended_at: datetime | None
    process_name: str
    app_name: str | None
    window_title: str | None
    productivity: Productivity
    subcategory: str | None
    is_idle: bool


@dataclass(frozen=True)
class AttentionEventRow:
    id: int
    started_at: datetime
    ended_at: datetime | None
    state: str
    confidence: float | None


@dataclass(frozen=True)
class InterventionRow:
    id: int
    at: datetime
    trigger: str
    level: int
    rule_id: str | None
    user_feedback: str | None
    refocus_seconds: float | None


@dataclass(frozen=True)
class FocusSessionRow:
    id: int
    started_at: datetime
    ended_at: datetime | None
    planned_minutes: int
    mode: Mode
    completed: bool


class Repository:
    def __init__(self, db_path: Path | str) -> None:
        if str(db_path) != MEMORY:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        # row_factory=sqlite3.Row: las filas se pueden leer por nombre de columna.
        self._conn.row_factory = sqlite3.Row
        # WAL (Write-Ahead Logging): permite leer (ej. `report`) mientras el tracker escribe.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        schema = resources.files("nublock.storage").joinpath("schema.sql").read_text("utf-8")
        self._conn.executescript(schema)

    def close(self) -> None:
        self._conn.close()

    def _insert(self, sql: str, params: tuple[object, ...]) -> int:
        # `with self._conn`: hace commit al salir del bloque (o rollback si hay excepción).
        # Los `?` son placeholders: sqlite3 escapa los valores (evita SQL injection).
        with self._conn:
            cursor = self._conn.execute(sql, params)
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def _update(self, sql: str, params: tuple[object, ...]) -> int:
        with self._conn:
            cursor = self._conn.execute(sql, params)
        return cursor.rowcount

    # --- activity_sessions -------------------------------------------------

    def open_session(
        self,
        started_at: datetime,
        process_name: str,
        app_name: str | None,
        window_title: str | None,
        classification: Classification,
        is_idle: bool,
    ) -> int:
        """Inserta una sesión abierta (ended_at = NULL) y retorna su id."""
        return self._insert(
            """
            INSERT INTO activity_sessions
                (started_at, process_name, app_name, window_title, productivity, subcategory,
                 is_idle)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                to_iso(started_at),
                process_name,
                app_name,
                window_title,
                classification.productivity,
                classification.subcategory,
                int(is_idle),
            ),
        )

    def set_session_end(self, session_id: int, ended_at: datetime) -> None:
        """Actualiza ended_at (se usa al cerrar la sesión y como heartbeat)."""
        self._update(
            "UPDATE activity_sessions SET ended_at = ? WHERE id = ?", (to_iso(ended_at), session_id)
        )

    def sessions_between(self, start: datetime, end: datetime) -> list[ActivitySession]:
        """Sesiones que se superponen con [start, end), ordenadas por inicio."""
        # Comparar strings ISO 8601 con el mismo formato equivale a comparar fechas.
        rows = self._conn.execute(
            """
            SELECT * FROM activity_sessions
            WHERE started_at < ? AND COALESCE(ended_at, started_at) >= ?
            ORDER BY started_at
            """,
            (to_iso(end), to_iso(start)),
        ).fetchall()
        return [_row_to_session(row) for row in rows]

    # --- attention_events ----------------------------------------------------

    def open_attention_event(self, started_at: datetime, state: str) -> int:
        return self._insert(
            "INSERT INTO attention_events (started_at, state) VALUES (?, ?)",
            (to_iso(started_at), state),
        )

    def close_attention_event(
        self, event_id: int, ended_at: datetime, confidence: float | None
    ) -> None:
        self._update(
            "UPDATE attention_events SET ended_at = ?, confidence = ? WHERE id = ?",
            (to_iso(ended_at), confidence, event_id),
        )

    def attention_events_between(self, start: datetime, end: datetime) -> list[AttentionEventRow]:
        rows = self._conn.execute(
            """
            SELECT * FROM attention_events
            WHERE started_at < ? AND COALESCE(ended_at, started_at) >= ?
            ORDER BY started_at
            """,
            (to_iso(end), to_iso(start)),
        ).fetchall()
        return [
            AttentionEventRow(
                id=row["id"],
                started_at=from_iso(row["started_at"]),
                ended_at=from_iso(row["ended_at"]) if row["ended_at"] else None,
                state=row["state"],
                confidence=row["confidence"],
            )
            for row in rows
        ]

    # --- interventions -----------------------------------------------------

    def record_intervention(
        self, at: datetime, trigger: str, level: int, rule_id: str | None
    ) -> int:
        return self._insert(
            "INSERT INTO interventions (at, trigger, level, rule_id) VALUES (?, ?, ?, ?)",
            (to_iso(at), trigger, level, rule_id),
        )

    def set_refocus_seconds(self, intervention_id: int, seconds: float) -> None:
        self._update(
            "UPDATE interventions SET refocus_seconds = ? WHERE id = ?", (seconds, intervention_id)
        )

    def mark_latest_false_alarm(self, since: datetime) -> InterventionRow | None:
        """Marca la última intervention desde `since` como falsa alarma (FR-43)."""
        row = self._conn.execute(
            "SELECT id FROM interventions WHERE at >= ? ORDER BY at DESC, id DESC LIMIT 1",
            (to_iso(since),),
        ).fetchone()
        if row is None:
            return None
        self._update(
            "UPDATE interventions SET user_feedback = 'false_alarm' WHERE id = ?", (row["id"],)
        )
        return self.get_intervention(row["id"])

    def get_intervention(self, intervention_id: int) -> InterventionRow | None:
        row = self._conn.execute(
            "SELECT * FROM interventions WHERE id = ?", (intervention_id,)
        ).fetchone()
        return _row_to_intervention(row) if row else None

    def count_false_alarms(self, trigger: str, since: datetime) -> int:
        row = self._conn.execute(
            """
            SELECT COUNT(*) FROM interventions
            WHERE trigger = ? AND user_feedback = 'false_alarm' AND at >= ?
            """,
            (trigger, to_iso(since)),
        ).fetchone()
        return int(row[0])

    def interventions_between(self, start: datetime, end: datetime) -> list[InterventionRow]:
        rows = self._conn.execute(
            "SELECT * FROM interventions WHERE at >= ? AND at < ? ORDER BY at",
            (to_iso(start), to_iso(end)),
        ).fetchall()
        return [_row_to_intervention(row) for row in rows]

    def count_interventions(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM interventions").fetchone()[0])

    # --- focus_sessions ------------------------------------------------------

    def start_focus_session(self, started_at: datetime, planned_minutes: int, mode: Mode) -> int:
        return self._insert(
            "INSERT INTO focus_sessions (started_at, planned_minutes, mode) VALUES (?, ?, ?)",
            (to_iso(started_at), planned_minutes, mode),
        )

    def end_focus_session(self, session_id: int, ended_at: datetime, completed: bool) -> None:
        self._update(
            "UPDATE focus_sessions SET ended_at = ?, completed = ? WHERE id = ?",
            (to_iso(ended_at), int(completed), session_id),
        )

    def focus_sessions_between(self, start: datetime, end: datetime) -> list[FocusSessionRow]:
        rows = self._conn.execute(
            "SELECT * FROM focus_sessions WHERE started_at >= ? AND started_at < ? "
            "ORDER BY started_at",
            (to_iso(start), to_iso(end)),
        ).fetchall()
        return [
            FocusSessionRow(
                id=row["id"],
                started_at=from_iso(row["started_at"]),
                ended_at=from_iso(row["ended_at"]) if row["ended_at"] else None,
                planned_minutes=row["planned_minutes"],
                mode=row["mode"],
                completed=bool(row["completed"]),
            )
            for row in rows
        ]

    def close_dangling(self) -> None:
        """Cierra filas que quedaron abiertas si la app se cayó (duración desconocida = 0)."""
        with self._conn:
            self._conn.execute(
                "UPDATE attention_events SET ended_at = started_at WHERE ended_at IS NULL"
            )
            self._conn.execute(
                "UPDATE focus_sessions SET ended_at = started_at WHERE ended_at IS NULL"
            )

    # --- disable_events (M6) -----------------------------------------------------

    def record_disable_event(
        self, at: datetime, action: str, target: str | None, strict: bool
    ) -> int:
        return self._insert(
            "INSERT INTO disable_events (at, action, target, strict) VALUES (?, ?, ?, ?)",
            (to_iso(at), action, target, int(strict)),
        )

    def count_disable_events(self, since: datetime) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM disable_events WHERE at >= ?", (to_iso(since),)
        ).fetchone()
        return int(row[0])

    # --- classification_overrides ---------------------------------------------

    def add_override(
        self,
        matcher_type: MatcherType,
        pattern: str,
        productivity: Productivity,
        subcategory: str | None,
        created_at: datetime,
    ) -> int:
        return self._insert(
            """
            INSERT INTO classification_overrides
                (matcher_type, pattern, productivity, subcategory, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (matcher_type, pattern, productivity, subcategory, to_iso(created_at)),
        )

    def load_overrides(self) -> list[ClassificationRule]:
        """Overrides como reglas de clasificación; el más reciente primero (gana)."""
        rows = self._conn.execute(
            "SELECT * FROM classification_overrides "
            "WHERE matcher_type IN ('process', 'title_regex') ORDER BY id DESC"
        ).fetchall()
        return [
            ClassificationRule(
                match=MatchConfig.model_validate({row["matcher_type"]: row["pattern"]}),
                productivity=row["productivity"],
                subcategory=row["subcategory"],
            )
            for row in rows
        ]

    # --- retención y borrado ----------------------------------------------------

    def delete_data_before(self, cutoff: datetime) -> int:
        """Retención (FR-72): borra actividad, atención e interventions anteriores a `cutoff`."""
        iso = to_iso(cutoff)
        with self._conn:
            deleted = self._conn.execute(
                "DELETE FROM activity_sessions WHERE COALESCE(ended_at, started_at) < ?", (iso,)
            ).rowcount
            deleted += self._conn.execute(
                "DELETE FROM attention_events WHERE COALESCE(ended_at, started_at) < ?", (iso,)
            ).rowcount
            deleted += self._conn.execute("DELETE FROM interventions WHERE at < ?", (iso,)).rowcount
            deleted += self._conn.execute(
                "DELETE FROM focus_sessions WHERE COALESCE(ended_at, started_at) < ?", (iso,)
            ).rowcount
        return deleted

    def delete_all_data(self) -> None:
        """Botón "borrar todo el historial" (FR-72). Los overrides se mantienen."""
        with self._conn:
            for table in (
                "activity_sessions",
                "attention_events",
                "interventions",
                "focus_sessions",
                "disable_events",
            ):
                self._conn.execute(f"DELETE FROM {table}")  # nombres fijos, no input del usuario


def _row_to_session(row: sqlite3.Row) -> ActivitySession:
    return ActivitySession(
        id=row["id"],
        started_at=from_iso(row["started_at"]),
        ended_at=from_iso(row["ended_at"]) if row["ended_at"] else None,
        process_name=row["process_name"],
        app_name=row["app_name"],
        window_title=row["window_title"],
        productivity=row["productivity"],
        subcategory=row["subcategory"],
        is_idle=bool(row["is_idle"]),
    )


def _row_to_intervention(row: sqlite3.Row) -> InterventionRow:
    return InterventionRow(
        id=row["id"],
        at=from_iso(row["at"]),
        trigger=row["trigger"],
        level=row["level"],
        rule_id=row["rule_id"],
        user_feedback=row["user_feedback"],
        refocus_seconds=row["refocus_seconds"],
    )
