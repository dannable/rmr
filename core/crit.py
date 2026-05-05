"""Critical strike chart lookups."""

from __future__ import annotations

import sqlite3

# Map cell-level crit-type letter (E.g. 'K' in '19EK') to canonical crit chart
# name. Matches the names of rows in critical_strike_table.
CRIT_TYPE_TO_TABLE = {
    "G": "Grapple", "K": "Krush", "P": "Puncture",
    "S": "Slash",   "T": "Tiny",  "U": "Unbalancing",
}


def list_crit_tables(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT name, table_number, column_axis FROM critical_strike_table "
        "ORDER BY table_number"
    ).fetchall()]


def search_crit_tables(conn: sqlite3.Connection, prefix: str, limit: int = 25) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM critical_strike_table WHERE LOWER(name) LIKE LOWER(?) "
        "ORDER BY name LIMIT ?",
        (f"%{prefix}%", limit),
    ).fetchall()
    return [r[0] for r in rows]


def resolve_crit_table_id(conn: sqlite3.Connection, attack: dict,
                          default_id: int | None) -> int | None:
    """Pick the crit chart for an attack-cell result.

    - If the cell carries a crit_type letter (K, S, P, ...), use the canonical
      table for that letter.
    - Otherwise fall back to the weapon's default_crit_table_id (used by
      Sweeps-style charts where every severity-only cell rolls on one chart).
    """
    if attack.get("crit_type"):
        name = CRIT_TYPE_TO_TABLE.get(attack["crit_type"])
        if not name:
            return None
        row = conn.execute(
            "SELECT crit_table_id FROM critical_strike_table WHERE name = ?",
            (name,),
        ).fetchone()
        return row[0] if row else None
    return default_id


def crit_lookup(conn: sqlite3.Connection, crit_table_id: int, severity: str,
                roll: int) -> dict | None:
    """Look up a crit cell by table id, severity column, and d100 roll.

    Returns a dict with the cell + an 'effects' list of effect rows.
    """
    res = conn.execute(
        """SELECT cr.roll_min, cr.roll_max, cr.severity, cr.narrative,
                  cst.name AS crit_table_name
             FROM critical_result cr
             JOIN critical_strike_table cst USING (crit_table_id)
            WHERE cr.crit_table_id = ? AND cr.severity = ?
              AND ? BETWEEN cr.roll_min AND cr.roll_max""",
        (crit_table_id, severity, roll),
    ).fetchone()
    if res is None:
        return None
    out = dict(res)
    out["effects"] = [dict(r) for r in conn.execute(
        """SELECT condition, raw_code FROM critical_result_effect
            WHERE crit_table_id = ? AND roll_min = ? AND severity = ?""",
        (crit_table_id, res["roll_min"], severity),
    ).fetchall()]
    return out


def crit_lookup_by_name(conn: sqlite3.Connection, table_name: str,
                        severity: str, roll: int) -> dict | None:
    """Convenience: look up a crit table by name, then run crit_lookup."""
    row = conn.execute(
        "SELECT crit_table_id FROM critical_strike_table WHERE name = ?",
        (table_name,),
    ).fetchone()
    if not row:
        return None
    return crit_lookup(conn, row[0], severity, roll)
