"""Tests for core.chargen.stats — Basic Stat Bonus Table T-2.1 + RR formulas."""

from __future__ import annotations

import pytest

from core.chargen.stats import (
    STAT_CODES,
    basic_stat_bonus,
    rr_bonus,
    stat_bonuses,
)


# Spot-check every printed band of T-2.1 (RMSS Character Law p. 54).
@pytest.mark.parametrize(
    "stat,bonus",
    [
        (1,   -10),
        (2,    -9), (3,    -9),
        (4,    -8), (5,    -8),
        (6,    -7), (7,    -7),
        (8,    -6), (9,    -6),
        (10,   -5),
        (11,   -4), (15,   -4),
        (16,   -3), (20,   -3),
        (21,   -2), (25,   -2),
        (26,   -1), (30,   -1),
        (31,    0), (69,    0),
        (70,    1), (74,    1),
        (75,    2), (79,    2),
        (80,    3), (84,    3),
        (85,    4), (89,    4),
        (90,    5), (91,    5),
        (92,    6), (93,    6),
        (94,    7), (95,    7),
        (96,    8), (97,    8),
        (98,    9), (99,    9),
        (100,  10),
        (101,  12),
        # 102+ uses (stat-95)*2 per the table footnote.
        (102,  14), (103,  16), (110,  30),
    ],
)
def test_basic_stat_bonus(stat: int, bonus: int) -> None:
    assert basic_stat_bonus(stat) == bonus


def test_out_of_range() -> None:
    with pytest.raises(ValueError):
        basic_stat_bonus(0)


def test_stat_bonuses_applies_to_all() -> None:
    block = {c: 70 for c in STAT_CODES}
    out = stat_bonuses(block)
    assert set(out.keys()) == set(STAT_CODES)
    assert all(v == 1 for v in out.values())  # 70 → +1


def test_stat_bonuses_skips_missing() -> None:
    out = stat_bonuses({"Ag": 95, "St": 50})
    assert out == {"Ag": 7, "St": 0}


def test_rr_bonus_channeling_uses_3x_In_bonus() -> None:
    # Callers now pass stat *bonuses* (T-2.1 + race mod), not raw temps.
    # Channeling = 3 × In_bonus.
    bonuses = {c: 0 for c in STAT_CODES}
    bonuses["In"] = 5             # ≈ T-2.1(90) = 5
    assert rr_bonus(bonuses, "Channeling") == 15


def test_rr_bonus_arcane_sums_Em_In_Pr_bonuses() -> None:
    bonuses = {c: 0 for c in STAT_CODES}
    bonuses["Em"] = 3
    bonuses["In"] = 5
    bonuses["Pr"] = 1
    # Arcane uses multiplier 1, summing Em + In + Pr bonuses.
    assert rr_bonus(bonuses, "Arcane") == 9


def test_rr_bonus_chan_ess_sums_In_Em_bonuses() -> None:
    bonuses = {c: 0 for c in STAT_CODES}
    bonuses["In"] = 5
    bonuses["Em"] = 4
    # Chan/Ess uses multiplier 1, summing In + Em bonuses.
    assert rr_bonus(bonuses, "Chan/Ess") == 9


def test_rr_bonus_unknown_category_raises() -> None:
    with pytest.raises(KeyError):
        rr_bonus({c: 0 for c in STAT_CODES}, "Bogus")


# ---------------------------------------------------------------------------
# T-1.2 stat-buy cost (used by the Step 3a budget banner)
# ---------------------------------------------------------------------------

def test_stat_cost_face_value_under_91() -> None:
    from core.chargen.stats import stat_cost
    assert stat_cost(1)  == 1
    assert stat_cost(50) == 50
    assert stat_cost(90) == 90


def test_stat_cost_ramps_91_to_100() -> None:
    from core.chargen.stats import stat_cost
    # Each step from 91→100 costs strictly more than the previous.
    assert stat_cost(91)  == 92
    assert stat_cost(95)  == 104
    assert stat_cost(100) == 130
    for v in range(91, 100):
        assert stat_cost(v + 1) > stat_cost(v)


