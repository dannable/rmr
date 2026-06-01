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
    "bastard axe":       CAT_1H_EDGED,
    "bastard sword":     CAT_1H_EDGED,   # 1-H by default in RM; usable 2-H
    "beaked axe":        CAT_1H_EDGED,
    "broadsword":        CAT_1H_EDGED,
    "cutlass":           CAT_1H_EDGED,
    "dagger":            CAT_1H_EDGED,
    "falchion":          CAT_1H_EDGED,
    "foil":              CAT_1H_EDGED,
    "handaxe":           CAT_1H_EDGED,
    "hand axe":          CAT_1H_EDGED,
    "jambiya":           CAT_1H_EDGED,
    "katana":            CAT_1H_EDGED,
    "khukuri":           CAT_1H_EDGED,
    "knife":             CAT_1H_EDGED,
    "long scimitar":     CAT_1H_EDGED,
    "long sword":        CAT_1H_EDGED,
    "longsword":         CAT_1H_EDGED,
    "main gauche":       CAT_1H_EDGED,
    "ninjato":           CAT_1H_EDGED,
    "rapier":            CAT_1H_EDGED,
    "scimitar":          CAT_1H_EDGED,
    "short sword":       CAT_1H_EDGED,
    "sword":             CAT_1H_EDGED,    # generic, mostly for outfittings that just say "sword"
    "tiger hook":        CAT_1H_EDGED,
    "wakazashi":         CAT_1H_EDGED,
    "war fan":           CAT_1H_EDGED,    # tessen — bladed war fan
    # 1-H Concussion
    "aklys":             CAT_1H_CONC,
    "cat o nine tails":  CAT_1H_CONC,
    "club":              CAT_1H_CONC,
    "comet hammer":      CAT_1H_CONC,
    "cudgel":            CAT_1H_CONC,
    "flail":             CAT_1H_CONC,
    "jitte":             CAT_1H_CONC,
    "mace":              CAT_1H_CONC,
    "morning star":      CAT_1H_CONC,
    "mullet":            CAT_1H_CONC,     # maul-type concussion weapon
    "nunchaku":          CAT_1H_CONC,
    "sai":               CAT_1H_CONC,
    "steel whip":        CAT_1H_CONC,
    "war hammer":        CAT_1H_CONC,
    "warhammer":         CAT_1H_CONC,
    "whip":              CAT_1H_CONC,
    # 2-Handed
    "great-sword":       CAT_2H,
    "great sword":       CAT_2H,
    "greatsword":        CAT_2H,
    "halberd":           CAT_2H,
    "nagamaki":          CAT_2H,
    "no dachi":          CAT_2H,
    "quarterstaff":      CAT_2H,
    "staff":             CAT_2H,
    "three section staff": CAT_2H,
    "two-handed sword":  CAT_2H,
    "two handed sword":  CAT_2H,
    "war mattock":       CAT_2H,
    # Missile
    "atlatl":            CAT_MISSILE,
    "blowgun":           CAT_MISSILE,
    "blowpipe":          CAT_MISSILE,
    "composite bow":     CAT_MISSILE,
    "crossbow":          CAT_MISSILE,
    "hand crossbow":     CAT_MISSILE,
    "heavy crossbow":    CAT_MISSILE,
    "light crossbow":    CAT_MISSILE,
    "long bow":          CAT_MISSILE,
    "longbow":           CAT_MISSILE,
    "poisoned arrows":   CAT_MISSILE,
    "short bow":         CAT_MISSILE,
    "shortbow":          CAT_MISSILE,
    "sling":             CAT_MISSILE,
    "staff sling":       CAT_MISSILE,
    # Pole-arms
    "bardiche":          CAT_POLEARMS,
    "bec de corbin":     CAT_POLEARMS,
    "fauchard":          CAT_POLEARMS,
    "glaive":            CAT_POLEARMS,
    "guisarme":          CAT_POLEARMS,
    "heavy spear":       CAT_POLEARMS,
    "lance":             CAT_POLEARMS,
    "lucerne hammer":    CAT_POLEARMS,
    "man catcher":       CAT_POLEARMS,
    "military fork":     CAT_POLEARMS,
    "naginata":          CAT_POLEARMS,
    "partisan":          CAT_POLEARMS,
    "pike":              CAT_POLEARMS,
    "pole axe":          CAT_POLEARMS,
    "pole-axe":          CAT_POLEARMS,
    "poleaxe":           CAT_POLEARMS,
    "polearm":           CAT_POLEARMS,
    "pole arm":          CAT_POLEARMS,
    "pole-arm":          CAT_POLEARMS,
    "ranseur":           CAT_POLEARMS,
    "spear":             CAT_POLEARMS,
    "trident":           CAT_POLEARMS,
    # Thrown
    "bola":              CAT_THROWN,
    "boomerang":         CAT_THROWN,
    "dart":              CAT_THROWN,
    "gladiators net":    CAT_THROWN,
    "harpoon":           CAT_THROWN,
    "javelin":           CAT_THROWN,
    "lasso":             CAT_THROWN,
    "shuriken":          CAT_THROWN,
    "throwing axe":      CAT_THROWN,
    "throwing dagger":   CAT_THROWN,
    "throwing knife":    CAT_THROWN,
}

