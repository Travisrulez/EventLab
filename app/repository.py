from __future__ import annotations

from typing import Any

from . import db
from .security import hash_password, hash_token, iso, parse_iso, utcnow


ROLES = {"admin", "operator", "viewer"}
TARGETS = {"windows", "linux", "ids"}
RUNNERS = {"powershell", "cmd", "bash"}


def create_user(username: str, password: str, role: str = "operator") -> int:
    if role not in ROLES:
        raise ValueError("unknown role")
    return db.execute(
        "INSERT INTO users(username, password_hash, role) VALUES (?, ?, ?)",
        (username.strip(), hash_password(password), role),
    )


def get_user_by_username(username: str):
    return db.one("SELECT * FROM users WHERE username = ?", (username.strip(),))


def get_user(user_id: int):
    return db.one("SELECT * FROM users WHERE id = ?", (user_id,))


def list_users():
    return db.all_rows("SELECT id, username, role, is_active, created_at, last_login_at FROM users ORDER BY id")


def update_login_success(user_id: int) -> None:
    db.execute(
        "UPDATE users SET failed_login_count = 0, locked_until = NULL, last_login_at = ? WHERE id = ?",
        (iso(), user_id),
    )


def update_login_failure(user_id: int, lock_until: str | None) -> None:
    db.execute(
        "UPDATE users SET failed_login_count = failed_login_count + 1, locked_until = COALESCE(?, locked_until) WHERE id = ?",
        (lock_until, user_id),
    )


def audit(user_id: int | None, action: str, details: str = "", ip: str = "") -> None:
    db.execute(
        "INSERT INTO audit_logs(user_id, action, details, ip) VALUES (?, ?, ?, ?)",
        (user_id, action, details[:2000], ip[:128]),
    )


def list_audit(limit: int = 100):
    return db.all_rows(
        """
        SELECT a.*, u.username
        FROM audit_logs a
        LEFT JOIN users u ON u.id = a.user_id
        ORDER BY a.id DESC
        LIMIT ?
        """,
        (limit,),
    )


def create_scenario(name: str, description: str, target_type: str, runner: str, script_body: str, created_by: int | None) -> int:
    if target_type not in TARGETS:
        raise ValueError("unknown target")
    if runner not in RUNNERS:
        raise ValueError("unknown runner")
    if not script_body.strip():
        raise ValueError("empty script")
    return db.execute(
        """
        INSERT INTO scenarios(name, description, target_type, runner, script_body, created_by)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (name.strip(), description.strip(), target_type, runner, script_body, created_by),
    )


def update_scenario(scenario_id: int, name: str, description: str, target_type: str, runner: str, script_body: str, is_active: bool) -> None:
    db.execute(
        """
        UPDATE scenarios SET name=?, description=?, target_type=?, runner=?, script_body=?, is_active=?
        WHERE id=?
        """,
        (name.strip(), description.strip(), target_type, runner, script_body, 1 if is_active else 0, scenario_id),
    )


def get_scenario(scenario_id: int):
    return db.one("SELECT * FROM scenarios WHERE id = ?", (scenario_id,))


def list_scenarios(target_type: str | None = None, active_only: bool = False):
    q = "SELECT s.*, u.username AS created_by_name FROM scenarios s LEFT JOIN users u ON u.id=s.created_by WHERE 1=1"
    params: list[Any] = []
    if target_type:
        q += " AND s.target_type = ?"
        params.append(target_type)
    if active_only:
        q += " AND s.is_active = 1"
    q += " ORDER BY s.target_type, s.name"
    return db.all_rows(q, params)


def create_task(
    title: str,
    target_type: str,
    event_count: int,
    delay_ms: int,
    target_host: str,
    target_port: int,
    token: str,
    token_preview: str,
    expires_at: str,
    created_by: int,
    scenario_ids: list[int],
    is_load_test: bool = False,
) -> int:
    task_id = db.execute(
        """
        INSERT INTO tasks(title, target_type, event_count, delay_ms, target_host, target_port, token_hash, token_preview, expires_at, created_by, is_load_test)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title.strip(),
            target_type,
            int(event_count),
            int(delay_ms),
            target_host.strip(),
            int(target_port or 0),
            hash_token(token),
            token_preview,
            expires_at,
            created_by,
            1 if is_load_test else 0,
        ),
    )
    db.execute_many(
        "INSERT INTO task_scenarios(task_id, scenario_id) VALUES (?, ?)",
        [(task_id, sid) for sid in scenario_ids],
    )
    return task_id


