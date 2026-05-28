"""Tests pinning the rank → bonus math to RMSS T-2.2.

The five RMSS skill rank progressions:
  - Standard skill        (most common; +3/+2/+1/+0.5 in bands of 10)
  - Standard category     (+2/+1/+0.5 in bands of 10, CAPS at 35)
  - Combined skill (*)    (+5/+3/+1.5/+0.5; rank-0 penalty -30)
  - Limited skill (‡)     (+1 ramps, caps at 25)
  - Special skill (†)     (+6/+5/+4/+3 — bigger ramp)

Values are read directly off the printed T-2.2 column for each rank,
so a regression that changes the math will surface here loudly.
"""

from __future__ import annotations

import pytest

from core.chargen.skills import (
    standard_skill_bonus,
    standard_category_bonus,
    combined_skill_bonus,
    limited_skill_bonus,
    special_skill_bonus,
    progression_bonus,
)


# ---------------------------------------------------------------------------
# Standard skill rank bonus (the † column on T-2.2 is Special; Standard is
# the third column. Values: 0:-15, 1:3, 2:6, ..., 10:30, 20:50, 30:60, 31+: 60+0.5/rank)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ranks,expected", [
    (0,  -15),
    (1,    3),
    (5,   15),
    (10,  30),
    (11,  32),
    (15,  40),
    (20,  50),
    (25,  55),
    (30,  60),
    (31,  60.5),
    (40,  65),
    (50,  70),
])
def test_standard_skill_bonus_t22(ranks: int, expected: float) -> None:
    assert standard_skill_bonus(ranks) == expected


# ---------------------------------------------------------------------------
# Standard category rank bonus — column 2 on T-2.2.
# Caps at 35 past rank 30.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ranks,expected", [
    (0,  -15),
    (1,    2),
    (5,   10),
    (10,  20),
    (11,  21),
    (15,  25),
    (20,  30),
    (25,  32.5),    # midway through the 21-30 band at +0.5/rank
    (30,  35),
    (31,  35),       # caps — no further growth
    (45,  35),
    (100, 35),
])
def test_standard_category_bonus_t22(ranks: int, expected: float) -> None:
    assert standard_category_bonus(ranks) == expected


# ---------------------------------------------------------------------------
# Combined skill rank bonus — fourth T-2.2 column ("*").
# Heavier rank-0 penalty (-30) and faster early growth than Standard.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ranks,expected", [
    (0,  -30),
    (1,    5),
    (5,   25),
    (10,  50),
    (15,  65),
    (20,  80),
    (25,  87.5),    # midway through 21-30 at +1.5/rank: 80 + 5*1.5 = 87.5
    (30,  95),
    (31,  95.5),
    (40,  100),
])
def test_combined_skill_bonus_t22(ranks: int, expected: float) -> None:
    assert combined_skill_bonus(ranks) == expected


# ---------------------------------------------------------------------------
# Limited skill bonus — fifth column ("‡"). Caps at 25.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ranks,expected", [
    (0,    0),
    (5,    5),
    (10,  10),
    (20,  20),
    (25,  22.5),
    (30,  25),
    (31,  25),     # caps
    (60,  25),
])
def test_limited_skill_bonus_t22(ranks: int, expected: float) -> None:
    assert limited_skill_bonus(ranks) == expected


# ---------------------------------------------------------------------------
# Special skill bonus — sixth column ("†"). 60 / 110 / 150 anchors.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ranks,expected", [
    (0,     0),
    (1,     6),
    (5,    30),
    (10,   60),
    (15,   85),
    (20,  110),
    (25,  130),
    (30,  150),
    (31,  153),    # +3/rank past 30
    (40,  180),
])
def test_special_skill_bonus_t22(ranks: int, expected: float) -> None:
    assert special_skill_bonus(ranks) == expected


# ---------------------------------------------------------------------------
# progression_bonus dispatcher
# ---------------------------------------------------------------------------

def test_progression_bonus_named_dispatches_to_right_function() -> None:
    # "Standard" + skill context → standard_skill_bonus
    assert progression_bonus("Standard", standard_skill_bonus, 10) == 30
    # "Combined" + skill context → combined_skill_bonus
    assert progression_bonus("Combined", standard_skill_bonus, 10) == 50
    # "Limited" + skill context → limited_skill_bonus
    assert progression_bonus("Limited", standard_skill_bonus, 10) == 10
    # "Special" + skill context → special_skill_bonus
    assert progression_bonus("Special", standard_skill_bonus, 10) == 60
    # "Standard" + category context → standard_category_bonus
    assert progression_bonus(
        "Standard", standard_category_bonus, 10, is_category=True,
    ) == 20


def test_progression_bonus_combined_in_category_context_falls_back() -> None:
    """RMSS T-2.2 doesn't define a "Combined" category column — for a
    category caller, "Combined" should resolve to Standard Category, not
    Combined Skill (which would over-apply)."""
    assert progression_bonus(
        "Combined", standard_category_bonus, 10, is_category=True,
    ) == 20   # standard_category_bonus(10), NOT combined_skill_bonus(10)=50


def test_progression_bonus_empty_uses_default() -> None:
    # Empty string falls through to the caller's default function.
    assert progression_bonus("", standard_skill_bonus, 5) == 15        # standard_skill
    assert progression_bonus("", standard_category_bonus, 5,
                              is_category=True) == 10                    # standard_category


def test_progression_bonus_dotted_form() -> None:
    """Custom dotted progression (rare; e.g. Body Dev "0 • 0 • 0 • 0 • 0")."""
    # Body Dev: zero across the board → 0 regardless of ranks.
    assert progression_bonus("0 • 0 • 0 • 0 • 0", standard_category_bonus,
                              20, is_category=True) == 0.0
    # Race-hits-style "0 • 7 • 5 • 3 • 1": ranks 1-10 = 0, 11-20 = 7/rank, etc.
    # 15 ranks = 0*10 + 7*5 = 35.
    assert progression_bonus("0 • 7 • 5 • 3 • 1",
                              standard_skill_bonus, 15) == 35.0


# ---------------------------------------------------------------------------
# Sanity-check rank-0 penalties — these used to be 0 (wrong) before the
# T-2.2 alignment pass. Easy to miss in a future refactor.
# ---------------------------------------------------------------------------

def test_rank_zero_penalties_match_t22() -> None:
    assert standard_skill_bonus(0) == -15
    assert standard_category_bonus(0) == -15
    assert combined_skill_bonus(0) == -30
    assert limited_skill_bonus(0) == 0
    assert special_skill_bonus(0) == 0


def test_rank_thirty_one_caps_per_column() -> None:
    # Standard skill and Combined grow linearly past 30; Standard category
    # caps at 35; Limited caps at 25; Special grows +3/rank.
    assert standard_skill_bonus(31) == 60.5
    assert combined_skill_bonus(31) == 95.5
    assert standard_category_bonus(31) == 35    # CAP
    assert standard_category_bonus(50) == 35    # CAP
    assert limited_skill_bonus(31) == 25       # CAP
    assert limited_skill_bonus(50) == 25
    assert special_skill_bonus(31) == 153
