"""Unit tests for the weapon → category classification layer in
core/chargen/weapons.py — the expanded map, label normalisation, and
the DB-backed weapons_in_category lookup."""

from __future__ import annotations

import sqlite3

import pytest

from core.chargen.weapons import (
    CAT_1H_CONC,
    CAT_1H_EDGED,
    CAT_2H,
    CAT_MISSILE,
    CAT_POLEARMS,
    CAT_THROWN,
    classify,
    normalize_category_label,
    weapons_in_category,
)


# ---------------------------------------------------------------------------
# classify — expanded map spot checks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("Short Sword", CAT_1H_EDGED),
    ("Long Sword", CAT_1H_EDGED),
    ("Bastard Sword", CAT_1H_EDGED),
    ("Katana", CAT_1H_EDGED),
    ("Dagger", CAT_1H_EDGED),
    ("Flail", CAT_1H_CONC),
    ("Nunchaku", CAT_1H_CONC),
    ("War Hammer", CAT_1H_CONC),
    ("Great Sword", CAT_2H),
    ("No Dachi", CAT_2H),
    ("Glaive", CAT_POLEARMS),
    ("Naginata", CAT_POLEARMS),
    ("Pike", CAT_POLEARMS),
    ("Hand Crossbow", CAT_MISSILE),
    ("Long Bow", CAT_MISSILE),
    ("Javelin", CAT_THROWN),
    ("Boomerang", CAT_THROWN),
])
def test_classify_known_weapons(name: str, expected: str) -> None:
    assert classify(name) == expected


def test_classify_case_and_plural_insensitive() -> None:
    assert classify("short swords") == CAT_1H_EDGED
    assert classify("DAGGER") == CAT_1H_EDGED


@pytest.mark.parametrize("name", [
    "Brawling", "Martial Arts Strikes", "Martial Arts Sweeps",
    "Ram, Butt, Bash, Knockdown",
])
def test_classify_non_weapons_return_none(name: str) -> None:
    """Pseudo-weapons (their own skill categories / creature attacks)
    must never classify into a weapon category."""
    assert classify(name) is None


# ---------------------------------------------------------------------------
# normalize_category_label
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,expected", [
    ("1-H Edged", CAT_1H_EDGED),
    ("Weapon • 1-H Edged", CAT_1H_EDGED),
    ("Weapon/1-H Edged", CAT_1H_EDGED),
    ("1-H Concussion", CAT_1H_CONC),    # profession-cost spelling
    ("1-H Conc.", CAT_1H_CONC),         # T-1.6 / weapons.py spelling
    ("2-Handed", CAT_2H),
    ("Missile", CAT_MISSILE),
    ("Pole Arms", CAT_POLEARMS),        # profession-cost spelling
    ("Pole-arms", CAT_POLEARMS),        # canonical spelling
    ("Thrown", CAT_THROWN),
    ("Weapon • 1-H Conc. skill category", CAT_1H_CONC),  # full T-1.6 row
])
def test_normalize_category_label(label: str, expected: str) -> None:
    assert normalize_category_label(label) == expected


@pytest.mark.parametrize("label", [
    "Missile Artillery",   # takes no hand weapons
    "Body Development",
    "Athletic • Brawn",
    "",
])
def test_normalize_category_label_non_weapon_returns_none(label: str) -> None:
    assert normalize_category_label(label) is None


# ---------------------------------------------------------------------------
# weapons_in_category (DB-backed)
# ---------------------------------------------------------------------------

def _weapon_db(names: list[str]) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE weapon (weapon_id INTEGER PRIMARY KEY, name TEXT)")
    conn.executemany("INSERT INTO weapon (name) VALUES (?)", [(n,) for n in names])
    conn.commit()
    return conn


def test_weapons_in_category_filters_and_sorts() -> None:
    conn = _weapon_db([
        "Short Sword", "Broadsword", "Dagger",     # 1-H Edged
        "War Hammer", "Mace",                       # 1-H Conc
        "Long Bow",                                 # Missile
        "Brawling",                                 # non-weapon
    ])
    edged = weapons_in_category(conn, "1-H Edged")
    assert edged == ["Broadsword", "Dagger", "Short Sword"]   # sorted
    # Other spellings resolve the same.
    assert weapons_in_category(conn, "Weapon • 1-H Edged") == edged
    assert weapons_in_category(conn, "1-H Concussion") == ["Mace", "War Hammer"]


def test_weapons_in_category_non_weapon_label_empty() -> None:
    conn = _weapon_db(["Short Sword", "Long Bow"])
    assert weapons_in_category(conn, "Missile Artillery") == []
    assert weapons_in_category(conn, "Body Development") == []


def test_weapons_in_category_excludes_unclassified() -> None:
    """A weapon the map doesn't know about doesn't show up in any
    category — the SPA's free-text entry is the escape hatch."""
    conn = _weapon_db(["Short Sword", "Rope Dart", "Tiger Claw"])
    assert weapons_in_category(conn, "1-H Edged") == ["Short Sword"]
    # Rope Dart / Tiger Claw classify to None → absent everywhere.
    for cat in ("1-H Conc.", "Thrown", "Missile"):
        assert "Rope Dart" not in weapons_in_category(conn, cat)
        assert "Tiger Claw" not in weapons_in_category(conn, cat)