def get_task(task_id: int):
    return db.one(
        """
        SELECT t.*, u.username AS created_by_name
        FROM tasks t
        LEFT JOIN users u ON u.id=t.created_by
        WHERE t.id = ?
        """,
        (task_id,),
    )


def get_task_by_token(token: str):
    return db.one("SELECT * FROM tasks WHERE token_hash = ?", (hash_token(token),))


def task_scenarios(task_id: int):
    return db.all_rows(
        """
        SELECT s.* FROM scenarios s
        JOIN task_scenarios ts ON ts.scenario_id = s.id
        WHERE ts.task_id = ?
        ORDER BY s.id
        """,
        (task_id,),
    )


def list_tasks(limit: int = 50):
    return db.all_rows(
        """
        SELECT t.*, u.username AS created_by_name,
               (SELECT COUNT(*) FROM task_scenarios ts WHERE ts.task_id=t.id) AS scenario_count
        FROM tasks t
        LEFT JOIN users u ON u.id=t.created_by
        ORDER BY t.id DESC
        LIMIT ?
        """,
        (limit,),
    )


def set_task_status(task_id: int, status: str) -> None:
    if status == "running":
        db.execute("UPDATE tasks SET status=?, started_at=COALESCE(started_at, ?) WHERE id=?", (status, iso(), task_id))
    elif status in {"completed", "failed", "expired", "cancelled"}:
        db.execute("UPDATE tasks SET status=?, finished_at=COALESCE(finished_at, ?) WHERE id=?", (status, iso(), task_id))
    else:
        db.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))


def add_task_log(task_id: int, level: str, message: str) -> int:
    return db.execute(
        "INSERT INTO task_logs(task_id, level, message) VALUES (?, ?, ?)",
        (task_id, level[:32], message[:5000]),
    )


def task_logs(task_id: int, limit: int = 500):
    return db.all_rows(
        "SELECT * FROM task_logs WHERE task_id=? ORDER BY id ASC LIMIT ?",
        (task_id, limit),
    )


def create_agent_run(task_id: int, hostname: str, os_name: str, agent_version: str) -> int:
    return db.execute(
        "INSERT INTO agent_runs(task_id, hostname, os_name, agent_version) VALUES (?, ?, ?, ?)",
        (task_id, hostname[:255], os_name[:255], agent_version[:64]),
    )


def finish_agent_run(run_id: int, status: str) -> None:
    db.execute("UPDATE agent_runs SET status=?, finished_at=? WHERE id=?", (status[:64], iso(), run_id))


def list_agent_runs(task_id: int):
    return db.all_rows("SELECT * FROM agent_runs WHERE task_id=? ORDER BY id DESC", (task_id,))


def delete_task(task_id: int) -> int:
    with db.connect() as conn:
        cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        return int(cur.rowcount or 0)


def delete_old_tasks(older_than_days: int = 7) -> int:
    days = max(1, min(int(older_than_days), 3650))
    with db.connect() as conn:
        cur = conn.execute(
            """
            DELETE FROM tasks
            WHERE status IN ('completed', 'failed', 'expired', 'cancelled')
              AND datetime(created_at) < datetime('now', ?)
            """,
            (f"-{days} days",),
        )
        conn.commit()
        return int(cur.rowcount or 0)