# Some catalog entries are NOT physical weapons — they are their own
# skill categories (Brawling, Martial Arts forms) or creature attacks.
# They live in the `weapon` table because they share the attack-table
# machinery, but they must never appear in a weapon-category dropdown.
# Left out of _WEAPON_CATEGORY on purpose; classify() returns None and
# weapons_in_category() filters them out. A handful of genuinely
# exotic / ambiguous weapons (e.g. rope dart, kyotetsu-shoge, tiger
# claw) are also intentionally unmapped — the SPA's free-text "Other
# weapon…" entry covers those.


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


# Map the many spellings of a weapon skill-category label onto our six
# canonical categories. The allocator / profession cost tables use forms
# like "1-H Concussion" and "Pole Arms" while the T-1.6 rows + this
# module use "1-H Conc." and "Pole-arms"; normalise them all here.
# "Missile Artillery" (ballistae, catapults) is a distinct skill
# category that takes no hand weapons, so it maps to None — its dropdown
# stays empty rather than offering bows.
_CATEGORY_LABEL_TO_CANONICAL: dict[str, str] = {
    "1-h conc.":          CAT_1H_CONC,
    "1-h conc":           CAT_1H_CONC,
    "1-h concussion":     CAT_1H_CONC,
    "1-h edged":          CAT_1H_EDGED,
    "2-handed":           CAT_2H,
    "two-handed":         CAT_2H,
    "missile":            CAT_MISSILE,
    "pole-arms":          CAT_POLEARMS,
    "pole arms":          CAT_POLEARMS,
    "polearms":           CAT_POLEARMS,
    "pole-arm":           CAT_POLEARMS,
    "thrown":             CAT_THROWN,
}


def normalize_category_label(label: str) -> str | None:
    """Resolve a weapon skill-category label to its canonical form.

    Accepts the short category ("1-H Edged"), the profession-cost
    spelling ("1-H Concussion", "Pole Arms"), or a full "Weapon • <cat>"
    skill-category name. Returns the canonical category constant, or None
    when the label isn't a recognised single-weapon category (e.g.
    "Missile Artillery", or a non-weapon group)."""
    if not label:
        return None
    s = label.strip()
    # Strip a leading group prefix ("Weapon • " / "Weapon · " / "Weapon/").
    for sep in (" • ", " · ", "/"):
        pre = "Weapon" + sep
        if s.startswith(pre):
            s = s[len(pre):].strip()
            break
    # Drop a trailing " skill category" suffix used by the T-1.6 rows.
    low = s.lower()
    if low.endswith(" skill category"):
        low = low[: -len(" skill category")].strip()
    return _CATEGORY_LABEL_TO_CANONICAL.get(low)


def weapons_in_category(conn, category_label: str) -> list[str]:
    """All weapon names in the DB that belong to `category_label`.

    `category_label` may be any spelling normalize_category_label
    accepts. Returns the weapon `name`s (catalog casing) whose
    classify() lands in that category, sorted alphabetically and
    de-duplicated. Empty when the label isn't a single-weapon category
    or nothing matches.

    `conn` is a sqlite3 connection; we read the `weapon` table directly
    rather than depending on core.attack to keep this module standalone.
    """
    canonical = normalize_category_label(category_label)
    if canonical is None:
        return []
    rows = conn.execute("SELECT name FROM weapon ORDER BY name").fetchall()
    names = [r[0] for r in rows]
    out: list[str] = []
    seen: set[str] = set()
    for n in names:
        if classify(n) == canonical and n not in seen:
            out.append(n)
            seen.add(n)
    return out


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
