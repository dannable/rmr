"""SQLite connection helper for RMR.

DB path comes from the DB_PATH env var, falling back to ./rmfrp.db at the
project root. The env-var override is what the Docker container uses to point
at a mounted volume.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("DB_PATH", _PROJECT_ROOT / "rmfrp.db"))


def connect() -> sqlite3.Connection:
    """Open a connection. Rows come back as sqlite3.Row (dict-like)."""
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"DB not found at {DB_PATH}. Run: python load.py --reset"
        )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
