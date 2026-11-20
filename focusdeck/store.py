"""SQLite persistence for tasks, finished sessions and settings."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .engine import Phase

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL,
    done       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at       TEXT    NOT NULL,
    phase            TEXT    NOT NULL,
    duration_seconds INTEGER NOT NULL,
    task_id          INTEGER REFERENCES tasks(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions(started_at);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def default_db_path() -> Path:
    """Where the database lives when the caller does not supply a path."""
    override = os.environ.get("FOCUSDECK_DB")
    if override:
        return Path(override).expanduser()

    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "focusdeck" / "focusdeck.db"


@dataclass(frozen=True)
class Task:
    id: int
    title: str
    done: bool
    created_at: str


def _phase_value(phase: Phase | str) -> str:
    return phase.value if isinstance(phase, Phase) else str(phase)


class Store:
    """Thin, explicit wrapper around a SQLite connection."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_db_path()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # -- lifecycle -----------------------------------------------------
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- tasks ---------------------------------------------------------
    def add_task(self, title: str) -> Task:
        title = title.strip()
        if not title:
            raise ValueError("Task title must not be empty.")
        created = datetime.now().isoformat(timespec="seconds")
        cur = self._conn.execute(
            "INSERT INTO tasks (title, done, created_at) VALUES (?, 0, ?)",
            (title, created),
        )
        self._conn.commit()
        return Task(int(cur.lastrowid), title, False, created)

    def tasks(self, include_done: bool = True) -> list[Task]:
        sql = "SELECT id, title, done, created_at FROM tasks"
        if not include_done:
            sql += " WHERE done = 0"
        sql += " ORDER BY done ASC, id ASC"
        rows = self._conn.execute(sql).fetchall()
        return [
            Task(int(r["id"]), r["title"], bool(r["done"]), r["created_at"])
            for r in rows
        ]

    def set_task_done(self, task_id: int, done: bool) -> None:
        self._conn.execute(
            "UPDATE tasks SET done = ? WHERE id = ?", (1 if done else 0, int(task_id))
        )
        self._conn.commit()

    def delete_task(self, task_id: int) -> None:
        self._conn.execute("DELETE FROM tasks WHERE id = ?", (int(task_id),))
        self._conn.commit()

    # -- sessions ------------------------------------------------------
    def record_session(
        self,
        phase: Phase | str,
        duration_seconds: int,
        task_id: int | None = None,
        started_at: datetime | None = None,
    ) -> int:
        started = started_at or datetime.now()
        cur = self._conn.execute(
            "INSERT INTO sessions (started_at, phase, duration_seconds, task_id)"
            " VALUES (?, ?, ?, ?)",
            (
                started.isoformat(timespec="seconds"),
                _phase_value(phase),
                int(duration_seconds),
                int(task_id) if task_id is not None else None,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def recent_sessions(self, limit: int = 100) -> list[dict]:
        rows = self._conn.execute(
            "SELECT s.id, s.started_at, s.phase, s.duration_seconds,"
            "       t.title AS task_title"
            "  FROM sessions s"
            "  LEFT JOIN tasks t ON t.id = s.task_id"
            " ORDER BY s.started_at DESC, s.id DESC"
            " LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]

    def focus_seconds_by_day(
        self, days: int = 7, today: date | None = None
    ) -> list[tuple[date, int]]:
        """Focus seconds per day for the last ``days`` days, zero-filled."""
        days = max(1, int(days))
        today = today or date.today()
        start = today - timedelta(days=days - 1)
        rows = self._conn.execute(
            "SELECT substr(started_at, 1, 10) AS day,"
            "       COALESCE(SUM(duration_seconds), 0) AS total"
            "  FROM sessions"
            " WHERE phase = ? AND substr(started_at, 1, 10) >= ?"
            " GROUP BY day",
            (_phase_value(Phase.FOCUS), start.isoformat()),
        ).fetchall()
        totals = {r["day"]: int(r["total"]) for r in rows}
        return [
            (start + timedelta(days=i), totals.get((start + timedelta(days=i)).isoformat(), 0))
            for i in range(days)
        ]

    def focus_sessions_on(self, day: date | None = None) -> int:
        day = day or date.today()
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM sessions"
            " WHERE phase = ? AND substr(started_at, 1, 10) = ?",
            (_phase_value(Phase.FOCUS), day.isoformat()),
        ).fetchone()
        return int(row["n"])

    def total_focus_seconds(self) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(duration_seconds), 0) AS total FROM sessions WHERE phase = ?",
            (_phase_value(Phase.FOCUS),),
        ).fetchone()
        return int(row["total"])

    # -- settings ------------------------------------------------------
    def load_settings(self) -> dict:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = 'app'"
        ).fetchone()
        if row is None:
            return {}
        try:
            data = json.loads(row["value"])
            return data if isinstance(data, dict) else {}
        except (TypeError, ValueError):
            return {}

    def save_settings(self, values: dict) -> None:
        self._conn.execute(
            "INSERT INTO settings (key, value) VALUES ('app', ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (json.dumps(values, sort_keys=True),),
        )
        self._conn.commit()
