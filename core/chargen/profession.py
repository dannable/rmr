"""Profession lookups for the character builder.

The profession table is loaded by load.py from
data/chargen/professions/<slug>.txt (decoded from `ERA/*.era`). Keys
are stable `slug` values so characters can FK to profession_id safely
across reloads.

Source: RMSS Character Law profession entries, surfaced through the
Electronic Roleplaying Assistant export. ERA's `groupName` /
`categoryName` strings are preserved verbatim — they don't always
match our `skill_category_group.name` strings (ERA uses 25 broader
groups, RMSS Appendix A-1 splits into 34). A cross-walk will arrive
when the skill DP allocator needs it.
"""

from __future__ import annotations

import sqlite3


# ---------------------------------------------------------------------------
# helpers — read rows for one profession
# ---------------------------------------------------------------------------

def _fetch_child_rows(
    conn: sqlite3.Connection,
    table: str,
    profession_id: int,
    *,
    order_by: str = "",
) -> list[dict]:
    sql = f"SELECT * FROM {table} WHERE profession_id = ?"
    if order_by:
        sql += f" ORDER BY {order_by}"
    return [dict(r) for r in conn.execute(sql, (profession_id,)).fetchall()]


def _hydrate(conn: sqlite3.Connection, row: dict) -> dict:
    """Attach child collections to a base profession row."""
    pid = row["profession_id"]
    row["realms"] = [
        r["realm_name"] for r in _fetch_child_rows(
            conn, "profession_realm", pid, order_by="realm_name")
    ]
    row["prime_stats"] = [
        r["stat_code"] for r in _fetch_child_rows(
            conn, "profession_prime_stat", pid, order_by="stat_code")
    ]
    row["group_bonuses"] = [
        {"group_name": r["group_name"], "bonus": r["bonus"]}
        for r in _fetch_child_rows(
            conn, "profession_group_bonus", pid, order_by="group_name")
    ]
    row["category_bonuses"] = [
        {"group_name": r["group_name"],
         "category_name": r["category_name"],
         "bonus": r["bonus"]}
        for r in _fetch_child_rows(
            conn, "profession_category_bonus", pid,
            order_by="group_name, category_name")
    ]
    row["category_costs"] = [
        {"group_name": r["group_name"],
         "category_name": r["category_name"],
         "cost": r["cost"]}
        for r in _fetch_child_rows(
            conn, "profession_category_cost", pid,
            order_by="group_name, category_name")
    ]
    row["skill_cost_modifiers"] = [
        {"group_name": r["group_name"],
         "category_name": r["category_name"],
         "skill_name": r["skill_name"],
         "classification": r["classification"],
         "modifier": r["modifier"]}
        for r in _fetch_child_rows(
            conn, "profession_skill_cost_modifier", pid,
            order_by="group_name, category_name, skill_name")
    ]
    row["favorite_skills"] = [
        {"group_name": r["group_name"],
         "category_name": r["category_name"],
         "skill_name": r["skill_name"],
         "classification": r["classification"]}
        for r in _fetch_child_rows(
            conn, "profession_favorite_skill", pid, order_by="sort_order")
    ]
    return row


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def list_professions(conn: sqlite3.Connection) -> list[dict]:
    """Lightweight profession-row list for the picker.

    Returns one row per profession with name + slug + description +
    realms + prime stats (everything you need to render a picker grid).
    Bonuses, costs, and favorites are NOT included — call
    `get_profession_by_slug` for the full detail.
    """
    base_rows = [
        dict(r) for r in conn.execute(
            "SELECT profession_id, slug, name, description, portrait_path, source "
            "FROM profession ORDER BY name"
        ).fetchall()
    ]
    for row in base_rows:
        pid = row["profession_id"]
        row["realms"] = [
            r[0] for r in conn.execute(
                "SELECT realm_name FROM profession_realm WHERE profession_id = ? "
                "ORDER BY realm_name",
                (pid,),
            ).fetchall()
        ]
        row["prime_stats"] = [
            r[0] for r in conn.execute(
                "SELECT stat_code FROM profession_prime_stat WHERE profession_id = ? "
                "ORDER BY stat_code",
                (pid,),
            ).fetchall()
        ]
    return base_rows


def get_profession_by_id(conn: sqlite3.Connection, profession_id: int) -> dict | None:
    row = conn.execute(
        "SELECT profession_id, slug, name, description, portrait_path, source "
        "FROM profession WHERE profession_id = ?",
        (profession_id,),
    ).fetchone()
    if row is None:
        return None
    return _hydrate(conn, dict(row))


def get_profession_by_slug(conn: sqlite3.Connection, slug: str) -> dict | None:
    row = conn.execute(
        "SELECT profession_id, slug, name, description, portrait_path, source "
        "FROM profession WHERE slug = ?",
        (slug,),
    ).fetchone()
    if row is None:
        return None
    return _hydrate(conn, dict(row))
