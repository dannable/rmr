"""Read helpers for the skills catalog (RMSS Appendix A-1).

All reference data is loaded by load.py from data/skills/*.txt into the
skill_category_group / skill_category / skill / skill_table tables.
These helpers compose the rows back into the structured payload the web
API (and future skill DP allocator) consumes.
"""

from __future__ import annotations

import sqlite3


def list_skill_groups(conn: sqlite3.Connection) -> list[dict]:
    """All 34 category-groups, ordered by section."""
    rows = conn.execute(
        """SELECT slug, section, name, page_div, page_content
             FROM skill_category_group
            ORDER BY CAST(SUBSTR(section, 5) AS INTEGER)"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_skill_group(conn: sqlite3.Connection, slug: str) -> dict | None:
    """One group with everything nested: categories, skills, tables, rows."""
    row = conn.execute(
        """SELECT group_id, slug, section, name, page_div, page_content
             FROM skill_category_group WHERE slug = ?""",
        (slug,),
    ).fetchone()
    if row is None:
        return None
    g = dict(row)
    g["categories"] = [
        dict(r) for r in conn.execute(
            """SELECT name, skills_list, restricted, stat_bonuses,
                      rank_progression, category_progression, parent_group,
                      classification, description
                 FROM skill_category
                WHERE group_id = ?
                ORDER BY category_id""",
            (g["group_id"],),
        ).fetchall()
    ]
    g["skills"] = [
        dict(r) for r in conn.execute(
            """SELECT name, stat, description
                 FROM skill
                WHERE group_id = ?
                ORDER BY skill_id""",
            (g["group_id"],),
        ).fetchall()
    ]
    tables_rows = conn.execute(
        """SELECT table_id, name, columns
             FROM skill_table
            WHERE group_id = ?
            ORDER BY table_id""",
        (g["group_id"],),
    ).fetchall()
    g["tables"] = []
    for t in tables_rows:
        rows = conn.execute(
            """SELECT roll, result, percent, time, mod, description
                 FROM skill_table_row
                WHERE table_id = ?
                ORDER BY sort_order""",
            (t["table_id"],),
        ).fetchall()
        g["tables"].append({
            "name": t["name"],
            "columns": [c.strip() for c in (t["columns"] or "").split("|")],
            "rows": [dict(r) for r in rows],
        })
    return g


def search_skills(conn: sqlite3.Connection, query: str,
                  limit: int = 25) -> list[dict]:
    """Search skills by name (case-insensitive substring).

    Returns rows with skill metadata + the parent group's name and section
    so the SPA can deep-link to the group page.
    """
    rows = conn.execute(
        """SELECT s.name, s.stat, scg.slug AS group_slug,
                  scg.section, scg.name AS group_name
             FROM skill s
             JOIN skill_category_group scg ON s.group_id = scg.group_id
            WHERE LOWER(s.name) LIKE LOWER(?)
            ORDER BY s.name
            LIMIT ?""",
        (f"%{query}%", limit),
    ).fetchall()
    return [dict(r) for r in rows]