def test_stat_cost_extrapolates_past_100() -> None:
    from core.chargen.stats import stat_cost
    assert stat_cost(101) == 138
    assert stat_cost(102) == 146


def test_stat_cost_clamps_zero_and_negative() -> None:
    from core.chargen.stats import stat_cost
    assert stat_cost(0)   == 0
    assert stat_cost(-5)  == 0


def test_total_stat_cost_matches_660_budget_at_66_each() -> None:
    """10 stats × 66 pts = 660; the canonical RMSS budget."""
    from core.chargen.stats import total_stat_cost, TEMP_STAT_BUDGET
    assert total_stat_cost({c: 66 for c in STAT_CODES}) == 660
    assert TEMP_STAT_BUDGET == 660


# ---------------------------------------------------------------------------
# T-1.3 random + fixed potential
# ---------------------------------------------------------------------------

class _MinRNG:
    """Always rolls the minimum (1) on every die. Useful for testing the
    "potential ≥ temp" floor — many T-1.3 bands roll below temp at min."""
    def randint(self, a: int, b: int) -> int:
        return a


class _MaxRNG:
    """Always rolls the max."""
    def randint(self, a: int, b: int) -> int:
        return b


def test_random_potential_floor_clamps_to_temp() -> None:
    """A min-roll of 70 + 3*1 = 73 < 74, so a temp of 74 stays at 74."""
    from core.chargen.stats import random_potential
    assert random_potential(74, _MinRNG()) == 74


def test_random_potential_max_roll() -> None:
    """Temp 50, max roll 50 + 5×10 = 100."""
    from core.chargen.stats import random_potential
    assert random_potential(50, _MaxRNG()) == 100


def test_random_potential_single_die_bands() -> None:
    """Temps 92-100 each use their own row with a small die."""
    from core.chargen.stats import random_potential
    # Temp 92 → base 91 + 1d9. Min 1 → 92 (== temp, floor kicks in).
    assert random_potential(92, _MinRNG()) == 92
    assert random_potential(92, _MaxRNG()) == 100   # 91 + 9
    # Temp 100 → base 99 + 1d2. Min 1 → 100, max 2 → 101.
    assert random_potential(100, _MinRNG()) == 100
    assert random_potential(100, _MaxRNG()) == 101


def test_random_potential_past_100_no_roll() -> None:
    """Stats past 100 have no T-1.3 row; potential = temp."""
    from core.chargen.stats import random_potential
    assert random_potential(101, _MaxRNG()) == 101
    assert random_potential(102, _MinRNG()) == 102


def test_fixed_potential_uses_table_modifier() -> None:
    """The Fixed Mod column adds a band-specific bump to temp."""
    from core.chargen.stats import fixed_potential
    assert fixed_potential(20) == 64   # 20 + 44
    assert fixed_potential(50) == 78   # 50 + 28
    assert fixed_potential(90) == 96   # 90 + 6
    assert fixed_potential(91) == 97   # 91 + 6 (still in 85-91 band)
    assert fixed_potential(92) == 97   # 92 + 5
    assert fixed_potential(100) == 101 # 100 + 1


# ---------------------------------------------------------------------------
# T-2.1 bonus-tier walker (used by the "+tier" button)
# ---------------------------------------------------------------------------

def test_next_bonus_tier_walks_through_table() -> None:
    from core.chargen.stats import next_bonus_tier
    # From 1 the next tier is 2 (where T-2.1 jumps from -10 to -9).
    assert next_bonus_tier(1) == 2
    # 50 is in the 31-69 band (+0); next tier is 70 (+1).
    assert next_bonus_tier(50) == 70
    # 90 is its own tier; next is 91.
    assert next_bonus_tier(90) == 91
    # 95 is in the 94-95 band; next is 96.
    assert next_bonus_tier(95) == 96
    # Already at the top.
    assert next_bonus_tier(102) is None
