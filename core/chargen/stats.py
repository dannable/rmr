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

# The five RMSS "Development stats" — Ag, Co, Me, Re, SD — whose temporary
# values feed the per-level Development Point budget. See RMSS Character
# Law p.13: "DPs = (Ag + Co + Me + Re + SD) ÷ 5, round normally."
DEV_STAT_CODES: tuple[StatCode, ...] = ("Ag", "Co", "Me", "Re", "SD")


def development_points(stats: Mapping[StatCode, int]) -> int:
    """Return per-level Development Points from the 5 development stats.

    RMSS rule (Character Law p.13): DPs = (Ag + Co + Me + Re + SD) ÷ 5,
    round normally (.5 rounds up). Missing dev stats default to 0 so
    partial blocks (e.g. during stat-buy planning) still give a usable
    preview rather than raising KeyError.
    """
    total = sum(int(stats.get(c, 0)) for c in DEV_STAT_CODES)
    # Integer half-up division by 5: 70.4 → 70, 70.6 → 71, 70.5 → 71.
    return (total + 2) // 5


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


# RMSS T-1.3: Potential Stat Table. Each entry maps a temp-stat band to:
#   - `base`: the floor of the potential roll (the "20" in "20 + 8d10")
#   - `dice`: tuple of (count, sides) for the dice roll added on top
#   - `fixed_mod`: the Fixed Mod alternative (added to temp, no dice)
#
# Stats 92+ get individual rows. Per the table's footnote, the floor
# rule applies to ALL bands: the rolled potential is clamped up to the
# temp if the roll comes out below it.
_T_1_3_ROWS: tuple[tuple[range, int, tuple[int, int], int], ...] = (
    (range( 20,  25),  20, (8, 10), 44),
    (range( 25,  35),  30, (7, 10), 39),
    (range( 35,  45),  40, (6, 10), 33),
    (range( 45,  55),  50, (5, 10), 28),
    (range( 55,  65),  60, (4, 10), 22),
    (range( 65,  75),  70, (3, 10), 17),
    (range( 75,  85),  80, (2, 10), 11),
    (range( 85,  92),  90, (1, 10),  6),
    (range( 92,  93),  91, (1,  9),  5),
    (range( 93,  94),  92, (1,  8),  4),
    (range( 94,  95),  93, (1,  7),  4),
    (range( 95,  96),  94, (1,  6),  3),
    (range( 96,  97),  95, (1,  5),  3),
    (range( 97,  98),  96, (1,  4),  2),
    (range( 98,  99),  97, (1,  3),  2),
    (range( 99, 100),  98, (1,  2),  1),
    (range(100, 101),  99, (1,  2),  1),
)


def _t_1_3_row(temp: int) -> tuple[int, tuple[int, int], int]:
    """Look up (base, (dice_count, dice_sides), fixed_mod) for `temp`."""
    for band, base, dice, fixed in _T_1_3_ROWS:
        if temp in band:
            return base, dice, fixed
    # Out of the printed range. Below 20 → use the 20-24 row; above 100 →
    # potential just equals temp (no roll, no fixed mod above 100).
    if temp < 20:
        return _T_1_3_ROWS[0][1:]
    return temp, (0, 0), 0


def random_potential(temp: int, rng=None) -> int:
    """Roll a potential stat per RMSS T-1.3.

    `rng` may be any object with `randint(a, b)` (Python `random.Random`
    or its `SystemRandom` subclass). Tests pass a seeded Random for
    determinism; production passes `random.SystemRandom()` so the result
    can't be reverse-engineered from the previous roll.

    Per the table's footnote, the rolled potential is clamped up to
    `temp` — a roll that would put potential below the current temp
    falls back to potential = temp.
    """
    import random
    if rng is None:
        rng = random.SystemRandom()
    base, (count, sides), _fixed = _t_1_3_row(int(temp))
    roll_total = sum(rng.randint(1, sides) for _ in range(count)) if count else 0
    return max(int(temp), base + roll_total)


def fixed_potential(temp: int) -> int:
    """Apply RMSS T-1.3 Fixed Mod alternative to `temp`.

    Per the table's "†" footnote, this is the no-dice option — every
    stat gets a fixed bump based on its band. Returns max(temp, …)
    just like the dice path, though for the printed Fixed Mod values
    the sum is always ≥ temp (e.g. temp 50 + 28 = 78, temp 91 + 6 = 97).
    """
    _base, _dice, fixed = _t_1_3_row(int(temp))
    return max(int(temp), int(temp) + fixed)


# RMSS T-2.1 bonus tier thresholds. Each value is the LOW edge of a band
# where the printed bonus increases. Used by the "+1 tier" button to
# bump a stat to its next bonus rung.
STAT_BONUS_TIERS: tuple[int, ...] = (
    1, 2, 4, 6, 8, 10, 11, 16, 21, 26, 31,
    70, 75, 80, 85, 90, 91, 92, 94, 96, 98, 100, 101, 102,
)


def next_bonus_tier(value: int) -> int | None:
    """Return the smallest tier threshold strictly greater than `value`,
    or None if `value` is already at the top tier (102+)."""
    for t in STAT_BONUS_TIERS:
        if t > int(value):
            return t
    return None


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


def rr_bonus(stat_bonuses: Mapping[StatCode, int], category: str) -> int:
    """Compute the base RR bonus for a category from a *stat-bonus* block.

    Per RMSS Character Law T-7.4, an RR is `multiplier × stat_bonus(es) +
    race_RR_mod + profession_RR_mod + …`. The caller passes in the
    final per-stat bonuses (T-2.1(temp) + race stat mod), not raw temp
    values, and this function applies the formula's multiplier.

    Note: this signature changed from the pre-2026 implementation, which
    multiplied raw temp values (e.g. Channeling RR = 3 × In_temp). That
    matched what some older RM editions printed but is inconsistent with
    RMSS T-1.1's "race mod is a bonus, not a stat adjustment" rule.
    """
    if category not in RR_FORMULAS:
        raise KeyError(f"Unknown RR category: {category}")
    mult, codes = RR_FORMULAS[category]
    return mult * sum(stat_bonuses[c] for c in codes)
