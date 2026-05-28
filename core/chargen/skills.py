"""Skill bonus calculation + DP cost lookup + purchase-state aggregation.

RMSS Character Law §6 — Development Point allocation. The player spends
DP to buy category and skill ranks; the total skill bonus is:

    category_progression(category_ranks)         (category contribution)
  + skill_progression(skill_ranks)               (skill contribution)
  + stat_bonus(skill's relevant stats)           (stat contribution)
  + profession_category_bonus + group_bonus      (profession contribution)

Plus race bonuses, item bonuses, and TP-granted bonuses on top — those
layer in elsewhere as the SPA gains those features. This module focuses
on the chargen-time math (level 1) and the per-rank purchase mechanics.

Cost format ("2/5", "5", "2/2/2"):
  - Slash-separated tokens give the DP cost per rank, starting at the
    1st rank for that level. "2/5" = 1st rank costs 2 DP, 2nd costs 5,
    no 3rd rank/level (cap = 2).
  - A single number ("5") means 1 rank/level at 5 DP.
  - Weapon category costs are subject to character_weapon_cost_assignment
    overrides — see core.chargen.weapon_costs for the lookup helper.

Standard skill rank progression (RMSS T-2.2):
  - Ranks  1-10: +5 per rank
  - Ranks 11-20: +2 per rank
  - Ranks 21-30: +1 per rank
  - Ranks 31+:   +0.5 per rank  (we store the float; SPA rounds for display)
"""

from __future__ import annotations

import sqlite3
from typing import Iterable

from .stats import basic_stat_bonus, STAT_CODES, StatCode


# ---------------------------------------------------------------------------
# Cost parsing + rank-cap derivation
# ---------------------------------------------------------------------------

def parse_cost(cost: str) -> list[int]:
    """Tokens of the cost string as a list of ints.

    "2/5" → [2, 5]; "5" → [5]; "2/2/2" → [2, 2, 2]; "" → []. Non-numeric
    tokens (rare; some custom-loaded data uses "—" for "untrainable")
    are dropped, so an "untrainable" cost yields [].
    """
    if not cost or not cost.strip():
        return []
    tokens = [t.strip() for t in cost.split("/")]
    out: list[int] = []
    for t in tokens:
        try:
            out.append(int(t))
        except ValueError:
            continue
    return out


def rank_cap_per_level(cost: str) -> int:
    """Maximum ranks the character can buy this level for a given cost."""
    return len(parse_cost(cost))


def dp_for_rank(cost: str, rank_within_level: int) -> int | None:
    """Cost in DP for buying the Nth rank THIS LEVEL (1-indexed).

    Returns None when the rank is beyond the per-level cap (the caller
    should refuse the purchase). When the cost string is empty / has no
    numeric tokens (untrainable), every rank returns None.
    """
    tokens = parse_cost(cost)
    if rank_within_level < 1 or rank_within_level > len(tokens):
        return None
    return tokens[rank_within_level - 1]


def cumulative_cost(cost: str, ranks_within_level: int) -> int | None:
    """Total DP to buy `ranks_within_level` ranks at this level.

    Returns None if the requested count exceeds the per-level cap.
    """
    tokens = parse_cost(cost)
    if ranks_within_level < 0 or ranks_within_level > len(tokens):
        return None
    return sum(tokens[:ranks_within_level])


# ---------------------------------------------------------------------------
# Rank → bonus progressions
# ---------------------------------------------------------------------------

def standard_skill_bonus(ranks: int) -> float:
    """RMSS T-2.2 standard skill rank progression.

    1-10: +5/rank  →  10 ranks = 50
    11-20: +2/rank → 20 ranks = 70
    21-30: +1/rank → 30 ranks = 80
    31+: +0.5/rank → 50 ranks = 90
    """
    if ranks <= 0:
        return 0.0
    bonus = 0.0
    if ranks > 30:
        bonus += 0.5 * (ranks - 30)
        ranks = 30
    if ranks > 20:
        bonus += 1.0 * (ranks - 20)
        ranks = 20
    if ranks > 10:
        bonus += 2.0 * (ranks - 10)
        ranks = 10
    bonus += 5.0 * ranks
    return bonus


