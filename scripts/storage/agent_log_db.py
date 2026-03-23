"""
SQLite persistence for agent runs: user input, plan, per-step logs, final state.

Default file: ``<project_root>/data/agent.db``. Override with env ``AGENT_DB_PATH``.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.models import TaskBreakdown
from agent.state import AgentState


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_root() -> Path:
    # storage/agent_log_db.py -> storage -> scripts -> repo root
    return Path(__file__).resolve().parent.parent.parent


def default_db_path() -> Path:
    raw = os.environ.get("AGENT_DB_PATH")
    if raw:
        return Path(raw).expanduser().resolve()
    return _project_root() / "data" / "agent.db"


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_input TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'started',
    plan_json TEXT,
    final_state_json TEXT,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS log_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    category TEXT NOT NULL,
    message TEXT,
    payload_json TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_log_entries_run_id ON log_entries(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def _dump_json(obj: Any) -> str:
    if hasattr(obj, "model_dump"):
        return json.dumps(obj.model_dump(), ensure_ascii=False)
    return json.dumps(obj, ensure_ascii=False, default=str)


def create_run(
    conn: sqlite3.Connection,
    user_input: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> int:
    """Start a run row; returns ``run_id``."""
    now = _utc_now()
    meta = _dump_json(metadata or {})
    cur = conn.execute(
        """
        INSERT INTO runs (user_input, created_at, updated_at, status, metadata_json)
        VALUES (?, ?, ?, 'started', ?)
        """,
        (user_input, now, now, meta),
    )
    conn.commit()
    return int(cur.lastrowid)


def touch_run(conn: sqlite3.Connection, run_id: int) -> None:
    conn.execute(
        "UPDATE runs SET updated_at = ? WHERE id = ?",
        (_utc_now(), run_id),
    )
    conn.commit()


def add_log(
    conn: sqlite3.Connection,
    run_id: int,
    category: str,
    message: str = "",
    payload: Any | None = None,
) -> int:
    """Append one log line; returns ``log_entries.id``."""
    touch_run(conn, run_id)
    pj = _dump_json(payload) if payload is not None else None
    cur = conn.execute(
        """
        INSERT INTO log_entries (run_id, created_at, category, message, payload_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, _utc_now(), category, message or "", pj),
    )
    conn.commit()
    return int(cur.lastrowid)


def save_plan(conn: sqlite3.Connection, run_id: int, plan: TaskBreakdown) -> None:
    conn.execute(
        "UPDATE runs SET plan_json = ?, updated_at = ? WHERE id = ?",
        (plan.model_dump_json(), _utc_now(), run_id),
    )
    conn.commit()


def save_final_state(conn: sqlite3.Connection, run_id: int, state: AgentState) -> None:
    conn.execute(
        "UPDATE runs SET final_state_json = ?, updated_at = ? WHERE id = ?",
        (state.model_dump_json(), _utc_now(), run_id),
    )
    conn.commit()


def set_run_status(conn: sqlite3.Connection, run_id: int, status: str) -> None:
    conn.execute(
        "UPDATE runs SET status = ?, updated_at = ? WHERE id = ?",
        (status, _utc_now(), run_id),
    )
    conn.commit()


def open_initialized(db_path: Path | None = None) -> sqlite3.Connection:
    """Connect and ensure tables exist."""
    conn = connect(db_path)
    init_schema(conn)
    return conn
