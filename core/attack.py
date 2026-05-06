"""Attack-table lookups and weapon metadata."""

from __future__ import annotations

import sqlite3

CRIT_TYPE_NAMES = {
    "G": "Grapple", "K": "Krush", "P": "Puncture",
    "S": "Slash",   "T": "Tiny",  "U": "Unbalance",
}
SIZE_NAMES = {1: "Small", 2: "Medium", 3: "Large", 4: "Huge"}
RANK_NAMES = {1: "Rank 1", 2: "Rank 2", 3: "Rank 3", 4: "Rank 4"}

# Per-term lookup. The key matches weapon.degree_term; default falls back
# to SIZE_NAMES so legacy weapon files (no @degree_term) keep working.
DEGREE_LABELS: dict[str, dict[int, str]] = {
    "Size": SIZE_NAMES,
    "Rank": RANK_NAMES,
}


def degree_label(term: str | None, degree: int) -> str:
    """Format the user-facing label for a degree value (e.g. 1→'Small' or 'Rank 1')."""
    return DEGREE_LABELS.get(term or "Size", SIZE_NAMES).get(degree, str(degree))


def get_weapon(conn: sqlite3.Connection, name: str) -> dict | None:
    """Look up a weapon by exact name. Returns None if not found."""
    row = conn.execute(
        """SELECT weapon_id, name, fumble_min, fumble_max, fumble_unmodified,
                  default_crit_table_id, fumble_table_name, fumble_column_index,
                  degree_term
             FROM weapon WHERE name = ?""",
        (name,),
    ).fetchone()
    return dict(row) if row else None


def list_weapons(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT name FROM weapon ORDER BY name"
    ).fetchall()]


def search_weapons(conn: sqlite3.Connection, prefix: str, limit: int = 25) -> list[str]:
    """Case-insensitive substring match for autocomplete dropdowns."""
    rows = conn.execute(
        "SELECT name FROM weapon WHERE LOWER(name) LIKE LOWER(?) "
        "ORDER BY name LIMIT ?",
        (f"%{prefix}%", limit),
    ).fetchall()
    return [r[0] for r in rows]


def attack_lookup(conn: sqlite3.Connection, weapon_id: int, at: int, total: int
                  ) -> tuple[dict | None, bool]:
    """Returns (result_or_None, was_capped).

    `was_capped` = True when the requested total exceeded the chart's max
    band for this AT and the highest-band result was returned instead.
    """
    row = conn.execute(
        """SELECT ar.raw, ar.hits, ar.crit_severity, ar.crit_type, ar.is_fumble,
                  ar.roll_min, ar.roll_max
             FROM attack_result ar
            WHERE ar.weapon_id = ? AND ar.armor_type = ?
              AND ? BETWEEN ar.roll_min AND ar.roll_max""",
        (weapon_id, at, total),
    ).fetchone()
    if row:
        return dict(row), False

    # Cap-out fallback: if the total is beyond the chart's top band, use it.
    max_row = conn.execute(
        """SELECT ar.raw, ar.hits, ar.crit_severity, ar.crit_type, ar.is_fumble,
                  ar.roll_min, ar.roll_max
             FROM attack_result ar
            WHERE ar.weapon_id = ? AND ar.armor_type = ?
            ORDER BY ar.roll_max DESC LIMIT 1""",
        (weapon_id, at),
    ).fetchone()
    if max_row and total > max_row["roll_max"]:
        return dict(max_row), True
    return None, False


def size_cap(conn: sqlite3.Connection, weapon_id: int, degree: int) -> int | None:
    """For Sweeps-style charts: max attack-roll total for a given attacker
    size degree (1=Small, 2=Medium, 3=Large, 4=Huge). None if no cap defined.
    """
    row = conn.execute(
        "SELECT max_roll FROM attack_table_size_cap "
        "WHERE weapon_id = ? AND degree = ?",
        (weapon_id, degree),
    ).fetchone()
    return row[0] if row else None
