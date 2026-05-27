"""Per-character weapon-cost assignments.

RMSS Character Law §6.2: a profession's profession_category_cost rows
pre-assign each weapon category a cost like "1/5", "2/7", "5". The
player has full freedom to swap these costs around among the standard
weapon categories — the MULTISET of costs (the "weapon-cost pool")
stays the same, but the player picks which category gets which cost.

This module reads + validates per-character reassignments. The
authoritative storage is `character_weapon_cost_assignment` — rows
override the profession defaults; absence falls through to
profession_category_cost.

A Fighter, for example, has the pool {1/5, 2/5, 2/7, 2/7, 2/7, 5, 5}
across seven weapon categories. The player can assign 1/5 to 2-Handed
and 2/5 to Pole Arms (instead of the defaults) without changing the
profession's overall DP-cost ceiling for weapons.
"""

from __future__ import annotations

import sqlite3
from collections import Counter

# Group label used on profession_category_cost.group_name for weapon rows.
WEAPON_GROUP_NAME = "Weapon"


def profession_weapon_costs(
    conn: sqlite3.Connection,
    profession_id: int,
) -> dict[str, str]:
    """Return {weapon_category: cost} for the profession's WEAPON rows.

    Empty dict when the profession has no Weapon costs (rare — every
    standard profession has weapons, but a custom-loaded one might not).
    """
    rows = conn.execute(
        "SELECT category_name, cost FROM profession_category_cost "
        "WHERE profession_id = ? AND group_name = ? "
        "ORDER BY category_name",
        (profession_id, WEAPON_GROUP_NAME),
    ).fetchall()
    return {r["category_name"] if hasattr(r, "keys") else r[0]:
            r["cost"] if hasattr(r, "keys") else r[1]
            for r in rows}


def character_weapon_cost_overrides(
    conn: sqlite3.Connection,
    character_id: int,
) -> dict[str, str]:
    """Return {weapon_category: cost} from character_weapon_cost_assignment.

    Empty dict when the character hasn't reassigned anything — the
    caller should fall through to profession defaults in that case.
    """
    rows = conn.execute(
        "SELECT weapon_category, cost "
        "FROM character_weapon_cost_assignment "
        "WHERE character_id = ?",
        (character_id,),
    ).fetchall()
    return {(r["weapon_category"] if hasattr(r, "keys") else r[0]):
            (r["cost"] if hasattr(r, "keys") else r[1])
            for r in rows}


def effective_weapon_costs(
    conn: sqlite3.Connection,
    character_id: int,
    profession_id: int | None,
) -> dict[str, str]:
    """Resolve the character's CURRENT cost per weapon category.

    If the character has overrides → use them (assumed to cover every
    profession weapon category; the PUT endpoint enforces "all or none").
    Otherwise → fall through to the profession defaults.

    Returns an empty dict when profession_id is None (no profession picked).
    """
    if profession_id is None:
        return {}
    overrides = character_weapon_cost_overrides(conn, character_id)
    defaults = profession_weapon_costs(conn, profession_id)
    if not overrides:
        return defaults
    # Overrides win per category; fall through to default for any
    # category the override list didn't touch (shouldn't happen if the
    # PUT enforced "all or none", but be defensive).
    out = dict(defaults)
    out.update(overrides)
    return out


class WeaponCostAssignmentError(ValueError):
    """Raised when a proposed assignment isn't a valid permutation of the
    profession's weapon-cost pool — wrong categories, wrong cost
    multiset, etc. The API turns this into a 422 with the message."""


def validate_assignments(
    profession_pool: dict[str, str],
    assignments: dict[str, str],
) -> None:
    """Raise WeaponCostAssignmentError if `assignments` is not a valid
    permutation of `profession_pool`.

    Rules:
      1. Every category in `assignments` must appear in `profession_pool`
         (no inventing weapon categories the profession doesn't have).
      2. Every category in `profession_pool` must be assigned (all-or-
         nothing — a partial reassignment is ambiguous: does the unset
         category keep its default, or get the leftover cost?).
      3. The multiset of values in `assignments` must equal the multiset
         of values in `profession_pool` — same costs, different mapping.
    """
    if not profession_pool:
        raise WeaponCostAssignmentError(
            "Character has no profession-derived weapon costs to reassign."
        )
    pool_cats = set(profession_pool.keys())
    given_cats = set(assignments.keys())

    extra = given_cats - pool_cats
    if extra:
        raise WeaponCostAssignmentError(
            f"Unknown weapon categories: {sorted(extra)}. "
            f"Valid: {sorted(pool_cats)}."
        )
    missing = pool_cats - given_cats
    if missing:
        raise WeaponCostAssignmentError(
            f"Missing weapon categories: {sorted(missing)}. "
            "All profession weapon categories must be assigned (all-or-nothing)."
        )

    pool_multiset = Counter(profession_pool.values())
    given_multiset = Counter(assignments.values())
    if pool_multiset != given_multiset:
        # Build a human-readable diff so the API error explains what's off.
        extra_costs = (given_multiset - pool_multiset).most_common()
        missing_costs = (pool_multiset - given_multiset).most_common()
        bits = []
        if extra_costs:
            bits.append("extra: " + ", ".join(f"{c}×{n}" for c, n in extra_costs))
        if missing_costs:
            bits.append("missing: " + ", ".join(f"{c}×{n}" for c, n in missing_costs))
        raise WeaponCostAssignmentError(
            "Cost multiset doesn't match the profession's weapon-cost pool — "
            + "; ".join(bits) + "."
        )


def set_assignments(
    conn: sqlite3.Connection,
    character_id: int,
    assignments: dict[str, str],
) -> None:
    """Replace the character's weapon-cost overrides wholesale.

    The caller is expected to have validated against the profession pool
    first (via validate_assignments). This function just writes — it
    DELETEs everything for the character and re-INSERTs the new set.
    """
    conn.execute(
        "DELETE FROM character_weapon_cost_assignment WHERE character_id = ?",
        (character_id,),
    )
    if not assignments:
        return   # caller asked to clear (revert to defaults)
    conn.executemany(
        "INSERT INTO character_weapon_cost_assignment "
        "(character_id, weapon_category, cost) VALUES (?, ?, ?)",
        [(character_id, cat, cost) for cat, cost in assignments.items()],
    )


def rank_cap_for_cost(cost: str) -> int:
    """Maximum ranks-per-level for a cost string.

    The cost is one or more DP values separated by `/` — e.g. "1/5" =
    up to 2 ranks/level (1 DP for the first, 5 for the second), "2/2/2"
    = up to 3 ranks/level, "5" = 1 rank/level. Used by hobby-rank caps
    (Phase C) and the DP allocator (Phase B).
    """
    if not cost or not cost.strip():
        return 0
    return len([t for t in cost.split("/") if t.strip()])
