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


# RMSS T-1.2: Temporary Stat Cost. Stats 1-90 cost their face value
# (one point per value). 91-100 use a ramping cost — the cumulative
# cost to BUY a stat of N points. Values past 100 (racial / magical
# inflation) extrapolate at +8 per point.
#
# Source: RMSS Character Law, Table T-1.2.
_T_1_2_RAMP: tuple[tuple[int, int], ...] = (
    (91,  92),
    (92,  94),
    (93,  97),
    (94, 100),
    (95, 104),
    (96, 108),
    (97, 113),
    (98, 118),
    (99, 124),
    (100, 130),
)


# Default stat-point budget for new RMSS characters (RMSS Character
# Law p.16: "660 points or 600+10d10 points"). 660 is the no-dice
# fixed allocation that the SPA uses as the planning target.
TEMP_STAT_BUDGET: int = 660

# Per RMSS, a character's two Prime stats (set by profession) must
# each be at least this value at character creation.
PRIME_STAT_MIN: int = 90


def stat_cost(value: int) -> int:
    """Return RMSS T-1.2 buy-cost for a temporary-stat value of `value`.

    Below 1 → 0 (clamp). 1..90 → face value (one point per). 91..100 →
    ramped via T-1.2. Past 100 → linear extrapolation at +8/pt off the
    100-point cost. Caller is responsible for any negative-buyback
    rules (RMSS allows reducing a stat below a starting floor; not
    modelled here)."""
    if value < 1:
        return 0
    if value <= 90:
        return value
    if value <= 100:
        for stat, cost in _T_1_2_RAMP:
            if stat == value:
                return cost
    # Past 100: extrapolate. The ramp's last delta is 130 → 100, +6.
    # Continue at +8/pt to stay strictly increasing without re-printing
    # a 101+ table (the rules don't really expect 100+ at creation but
    # racial bonuses can push there).
    return 130 + (value - 100) * 8


def total_stat_cost(stats: Mapping[StatCode, int]) -> int:
    """Sum stat_cost across every entry in `stats`."""
    return sum(stat_cost(int(v)) for v in stats.values())


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
