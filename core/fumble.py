"""Fumble-table lookups and crit-chain parsing."""

from __future__ import annotations

import re
import sqlite3

# Maps a crit-type word as it appears in fumble narratives ("'A' Krush critical")
# to the canonical critical_strike_table.name. Anything not in the map is
# tried verbatim and falls through if no chart with that name is loaded.
CRIT_WORD_TO_TABLE = {
    "Krush":     "Krush",
    "Slash":     "Slash",
    "Puncture":  "Puncture",
    "Grapple":   "Grapple",
    "Tiny":      "Tiny",
    "Unbalance": "Unbalancing",
    "Brawling":  "Brawling",
    "Subdual":   "Subdual",
}

# Pattern in fumble narratives: e.g. "Take an 'A' Krush critical".
# Group 1 = severity letter; Group 2 = type word.
FUMBLE_CRIT_RE = re.compile(r"'([A-E])'\s+([A-Z][a-z]+)\s+critical")


def list_fumble_tables(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT name, table_number FROM fumble_table ORDER BY table_number"
    ).fetchall()]


def search_fumble_tables(conn: sqlite3.Connection, prefix: str, limit: int = 25) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM fumble_table WHERE LOWER(name) LIKE LOWER(?) "
        "ORDER BY name LIMIT ?",
        (f"%{prefix}%", limit),
    ).fetchall()
    return [r[0] for r in rows]


def fumble_columns(conn: sqlite3.Connection, table_name: str) -> list[dict]:
    """List the columns (col_index, col_name) defined on a fumble table."""
    return [dict(r) for r in conn.execute(
        """SELECT ftc.col_index, ftc.col_name
             FROM fumble_table_column ftc
             JOIN fumble_table ft USING (fumble_table_id)
            WHERE ft.name = ? ORDER BY ftc.col_index""",
        (table_name,),
    ).fetchall()]


def fumble_lookup(conn: sqlite3.Connection, table_name: str, col_index: int,
                  roll: int) -> dict | None:
    row = conn.execute(
        """SELECT fr.roll_min, fr.roll_max, fr.narrative, ftc.col_name,
                  ft.name AS table_name
             FROM fumble_result fr
             JOIN fumble_table ft USING (fumble_table_id)
             JOIN fumble_table_column ftc
               ON ftc.fumble_table_id = fr.fumble_table_id
              AND ftc.col_index       = fr.col_index
            WHERE ft.name = ? AND fr.col_index = ?
              AND ? BETWEEN fr.roll_min AND fr.roll_max""",
        (table_name, col_index, roll),
    ).fetchone()
    return dict(row) if row else None


def parse_fumble_crit_chain(narrative: str | None) -> tuple[str, str] | None:
    """If a fumble narrative says e.g. "Take an 'A' Krush critical", return
    (severity, canonical_chart_name). Otherwise None.
    """
    if not narrative:
        return None
    m = FUMBLE_CRIT_RE.search(narrative)
    if not m:
        return None
    sev, word = m.group(1), m.group(2)
    return sev, CRIT_WORD_TO_TABLE.get(word, word)
