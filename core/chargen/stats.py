"""RMSS stats: bonuses, prime-stat handling, and Resistance Roll formulas.

Source: Rolemaster Character Generation (RMSS), §12.3 "Stat Bonuses" and
the Resistance Roll formulas printed on the Character Record Sheet (T-6.1).

The basic stat-bonus table (T-2.1) is the source of truth here. The PDF
also prints an "Optional Formula" column; the two don't agree exactly at
some bandary values (e.g. stat=100 → table says 10, formula gives 9.5), so
we encode the table verbatim and treat the formula as informational.
"""

from __future__ import annotations

from typing import Literal, Mapping

# The 10 RMSS stats, in the canonical order used on T-6.1.
StatCode = Literal["Ag", "Co", "Me", "Re", "SD", "Em", "In", "Pr", "Qu", "St"]

STAT_CODES: tuple[StatCode, ...] = (
    "Ag", "Co", "Me", "Re", "SD", "Em", "In", "Pr", "Qu", "St",
)

STAT_NAMES: dict[StatCode, str] = {
    "Ag": "Agility",
    "Co": "Constitution",
    "Me": "Memory",
    "Re": "Reasoning",
    "SD": "Self Discipline",
    "Em": "Empathy",
    "In": "Intuition",
    "Pr": "Presence",
    "Qu": "Quickness",
    "St": "Strength",
}


# Basic Stat Bonus Table T-2.1, RMSS Character Law p. 54.
# Each entry: (inclusive_low, inclusive_high, basic_bonus). The 102+ band has
# no upper bound and is handled separately below.
_BANDS: tuple[tuple[int, int, int], ...] = (
    (101, 101,  12),
    (100, 100,  10),
    ( 98,  99,   9),
    ( 96,  97,   8),
    ( 94,  95,   7),
    ( 92,  93,   6),
    ( 90,  91,   5),
    ( 85,  89,   4),
    ( 80,  84,   3),
    ( 75,  79,   2),
    ( 70,  74,   1),
    ( 31,  69,   0),
    ( 26,  30,  -1),
    ( 21,  25,  -2),
    ( 16,  20,  -3),
    ( 11,  15,  -4),
    ( 10,  10,  -5),
    (  8,   9,  -6),
    (  6,   7,  -7),
    (  4,   5,  -8),
    (  2,   3,  -9),
    (  1,   1, -10),
)


def basic_stat_bonus(stat: int) -> int:
    """Return the T-2.1 basic stat bonus for `stat` (any int 1..200+).

    Stats are in [1, 102]; the 102+ band scales linearly to handle racial
    or magical inflation past 102 (the printed formula (Stat-95)*2).
    """
    if stat >= 102:
        return (stat - 95) * 2
    for lo, hi, bonus in _BANDS:
        if lo <= stat <= hi:
            return bonus
    raise ValueError(f"stat out of range: {stat}")


def stat_bonuses(stats: Mapping[StatCode, int]) -> dict[StatCode, int]:
    """Convenience: apply basic_stat_bonus to every stat in a mapping."""
    return {code: basic_stat_bonus(stats[code]) for code in STAT_CODES if code in stats}


# Resistance Roll base formulas, RMSS Character Record Sheet T-6.1.
# The RR "base" is computed from temp stats; final RR also includes racial
# RR bonuses, items, and special abilities — those are layered on later.
Realm = Literal[
    "Channeling", "Essence", "Mentalism",
    "Chan/Ess", "Chan/Ment", "Ess/Ment", "Arcane",
]

RR_FORMULAS: dict[str, tuple[int, tuple[StatCode, ...]]] = {
    # name -> (multiplier, stats whose temps are summed and then multiplied)
    "Channeling":     (3, ("In",)),
    "Essence":        (3, ("Em",)),
    "Mentalism":      (3, ("Pr",)),
    "Chan/Ess":       (1, ("In", "Em")),
    "Chan/Ment":      (1, ("In", "Pr")),
    "Ess/Ment":       (1, ("Em", "Pr")),
    "Arcane":         (1, ("Em", "In", "Pr")),
    "Poison/Disease": (3, ("Co",)),
    "Fear":           (3, ("SD",)),
}


def rr_bonus(stats: Mapping[StatCode, int], category: str) -> int:
    """Compute the base RR bonus for a category from a stat block.

    The RMSS RR sheet adds the *temp stat* (not the bonus), then multiplies.
    For example, Channeling RR = 3 * In (temp).
    """
    if category not in RR_FORMULAS:
        raise KeyError(f"Unknown RR category: {category}")
    mult, codes = RR_FORMULAS[category]
    return mult * sum(stats[c] for c in codes)
