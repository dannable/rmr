"""Unit tests for the flexible-slot pick classification in
core/chargen/training_package.py — the logic that decides whether a TP's
flexible rank assignment is a single-pick choice (resolvable in the
selection modal) or a multi-distribution slot (manual Step-6 setup)."""

from __future__ import annotations

from core.chargen.training_package import (
    skill_options_are_generic,
    slot_is_single_pick,
    slot_pick_counts,
)


def _counts(**kw) -> tuple[int, int]:
    base = dict(
        cat_ranks=0, skill_ranks=0, cat_spread_max=None,
        skill_spread_max=None, ranks_assigned_max=None, skill_option_names=[],
    )
    base.update(kw)
    return slot_pick_counts(**base)


def _single(**kw) -> bool:
    base = dict(
        cat_ranks=0, skill_ranks=0, cat_spread_max=None,
        skill_spread_max=None, ranks_assigned_max=None, skill_option_names=[],
    )
    base.update(kw)
    return slot_is_single_pick(**base)


# ---------------------------------------------------------------------------
# skill_options_are_generic
# ---------------------------------------------------------------------------

def test_generic_when_all_identical() -> None:
    assert skill_options_are_generic(["Languages", "Languages"]) is True
    assert skill_options_are_generic(["Languages"] * 5) is True


def test_not_generic_when_distinct() -> None:
    assert skill_options_are_generic(["Philosophy", "Religion"]) is False
    assert skill_options_are_generic(["Animal Training", "Animal Mastery"]) is False


def test_not_generic_when_short() -> None:
    assert skill_options_are_generic([]) is False
    assert skill_options_are_generic(["Languages"]) is False


# ---------------------------------------------------------------------------
# slot_pick_counts / slot_is_single_pick — the real TP shapes
# ---------------------------------------------------------------------------

def test_weapon_attack_is_single_pick() -> None:
    # "Weapon/Attack": cat 1 + skill 1, no spread → one category, one weapon.
    assert _counts(cat_ranks=1, skill_ranks=1) == (1, 1)
    assert _single(cat_ranks=1, skill_ranks=1) is True


def test_gm_assigned_weapon_spread_one_is_single() -> None:
    # City Guard "Weapon (GM assigned)": cat 2 + skill 2, spreads = 1 each
    # → still a single category + single weapon (all ranks to one).
    assert _single(cat_ranks=2, skill_ranks=2,
                   cat_spread_max=1, skill_spread_max=1) is True


def test_berserker_category_spread_two_is_multi() -> None:
    # "Assign 3 ranks to weapon category #1, 1 to #2": cat_spread_max=2.
    assert _counts(cat_ranks=4, cat_spread_max=2, ranks_assigned_max=3) == (2, 0)
    assert _single(cat_ranks=4, cat_spread_max=2, ranks_assigned_max=3) is False


def test_gladiator_ranks_assigned_max_forces_multi() -> None:
    # "Assign 1 rank to 4 different weapon categories": ram=1, cat 4 → 4 picks.
    assert _counts(cat_ranks=4, ranks_assigned_max=1) == (4, 0)
    assert _single(cat_ranks=4, ranks_assigned_max=1) is False


def test_written_languages_spread_one_is_single() -> None:
    # Cloistered Academic WRITTEN languages: skill 3, ssm=1, dup generics
    # → one written language gets all 3 ranks.
    assert _counts(cat_ranks=3, skill_ranks=3, skill_spread_max=1,
                   skill_option_names=["Languages", "Languages"]) == (1, 1)
    assert _single(cat_ranks=3, skill_ranks=3, skill_spread_max=1,
                   skill_option_names=["Languages", "Languages"]) is True


def test_spoken_languages_generic_duplicates_is_multi() -> None:
    # Crusading Academic SPOKEN: skill 5, no spread, 5 duplicate 'Languages'
    # → 5 distinct languages.
    assert _counts(cat_ranks=5, skill_ranks=5,
                   skill_option_names=["Languages"] * 5) == (1, 5)
    assert _single(cat_ranks=5, skill_ranks=5,
                   skill_option_names=["Languages"] * 5) is False


def test_distinct_named_options_single_pick() -> None:
    # Beastmaster "Animal Training and/or Mastery": cat 1 + skill 2, distinct
    # options → pick one of the two skills.
    assert _counts(cat_ranks=1, skill_ranks=2,
                   skill_option_names=["Animal Training", "Animal Mastery"]) == (1, 1)
    assert _single(cat_ranks=1, skill_ranks=2,
                   skill_option_names=["Animal Training", "Animal Mastery"]) is True


def test_athletic_skill_spread_four_is_multi() -> None:
    # Athlete: skill 8, ssm=4 → 4 distinct athletic skills.
    assert _counts(skill_ranks=8, skill_spread_max=4, ranks_assigned_max=2) == (0, 4)
    assert _single(skill_ranks=8, skill_spread_max=4, ranks_assigned_max=2) is False


def test_zero_ranks_dimensions() -> None:
    # Category-only slot: skill picks 0; skill-only slot: cat picks 0.
    assert _counts(cat_ranks=4, ranks_assigned_max=1) == (4, 0)
    assert _counts(skill_ranks=2, skill_option_names=["Spell Mastery"] * 2) == (0, 2)
