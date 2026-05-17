"""SQLite helpers for the web app.

We re-use core.db.connect for read-only paths and provide a writable variant
plus app_user upsert here. Schema.sql is the source of truth — run
`python load.py --reset` to (re)create tables.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from core.db import DB_PATH


def connect_rw() -> sqlite3.Connection:
    """Open a connection with foreign keys enabled.

    Unlike core.db.connect this does NOT require the DB file to exist —
    the load.py path will create it. We still raise if the parent dir is missing.
    """
    parent = Path(DB_PATH).parent
    if not parent.exists():
        raise FileNotFoundError(f"DB parent dir does not exist: {parent}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_app_user(
    conn: sqlite3.Connection,
    *,
    discord_id: str,
    discord_username: str | None,
    discord_avatar: str | None,
) -> dict:
    """Insert-or-update an app_user row keyed by discord_id. Returns the row."""
    now = _utcnow()
    cur = conn.execute(
        """
        INSERT INTO app_user (discord_id, discord_username, discord_avatar,
                              created_at, last_login_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(discord_id) DO UPDATE SET
            discord_username = excluded.discord_username,
            discord_avatar   = excluded.discord_avatar,
            last_login_at    = excluded.last_login_at
        RETURNING user_id, discord_id, discord_username, discord_avatar,
                  created_at, last_login_at
        """,
        (discord_id, discord_username, discord_avatar, now, now),
    )
    row = cur.fetchone()
    conn.commit()
    return dict(row)


def get_app_user(conn: sqlite3.Connection, user_id: int) -> dict | None:
    cur = conn.execute(
        "SELECT user_id, discord_id, discord_username, discord_avatar, "
        "created_at, last_login_at FROM app_user WHERE user_id = ?",
        (user_id,),
    )
    row = cur.fetchone()
    return dict(row) if row else None
