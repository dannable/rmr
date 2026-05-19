"""Spell-list and spell lookups (Channeling realm; Phase 1+2 schema)."""

from __future__ import annotations

import sqlite3


# ---------------------------------------------------------------------------
# classes / lists
# ---------------------------------------------------------------------------

def list_classes(conn: sqlite3.Connection) -> list[dict]:
    """All caster classes, ordered by realm then name."""
    return [dict(r) for r in conn.execute(
        """SELECT sc.name AS class_name, sr.name AS realm_name
             FROM spell_class sc
             JOIN spell_realm sr USING (realm_id)
            ORDER BY sr.name, sc.name"""
    ).fetchall()]


def search_classes(conn: sqlite3.Connection, prefix: str,
                   limit: int = 25) -> list[str]:
    """Case-insensitive substring match for autocomplete dropdowns."""
    rows = conn.execute(
        "SELECT name FROM spell_class WHERE LOWER(name) LIKE LOWER(?) "
        "ORDER BY name LIMIT ?",
        (f"%{prefix}%", limit),
    ).fetchall()
    return [r[0] for r in rows]


def lists_for_class(conn: sqlite3.Connection, class_name: str) -> list[dict]:
    """All lists accessible to the given class, grouped by category.

    Returns rows with: name, list_number, category. Sort is Base→Open→Closed
    then by list_number within each category.
    """
    rows = conn.execute(
        """SELECT sl.name, sl.list_number, sl.category
             FROM spell_list sl
             JOIN class_spell_list csl ON sl.list_id = csl.list_id
             JOIN spell_class sc ON sc.class_id = csl.class_id
            WHERE sc.name = ?
            ORDER BY CASE sl.category
                       WHEN 'Base'   THEN 1
                       WHEN 'Open'   THEN 2
                       WHEN 'Closed' THEN 3
                       ELSE 99
                     END,
                     -- Natural-sort list_number: "2.1.2" sorts before "2.1.10"
                     -- by ordering on (string length, value).
                     length(sl.list_number), sl.list_number""",
        (class_name,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_spell_lists(conn: sqlite3.Connection) -> list[dict]:
    """Every spell list across all realms (debug / /spells without args)."""
    return [dict(r) for r in conn.execute(
        """SELECT sl.name, sl.list_number, sl.category, sr.name AS realm_name
             FROM spell_list sl
             JOIN spell_realm sr USING (realm_id)
            ORDER BY length(sl.list_number), sl.list_number"""
    ).fetchall()]


def search_spell_lists(conn: sqlite3.Connection, prefix: str,
                       limit: int = 25) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM spell_list WHERE LOWER(name) LIKE LOWER(?) "
        "ORDER BY name LIMIT ?",
        (f"%{prefix}%", limit),
    ).fetchall()
    return [r[0] for r in rows]


def get_spell_list(conn: sqlite3.Connection, name: str) -> dict | None:
    """Look up a spell list by name (case-insensitive). Returns None if absent."""
    row = conn.execute(
        """SELECT sl.list_id, sl.name, sl.list_number, sl.category,
                  sr.name AS realm_name
             FROM spell_list sl
             JOIN spell_realm sr USING (realm_id)
            WHERE LOWER(sl.name) = LOWER(?)""",
        (name,),
    ).fetchone()
    return dict(row) if row else None


def spells_on_list(conn: sqlite3.Connection, list_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """SELECT level, name, area_effect, duration, range_str, spell_type,
                  starred, description
             FROM spell
            WHERE list_id = ?
            ORDER BY level""",
        (list_id,),
    ).fetchall()]


def classes_for_list(conn: sqlite3.Connection, list_id: int) -> list[str]:
    """Return the class names that have access to this list."""
    rows = conn.execute(
        """SELECT sc.name
             FROM spell_class sc
             JOIN class_spell_list csl ON sc.class_id = csl.class_id
            WHERE csl.list_id = ?
            ORDER BY sc.name""",
        (list_id,),
    ).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# individual spell lookup + search
# ---------------------------------------------------------------------------

def get_spell(conn: sqlite3.Connection, list_name: str,
              level: int) -> dict | None:
    """Look up one spell by its list name + level."""
    row = conn.execute(
        """SELECT s.level, s.name, s.area_effect, s.duration, s.range_str,
                  s.spell_type, s.starred, s.description,
                  sl.name AS list_name, sl.list_number, sl.category,
                  sr.name AS realm_name
             FROM spell s
             JOIN spell_list sl ON s.list_id = sl.list_id
             JOIN spell_realm sr ON sl.realm_id = sr.realm_id
            WHERE LOWER(sl.name) = LOWER(?) AND s.level = ?""",
        (list_name, level),
    ).fetchone()
    return dict(row) if row else None


def search_spells(conn: sqlite3.Connection, query: str,
                  limit: int = 25) -> list[dict]:
    """Search across all spells by name (case-insensitive substring).

    Returns rows with the spell + its containing list info.
    """
    rows = conn.execute(
        """SELECT s.level, s.name, s.spell_type,
                  sl.name AS list_name, sl.list_number, sl.category
             FROM spell s
             JOIN spell_list sl ON s.list_id = sl.list_id
            WHERE LOWER(s.name) LIKE LOWER(?)
            ORDER BY s.name, sl.list_number
            LIMIT ?""",
        (f"%{query}%", limit),
    ).fetchall()
    return [dict(r) for r in rows]
