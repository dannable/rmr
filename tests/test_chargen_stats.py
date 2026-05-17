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


def test_rr_bonus_channeling_uses_3xIn() -> None:
    stats = {c: 50 for c in STAT_CODES}
    stats["In"] = 90
    assert rr_bonus(stats, "Channeling") == 270


def test_rr_bonus_arcane_sums_em_in_pr() -> None:
    stats = {c: 0 for c in STAT_CODES}
    stats["Em"] = 80
    stats["In"] = 90
    stats["Pr"] = 70
    assert rr_bonus(stats, "Arcane") == 240


def test_rr_bonus_chan_ess_sums_in_em() -> None:
    stats = {c: 0 for c in STAT_CODES}
    stats["In"] = 50
    stats["Em"] = 40
    assert rr_bonus(stats, "Chan/Ess") == 90


def test_rr_bonus_unknown_category_raises() -> None:
    with pytest.raises(KeyError):
        rr_bonus({c: 50 for c in STAT_CODES}, "Bogus")
