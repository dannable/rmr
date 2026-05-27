"""Training-package lookups for the character builder.

The training_package table is loaded by load.py from
data/chargen/training_packages/<slug>.txt (decoded from
`ERA/rmfrpCharacterLaw.trainingPackages.era`).

Same naming caveat as professions: ERA's group / category strings are
preserved verbatim rather than FK'd into our `skill_category_group`
table. The DP allocator will cross-walk them when it lands.

The `profession_name` strings on training_package_profession_cost cover
~60 professions from RMSS Core + Companion expansions — wider than our
20-profession set. List + detail responses return them as-is; consumers
that need to filter to "professions we actually know" can join against
`profession.name` at query time.
"""

from __future__ import annotations

import sqlite3


def _fetch_children(
    conn: sqlite3.Connection,
    table: str,
    tpid: int,
    *,
    order_by: str = "sort_order",
) -> list[dict]:
    return [dict(r) for r in conn.execute(
        f"SELECT * FROM {table} WHERE training_package_id = ? ORDER BY {order_by}",
        (tpid,),
    ).fetchall()]


def list_training_packages(conn: sqlite3.Connection) -> list[dict]:
    """Lightweight TP rows for the browse grid.

    Each row carries slug + name + category + description +
    default_cost (no specials / rank-assignments / per-profession costs —
    fetch the detail endpoint for those).
    """
    return [dict(r) for r in conn.execute(
        "SELECT slug, name, category, description, default_cost, source "
        "FROM training_package ORDER BY name"
    ).fetchall()]


def get_training_package_by_slug(conn: sqlite3.Connection,
                                 slug: str) -> dict | None:
    """One TP, fully hydrated: specials + stat gains + rank assignments
    (with category / skill options) + per-profession DP costs."""
    row = conn.execute(
        "SELECT training_package_id, slug, name, category, description, "
        "       default_cost, source "
        "FROM training_package WHERE slug = ?",
        (slug,),
    ).fetchone()
    if row is None:
        return None
    tp = dict(row)
    tpid = tp["training_package_id"]

    tp["specials"] = [
        {"chance": r["chance"], "description": r["description"]}
        for r in _fetch_children(conn, "training_package_special", tpid)
    ]

    # Stat gains: for choice slots, look up their choice rows.
    sg_rows = _fetch_children(conn, "training_package_stat_gain", tpid)
    stat_gains: list[dict] = []
    for sg in sg_rows:
        if sg["has_choice"]:
            choices = [
                r[0] for r in conn.execute(
                    "SELECT stat_code FROM training_package_stat_gain_choice "
                    "WHERE training_package_id = ? AND sort_order = ? "
                    "ORDER BY stat_code",
                    (tpid, sg["sort_order"]),
                ).fetchall()
            ]
            stat_gains.append({"stat_code": None, "choices": choices})
        else:
            stat_gains.append({"stat_code": sg["stat_code"], "choices": []})
    tp["stat_gains"] = stat_gains

    # Rank assignments: pull each plus its category + skill options.
    ras = _fetch_children(conn, "training_package_rank_assignment", tpid)
    rank_assignments: list[dict] = []
    for ra in ras:
        order = ra["sort_order"]
        cat_opts = [
            {"group_name": r["group_name"], "category_name": r["category_name"]}
            for r in conn.execute(
                "SELECT group_name, category_name "
                "FROM training_package_ra_category_option "
                "WHERE training_package_id = ? AND sort_order = ? "
                "ORDER BY option_index",
                (tpid, order),
            ).fetchall()
        ]
        skill_opts = [
            {"skill_name": r["skill_name"], "classification": r["classification"]}
            for r in conn.execute(
                "SELECT skill_name, classification "
                "FROM training_package_ra_skill_option "
                "WHERE training_package_id = ? AND sort_order = ? "
                "ORDER BY option_index",
                (tpid, order),
            ).fetchall()
        ]
        rank_assignments.append({
            "reference_label":    ra["reference_label"],
            "group_name":         ra["group_name"],
            "category_name":      ra["category_name"],
            "cat_ranks":          ra["cat_ranks"],
            "skill_ranks":        ra["skill_ranks"],
            "cat_spread_max":     ra["cat_spread_max"],
            "skill_spread_max":   ra["skill_spread_max"],
            "ranks_assigned_max": ra["ranks_assigned_max"],
            "category_options":   cat_opts,
            "skill_options":      skill_opts,
        })
    tp["rank_assignments"] = rank_assignments

    tp["profession_costs"] = [
        {"profession_name": r["profession_name"], "cost": r["cost"]}
        for r in conn.execute(
            "SELECT profession_name, cost FROM training_package_profession_cost "
            "WHERE training_package_id = ? ORDER BY profession_name",
            (tpid,),
        ).fetchall()
    ]

    # Drop internal id before returning so callers don't accidentally
    # leak it through to the API surface.
    tp.pop("training_package_id", None)
    return tp
