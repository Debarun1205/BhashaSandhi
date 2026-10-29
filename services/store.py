"""SQLite conversation history (a real database instead of an in-memory toy)."""
from __future__ import annotations

import os
import sqlite3
import time

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "team_j.db"))


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS turns(
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, ts REAL NOT NULL,
        lang TEXT, role TEXT NOT NULL, text TEXT NOT NULL, intent TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_session ON turns(session_id, id)")
    return c


def add_turn(session_id: str, role: str, text: str, lang: str | None = None, intent: str | None = None) -> None:
    with _conn() as c:
        c.execute("INSERT INTO turns(session_id, ts, lang, role, text, intent) VALUES (?,?,?,?,?,?)",
                  (session_id, time.time(), lang, role, text, intent))


def history(session_id: str, limit: int = 6) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT role, text, lang, intent, ts FROM turns WHERE session_id=? "
                         "ORDER BY id DESC LIMIT ?", (session_id, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]
