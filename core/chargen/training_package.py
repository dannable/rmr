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

import math
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


# ---------------------------------------------------------------------------
# Flexible rank-assignment classification (TP weapon/skill selection)
# ---------------------------------------------------------------------------
#
# A "flexible" rank assignment (reference_label set) lets the player choose
# where its ranks land. Most are single-pick — one category + one skill —
# but some spread ranks across several targets ("3 ranks to category #1,
# 1 to #2"). The SPA's selection modal only resolves single-pick slots;
# multi-distribution slots are surfaced as a note and applied manually in
# Step 6. These pure helpers decide which bucket a slot falls into so the
# logic is unit-testable without a DB.


def skill_options_are_generic(skill_option_names: list[str]) -> bool:
    """True when a slot's skill options are all the same generic label
    (e.g. ['Languages', 'Languages']) rather than distinct named skills
    (e.g. ['Animal Training', 'Animal Mastery']).

    Generic-duplicate options mean "pick a specific skill yourself"
    (free text in the SPA); distinct options mean "choose one of these".
    Empty or single-option lists are not 'generic' in this sense."""
    if len(skill_option_names) < 2:
        return False
    return len(set(skill_option_names)) == 1


def slot_pick_counts(
    *,
    cat_ranks: int,
    skill_ranks: int,
    cat_spread_max: int | None,
    skill_spread_max: int | None,
    ranks_assigned_max: int | None,
    skill_option_names: list[str],
) -> tuple[int, int]:
    """How many DISTINCT category picks and skill picks a flexible slot
    wants, given its rank counts + spread constraints.

    Returns (n_category_picks, n_skill_picks). A value of 0 means that
    dimension grants no ranks; 1 means a single pick; >1 means the slot
    spreads ranks across multiple distinct targets (multi-distribution).

    Inference rules (most specific first):
      * explicit spread max (cat_spread_max / skill_spread_max) wins;
      * else, ranks_assigned_max (max ranks per single target) implies
        ceil(ranks / max) distinct picks when it's below the rank total;
      * else, duplicate-generic skill options (N copies of 'Languages')
        imply N distinct skill picks;
      * else a single pick."""
    def cat_picks() -> int:
        if cat_ranks <= 0:
            return 0
        if cat_spread_max:
            return cat_spread_max
        if ranks_assigned_max and ranks_assigned_max < cat_ranks:
            return math.ceil(cat_ranks / ranks_assigned_max)
        return 1

    def skill_picks() -> int:
        if skill_ranks <= 0:
            return 0
        if skill_spread_max:
            return skill_spread_max
        if ranks_assigned_max and ranks_assigned_max < skill_ranks:
            # ranks_assigned_max caps ranks per target, but only forces
            # multiple picks when the options are duplicate-generic
            # (N different languages) — a single named skill can legally
            # hold up to its own cap and the rest cascade in play. We use
            # the generic-options signal to decide.
            if skill_options_are_generic(skill_option_names):
                return math.ceil(skill_ranks / ranks_assigned_max)
            return 1
        if skill_options_are_generic(skill_option_names):
            return len(skill_option_names)
        return 1

    return (cat_picks(), skill_picks())


def slot_is_single_pick(
    *,
    cat_ranks: int,
    skill_ranks: int,
    cat_spread_max: int | None,
    skill_spread_max: int | None,
    ranks_assigned_max: int | None,
    skill_option_names: list[str],
) -> bool:
    """True when a flexible slot needs at most one category pick and at
    most one skill pick — the case the selection modal resolves."""
    n_cat, n_skill = slot_pick_counts(
        cat_ranks=cat_ranks, skill_ranks=skill_ranks,
        cat_spread_max=cat_spread_max, skill_spread_max=skill_spread_max,
        ranks_assigned_max=ranks_assigned_max,
        skill_option_names=skill_option_names,
    )
    return n_cat <= 1 and n_skill <= 1
