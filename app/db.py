from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .config import get_settings


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'operator', 'viewer')),
    is_active INTEGER NOT NULL DEFAULT 1,
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    target_type TEXT NOT NULL CHECK(target_type IN ('windows', 'linux', 'ids')),
    runner TEXT NOT NULL CHECK(runner IN ('powershell', 'cmd', 'bash')),
    script_body TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK(target_type IN ('windows', 'linux', 'ids')),
    event_count INTEGER NOT NULL CHECK(event_count BETWEEN 1 AND 100000),
    delay_ms INTEGER NOT NULL CHECK(delay_ms BETWEEN 0 AND 60000),
    target_host TEXT NOT NULL DEFAULT '',
    target_port INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK(status IN ('created', 'running', 'completed', 'failed', 'expired', 'cancelled')) DEFAULT 'created',
    token_hash TEXT NOT NULL UNIQUE,
    token_preview TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS task_scenarios (
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE RESTRICT,
    PRIMARY KEY(task_id, scenario_id)
);

CREATE TABLE IF NOT EXISTS task_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    level TEXT NOT NULL DEFAULT 'info',
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    hostname TEXT NOT NULL DEFAULT '',
    os_name TEXT NOT NULL DEFAULT '',
    agent_version TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'started',
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def _db_path() -> Path:
    path = Path(get_settings().db_path)
    if path.parent and str(path.parent) != ".":
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def one(query: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(query, tuple(params)).fetchone()


def all_rows(query: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(query, tuple(params)).fetchall()


def execute(query: str, params: Iterable[Any] = ()) -> int:
    with connect() as conn:
        cur = conn.execute(query, tuple(params))
        conn.commit()
        return int(cur.lastrowid or 0)


def execute_many(query: str, params_seq: Iterable[Iterable[Any]]) -> None:
    with connect() as conn:
        conn.executemany(query, [tuple(p) for p in params_seq])
        conn.commit()
