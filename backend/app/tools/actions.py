"""
Tool 3 — state-changing action (escalation), with a mandatory confirmation
gate (§18/§45 item 5).

Flow the model MUST follow (enforced here, not just documented):
  1. prepare_escalation(...)  -> creates a PENDING_CONFIRMATION action, returns action_id.
     Nothing is executed yet.
  2. The user must send an explicit, separate confirmation for that exact
     action_id. A vague follow-up message ("yes", "ok", "sure") arriving as
     free text from the model does NOT count — the API layer requires the
     literal action_id and an explicit confirm=True.
  3. confirm_action(action_id, ctx) -> transitions PENDING_CONFIRMATION -> EXECUTED,
     and only then does the "write" happen (mocked here as an in-memory/DB record).
  4. Re-confirming an already-EXECUTED or CANCELLED action is rejected
     (no double execution / no replay).

This module intentionally holds state in SQLite so it survives process
restarts during the assessment/demo, and so the audit trail (§19) is real.
"""
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from app.security.auth import UserContext, require_account_access


ACTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS actions (
    action_id TEXT PRIMARY KEY,
    action_type TEXT NOT NULL,
    account_id TEXT,
    payload_json TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,           -- PENDING_CONFIRMATION | CONFIRMED | EXECUTED | CANCELLED | EXPIRED
    executed_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    user_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    detail TEXT NOT NULL,
    outcome TEXT NOT NULL
);
"""


@contextmanager
def _conn(db_path: str):
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    c.executescript(ACTIONS_SCHEMA)
    try:
        yield c
    finally:
        c.commit()
        c.close()


def _audit(conn, user_id: str, tool_name: str, detail: str, outcome: str):
    conn.execute(
        "INSERT INTO audit_log (timestamp, user_id, tool_name, detail, outcome) VALUES (?,?,?,?,?)",
        (datetime.now(timezone.utc).isoformat(), user_id, tool_name, detail, outcome),
    )


class ActionError(Exception):
    pass


def prepare_escalation(db_path: str, ctx: UserContext, account_id: str,
                        reason: str, related_id: str | None = None,
                        structured_db_path: str | None = None) -> dict:
    """Creates a PENDING_CONFIRMATION action. Does not execute anything."""
    require_account_access(ctx, account_id)

    if structured_db_path is not None:
        from app.data import db as _structured_db
        if _structured_db.get_account(structured_db_path, account_id) is None:
            raise ActionError(f"Cannot prepare escalation: no such account '{account_id}'")

    action_id = f"act_{uuid.uuid4().hex[:12]}"
    payload = {"reason": reason, "related_id": related_id}
    import json

    with _conn(db_path) as conn:
        conn.execute(
            """INSERT INTO actions
               (action_id, action_type, account_id, payload_json, created_by, created_at, status)
               VALUES (?,?,?,?,?,?,?)""",
            (action_id, "escalation", account_id, json.dumps(payload),
             ctx.user_id, datetime.now(timezone.utc).isoformat(), "PENDING_CONFIRMATION"),
        )
        _audit(conn, ctx.user_id, "prepare_escalation",
               f"action_id={action_id} account_id={account_id}", "PENDING_CONFIRMATION")

    return {
        "action_id": action_id,
        "action_type": "escalation",
        "account_id": account_id,
        "payload": payload,
        "status": "PENDING_CONFIRMATION",
    }


def confirm_action(db_path: str, ctx: UserContext, action_id: str, confirm: bool) -> dict:
    """
    The ONLY path that can move an action to EXECUTED. Requires the literal
    action_id (not inferred from conversation) and an explicit boolean.
    """
    with _conn(db_path) as conn:
        row = conn.execute("SELECT * FROM actions WHERE action_id = ?", (action_id,)).fetchone()
        if row is None:
            raise ActionError(f"No such action: {action_id}")

        action = dict(row)

        # ownership / access re-check at confirmation time too, not just at creation
        if action["account_id"]:
            require_account_access(ctx, action["account_id"])

        if action["status"] != "PENDING_CONFIRMATION":
            _audit(conn, ctx.user_id, "confirm_action",
                   f"action_id={action_id} rejected: status={action['status']}", "REJECTED_NOT_PENDING")
            raise ActionError(
                f"Action {action_id} is not pending confirmation (status={action['status']}); "
                f"cannot confirm or re-confirm."
            )

        if not confirm:
            conn.execute("UPDATE actions SET status = ? WHERE action_id = ?", ("CANCELLED", action_id))
            _audit(conn, ctx.user_id, "confirm_action", f"action_id={action_id}", "CANCELLED")
            return {"action_id": action_id, "status": "CANCELLED"}

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE actions SET status = ?, executed_at = ? WHERE action_id = ?",
            ("EXECUTED", now, action_id),
        )
        _audit(conn, ctx.user_id, "confirm_action", f"action_id={action_id}", "EXECUTED")
        return {"action_id": action_id, "status": "EXECUTED", "executed_at": now}


def get_action(db_path: str, action_id: str) -> dict | None:
    with _conn(db_path) as conn:
        row = conn.execute("SELECT * FROM actions WHERE action_id = ?", (action_id,)).fetchone()
        return dict(row) if row else None