def standard_category_bonus(ranks: int) -> float:
    """Standard category rank progression (T-2.2).

    Same shape as the skill progression but half the weight per rank
    band: +2 / +1 / +0.5 / +0.25. Most "Standard" categories use this.
    """
    if ranks <= 0:
        return 0.0
    bonus = 0.0
    if ranks > 30:
        bonus += 0.25 * (ranks - 30)
        ranks = 30
    if ranks > 20:
        bonus += 0.5 * (ranks - 20)
        ranks = 20
    if ranks > 10:
        bonus += 1.0 * (ranks - 10)
        ranks = 10
    bonus += 2.0 * ranks
    return bonus


def parse_dotted_progression(text: str) -> list[float]:
    """Parse a "0 • 7 • 5 • 3 • 1"-style progression string.

    Returns the 5 floats (or whatever the source has). Empty when the
    progression is "Standard", "Combined", or otherwise non-numeric —
    callers fall back to standard_*_bonus in that case.
    """
    if not text or not text.strip():
        return []
    tokens = []
    for t in text.replace("•", "·").split("·"):
        t = t.strip()
        if not t:
            continue
        try:
            tokens.append(float(t))
        except ValueError:
            return []   # any non-numeric token → bail out
    return tokens


def progression_bonus(progression_text: str, default_fn, ranks: int) -> float:
    """Compute the rank bonus for a progression string.

    - "Standard" / "Combined" / empty → fall through to default_fn(ranks)
      (default_fn is standard_skill_bonus for skills, standard_category_bonus
      for categories)
    - Otherwise parse the dotted form "0 • 7 • 5 • 3 • 1" and apply the
      same band scheme: token[0] = bonus per rank for ranks 1-10,
      token[1] = per rank for 11-20, ..., token[4] = 41+.

    Body Development's "0 • 0 • 0 • 0 • 0" yields 0 bonus regardless of
    ranks — Body Dev contributes hits, not a skill bonus, and the
    race-specific body_dev_prog drives that hit count separately.
    """
    txt = (progression_text or "").strip()
    if txt in ("", "Standard", "Combined"):
        return default_fn(ranks)
    tokens = parse_dotted_progression(txt)
    if not tokens:
        return default_fn(ranks)
    # Apply per-band: token i covers ranks in band [10*i+1, 10*i+10].
    bonus = 0.0
    remaining = max(0, ranks)
    band = 0
    while remaining > 0 and band < len(tokens):
        take = min(remaining, 10)
        bonus += tokens[band] * take
        remaining -= take
        band += 1
    # Past the last band, no more bonus (most progressions stop at band 4
    # because they're either zero or so small).
    return bonus


# ---------------------------------------------------------------------------
# Stat-bonus lookup for a skill / category
# ---------------------------------------------------------------------------

def parse_stat_codes(stat_str: str | None) -> list[StatCode]:
    """Parse a "St/Ag/St"-style stat-bonus key into a list of StatCodes.

    Returns [] for "no stat bonus" / empty / unparseable. Duplicates ARE
    preserved — "St/Ag/St" means St is counted twice when the bonuses
    are summed.
    """
    if not stat_str or not stat_str.strip():
        return []
    if "no stat bonus" in stat_str.lower():
        return []
    out: list[StatCode] = []
    for t in stat_str.split("/"):
        t = t.strip()
        if t in STAT_CODES:
            out.append(t)  # type: ignore[arg-type]
    return out


def stat_bonus_for(stat_str: str | None, raw_temps: dict[StatCode, int]) -> int:
    """Sum the T-2.1 bonuses for each stat code in the slash-separated list."""
    codes = parse_stat_codes(stat_str)
    if not codes:
        return 0
    return sum(basic_stat_bonus(int(raw_temps[c])) for c in codes if c in raw_temps)


