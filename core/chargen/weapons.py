"""Classify weapons into RMSS skill categories (T-1.6 weapon-category rows).

When the adolescence panel asks the player to pick "1 Weapon Based on
Culture/Race ‡" inside a specific weapon category (e.g. 1-H Edged), the
dropdown options are the race's culture_data.weapons entries filtered by
that category. This module owns the weapon → category mapping.

RMSS weapon categories (T-1.6 row labels use the short forms):
  * 1-H Conc.   — clubs, maces, hammers (concussive 1-handed)
  * 1-H Edged   — daggers, swords, axes (edged 1-handed)
  * 2-Handed    — two-handed swords, war mattocks, halberds
  * Missile     — bows, crossbows, slings, thrown projectiles
  * Pole-arms   — spears, polearms, lances
  * Thrown      — javelins, throwing knives, harpoons, etc.

A given physical weapon can sometimes fit multiple categories (e.g.
javelin can be Thrown or Pole-arms depending on house rules). We pick
the single most common RMSS classification per weapon; ambiguous cases
fall through to None and the SPA shows an empty dropdown the user has
to fill manually.
"""

from __future__ import annotations

import re

# Canonical category labels — match exactly what the T-1.6 row prefix uses.
CAT_1H_CONC   = "1-H Conc."
CAT_1H_EDGED  = "1-H Edged"
CAT_2H        = "2-Handed"
CAT_MISSILE   = "Missile"
CAT_POLEARMS  = "Pole-arms"
CAT_THROWN    = "Thrown"

# Weapon name (lowercase) → category. Names are matched after normalising
# whitespace and dropping plural/punctuation. Keep this map roughly
# alphabetical per category for readability.
_WEAPON_CATEGORY: dict[str, str] = {
    # 1-H Edged
    "battle-axe":        CAT_1H_EDGED,
    "battle axe":        CAT_1H_EDGED,
    "broadsword":        CAT_1H_EDGED,
    "dagger":            CAT_1H_EDGED,
    "falchion":          CAT_1H_EDGED,
    "handaxe":           CAT_1H_EDGED,
    "hand axe":          CAT_1H_EDGED,
    "jambiya":           CAT_1H_EDGED,
    "khukuri":           CAT_1H_EDGED,
    "main gauche":       CAT_1H_EDGED,
    "rapier":            CAT_1H_EDGED,
    "scimitar":          CAT_1H_EDGED,
    "short sword":       CAT_1H_EDGED,
    "sword":             CAT_1H_EDGED,    # generic, mostly for outfittings that just say "sword"
    # 1-H Concussion
    "club":              CAT_1H_CONC,
    "cudgel":            CAT_1H_CONC,
    "mace":              CAT_1H_CONC,
    "morning star":      CAT_1H_CONC,
    "war hammer":        CAT_1H_CONC,
    "warhammer":         CAT_1H_CONC,
    "whip":              CAT_1H_CONC,
    # 2-Handed
    "great-sword":       CAT_2H,
    "greatsword":        CAT_2H,
    "halberd":           CAT_2H,
    "quarterstaff":      CAT_2H,
    "staff":             CAT_2H,
    "two-handed sword":  CAT_2H,
    "two handed sword":  CAT_2H,
    "war mattock":       CAT_2H,
    # Missile
    "blowgun":           CAT_MISSILE,
    "composite bow":     CAT_MISSILE,
    "crossbow":          CAT_MISSILE,
    "heavy crossbow":    CAT_MISSILE,
    "light crossbow":    CAT_MISSILE,
    "long bow":          CAT_MISSILE,
    "longbow":           CAT_MISSILE,
    "poisoned arrows":   CAT_MISSILE,
    "short bow":         CAT_MISSILE,
    "shortbow":          CAT_MISSILE,
    "sling":             CAT_MISSILE,
    # Pole-arms
    "lance":             CAT_POLEARMS,
    "polearm":           CAT_POLEARMS,
    "pole arm":          CAT_POLEARMS,
    "pole-arm":          CAT_POLEARMS,
    "spear":             CAT_POLEARMS,
    "trident":           CAT_POLEARMS,
    # Thrown
    "bola":              CAT_THROWN,
    "dart":              CAT_THROWN,
    "harpoon":           CAT_THROWN,
    "javelin":           CAT_THROWN,
    "shuriken":          CAT_THROWN,
    "throwing axe":      CAT_THROWN,
    "throwing dagger":   CAT_THROWN,
    "throwing knife":    CAT_THROWN,
}


# Map "T-1.6 row category prefix" → our canonical category. The loader
# prefixes "[<source row>] 1 Weapon Based on Culture/Race ‡" — the source
# row uses the longer form "Weapon • 1-H Conc. skill category".
T16_CATEGORY_TO_CANONICAL: dict[str, str] = {
    "Weapon • 1-H Conc. skill category":  CAT_1H_CONC,
    "Weapon • 1-H Edged skill category":  CAT_1H_EDGED,
    "Weapon • 2-Handed skill category":   CAT_2H,
    "Weapon • Missile skill category":    CAT_MISSILE,
    "Weapon • Pole-arms skill category":  CAT_POLEARMS,
    "Weapon • Thrown skill category":     CAT_THROWN,
}

# Regex extracting the bracketed category prefix the loader uses to
# disambiguate duplicate "1 Weapon Based..." rows.
_BRACKETED = re.compile(r"^\[([^\]]+)\]\s*(.+)$")


def category_for_t16_row(t16_row: str) -> str | None:
    """Given an adolescence_rank.skill label like
    '[Weapon • 1-H Edged skill category] 1 Weapon Based on Culture/Race ‡',
    return the canonical short-form category ('1-H Edged') or None."""
    m = _BRACKETED.match(t16_row)
    if not m:
        return None
    return T16_CATEGORY_TO_CANONICAL.get(m.group(1))


def classify(name: str) -> str | None:
    """Return the canonical category for a weapon name, or None if unknown.

    Matching is case-insensitive and tolerates trailing 's' (plural) and
    surrounding whitespace/punctuation. Unknown weapons fall back to None
    so the SPA can still surface them — they just won't pre-filter into
    a category.
    """
    if not name:
        return None
    key = name.strip().lower().rstrip(".")
    # Strip a trailing plural 's' if it makes the lookup succeed.
    if key in _WEAPON_CATEGORY:
        return _WEAPON_CATEGORY[key]
    if key.endswith("s") and key[:-1] in _WEAPON_CATEGORY:
        return _WEAPON_CATEGORY[key[:-1]]
    return None


def filter_race_weapons_by_category(weapons_text: str, category: str) -> list[str]:
    """Split a race's culture_data.weapons text into individual weapon
    names, filter to those in `category`, return the matches.

    `weapons_text` is the raw comma-separated text from culture_data
    (e.g. "Dagger, handaxe, short sword, club, war hammer, mace,
    crossbow, battle-axe, spear, poisoned arrows"). We split on commas
    and semicolons, trim, then classify each token.
    """
    if not weapons_text:
        return []
    tokens = [t.strip().rstrip(".").strip() for t in re.split(r"[,;]", weapons_text)]
    tokens = [t for t in tokens if t]
    return [t for t in tokens if classify(t) == category]


def all_race_weapons(weapons_text: str) -> list[str]:
    """Split a race's weapons text into individual weapon names, dropping
    empty fragments. Used when a category-specific filter returns no
    matches and we want to show every option as a fallback."""
    if not weapons_text:
        return []
    tokens = [t.strip().rstrip(".").strip() for t in re.split(r"[,;]", weapons_text)]
    return [t for t in tokens if t]