# ---------------------------------------------------------------------------
# DB lookups
# ---------------------------------------------------------------------------

def _row_dict(row) -> dict:
    return dict(row) if hasattr(row, "keys") else {}


def list_skill_categories(conn: sqlite3.Connection) -> list[dict]:
    """All skill categories with their group + progression metadata.

    Returned columns: group_name, category_name (full, with "Group • "
    prefix stripped), rank_progression, category_progression, stat_bonuses,
    classification.
    """
    rows = conn.execute("""
        SELECT g.name AS group_name,
               sc.name AS category_name,
               sc.rank_progression,
               sc.category_progression,
               sc.stat_bonuses,
               sc.classification
          FROM skill_category sc
          JOIN skill_category_group g ON g.group_id = sc.group_id
         ORDER BY g.name, sc.name
    """).fetchall()
    return [_row_dict(r) for r in rows]


def list_skills_in_category(
    conn: sqlite3.Connection,
    group_name: str,
    category_name: str,
) -> list[dict]:
    """Skills filed under a given group + category.

    `category_name` here is the FULL category name as stored in
    `skill_category.name` (e.g. "Weapon • 1-H Edged"). The skill table
    doesn't carry a category FK directly, but `skills_list` on
    skill_category lists them by comma-separated names.
    """
    sc = conn.execute("""
        SELECT sc.category_id, sc.skills_list
          FROM skill_category sc
          JOIN skill_category_group g ON g.group_id = sc.group_id
         WHERE g.name = ? AND sc.name = ?
    """, (group_name, category_name)).fetchone()
    if sc is None:
        return []
    sc = _row_dict(sc)
    # skills_list is a comma-separated string of skill names. Skills
    # themselves live in the `skill` table with group_id matching the
    # category's group. Pull all skills in the same group that match
    # any entry in skills_list.
    raw = sc.get("skills_list") or ""
    expected = {s.strip() for s in raw.split(",") if s.strip() and s.strip() != "-"}
    if not expected:
        return []
    placeholders = ",".join("?" * len(expected))
    rows = conn.execute(f"""
        SELECT s.name, s.stat
          FROM skill s
          JOIN skill_category_group g ON g.group_id = s.group_id
         WHERE g.name = ? AND s.name IN ({placeholders})
         ORDER BY s.name
    """, (group_name, *sorted(expected))).fetchall()
    return [_row_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Per-character purchase aggregation
# ---------------------------------------------------------------------------

def category_purchase_state(
    conn: sqlite3.Connection,
    character_id: int,
    level: int = 1,
) -> dict[tuple[str, str], dict]:
    """Map (group_name, category_name) → {ranks_bought, dp_spent} for one level."""
    rows = conn.execute(
        "SELECT group_name, category_name, ranks_bought, dp_spent "
        "FROM character_category_purchase "
        "WHERE character_id = ? AND level = ?",
        (character_id, level),
    ).fetchall()
    return {
        (r["group_name"], r["category_name"]): {
            "ranks_bought": int(r["ranks_bought"]),
            "dp_spent": int(r["dp_spent"]),
        }
        for r in rows
    }


def skill_purchase_state(
    conn: sqlite3.Connection,
    character_id: int,
    level: int = 1,
) -> dict[tuple[str, str, str], dict]:
    """Map (group, category, skill) → purchase state."""
    rows = conn.execute(
        "SELECT group_name, category_name, skill_name, ranks_bought, dp_spent "
        "FROM character_skill_purchase "
        "WHERE character_id = ? AND level = ?",
        (character_id, level),
    ).fetchall()
    return {
        (r["group_name"], r["category_name"], r["skill_name"]): {
            "ranks_bought": int(r["ranks_bought"]),
            "dp_spent": int(r["dp_spent"]),
        }
        for r in rows
    }


def total_dp_spent(conn: sqlite3.Connection, character_id: int, level: int = 1) -> int:
    """Sum DP spent across categories, skills, AND training-package purchases."""
    cat = conn.execute(
        "SELECT COALESCE(SUM(dp_spent), 0) FROM character_category_purchase "
        "WHERE character_id = ? AND level = ?",
        (character_id, level),
    ).fetchone()[0]
    skill = conn.execute(
        "SELECT COALESCE(SUM(dp_spent), 0) FROM character_skill_purchase "
        "WHERE character_id = ? AND level = ?",
        (character_id, level),
    ).fetchone()[0]
    # TP purchases aren't per-level today; charge them against level 1
    # so chargen-time TP buys count against the level-1 budget.
    tp = 0
    if level == 1:
        tp = conn.execute(
            "SELECT COALESCE(SUM(dp_paid), 0) FROM character_training_package "
            "WHERE character_id = ?",
            (character_id,),
        ).fetchone()[0]
    return int(cat) + int(skill) + int(tp)


# ---------------------------------------------------------------------------
# Profession cost / bonus lookups
# ---------------------------------------------------------------------------

def profession_category_costs(
    conn: sqlite3.Connection, profession_id: int,
) -> dict[tuple[str, str], str]:
    """{(group_name, category_name): cost_string}."""
    rows = conn.execute(
        "SELECT group_name, category_name, cost "
        "FROM profession_category_cost WHERE profession_id = ?",
        (profession_id,),
    ).fetchall()
    return {(r["group_name"], r["category_name"]): r["cost"] for r in rows}


def profession_category_bonuses(
    conn: sqlite3.Connection, profession_id: int,
) -> dict[tuple[str, str], int]:
    """{(group_name, category_name): bonus} — flat per-category profession bonus."""
    rows = conn.execute(
        "SELECT group_name, category_name, bonus "
        "FROM profession_category_bonus WHERE profession_id = ?",
        (profession_id,),
    ).fetchall()
    return {(r["group_name"], r["category_name"]): int(r["bonus"]) for r in rows}


def profession_group_bonuses(
    conn: sqlite3.Connection, profession_id: int,
) -> dict[str, int]:
    """{group_name: bonus} — flat per-group profession bonus."""
    rows = conn.execute(
        "SELECT group_name, bonus FROM profession_group_bonus "
        "WHERE profession_id = ?",
        (profession_id,),
    ).fetchall()
    return {r["group_name"]: int(r["bonus"]) for r in rows}


# ---------------------------------------------------------------------------
# Total-bonus assembly
# ---------------------------------------------------------------------------

def category_total_bonus(
    *,
    category_ranks: int,
    category_progression: str,
    stat_bonuses: str,
    raw_temps: dict[StatCode, int],
    profession_category_bonus: int = 0,
    profession_group_bonus: int = 0,
) -> int:
    """Compose the category total bonus from its parts (rounded to int)."""
    rank_b = progression_bonus(category_progression, standard_category_bonus,
                                category_ranks)
    stat_b = stat_bonus_for(stat_bonuses, raw_temps)
    total = rank_b + stat_b + profession_category_bonus + profession_group_bonus
    return int(round(total))


def skill_total_bonus(
    *,
    skill_ranks: int,
    skill_progression: str,        # almost always "Standard"
    skill_stat: str | None,        # one stat code like "St" or "St/Ag/St"
    category_total_bonus: int,     # the category's total — flows through
    raw_temps: dict[StatCode, int],
) -> int:
    """Compose the per-skill total bonus.

    skill_total = skill_rank_bonus + skill-specific stat_bonus
                  + category_total (which already includes category ranks +
                  category-stat bonus + profession bonuses).
    """
    rank_b = progression_bonus(skill_progression, standard_skill_bonus,
                                skill_ranks)
    # Skill-level stat bonus uses the skill's own `stat` field (single
    # code). The category-level stat bonus is rolled into category_total.
    stat_b = 0
    if skill_stat:
        for c in parse_stat_codes(skill_stat):
            if c in raw_temps:
                stat_b += basic_stat_bonus(int(raw_temps[c]))
    return int(round(rank_b + stat_b + category_total_bonus))
