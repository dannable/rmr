"""Race lookups + race-mod application for the character builder.

The race table is loaded by load.py from data/chargen/races/<slug>.txt and
keyed by stable `slug`. Race-mod helpers in here fold a race's stat / RR
modifiers into a character's effective stats so the web API can hand the
SPA pre-computed numbers without each caller re-implementing T-1.1.

Source: RMSS Character Generation Race Abilities Table T-1.1.
"""

from __future__ import annotations

import sqlite3
from typing import Mapping

from .stats import STAT_CODES, StatCode

# Column lists for SELECTs — keeping these in one place so the API/tests
# all see the same shape and so adding a future race column is a one-spot edit.
_STAT_COLS: tuple[str, ...] = tuple(f"stat_{c.lower()}" for c in STAT_CODES)
_RR_COLS: tuple[str, ...] = (
    "rr_ess", "rr_chan", "rr_ment", "rr_pois", "rr_dis",
)
_PROG_COLS: tuple[str, ...] = (
    "body_dev_prog", "chan_pp_prog", "ess_pp_prog", "ment_pp_prog",
)
_RACE_COLS = ("race_id", "slug", "name") + _STAT_COLS + _RR_COLS \
    + ("bg_opts",) + _PROG_COLS + ("culture_data",)

_RACE_SELECT = "SELECT " + ", ".join(_RACE_COLS) + " FROM race"


# RMSS umbrella race categories — these don't have their own T-1.6 entries,
# stat mods, or culture_data. A character with one of these races picks a
# specific sub-culture (via character.culture_slug) to fill in those details.
UMBRELLA_RACE_SLUGS: frozenset[str] = frozenset({"common_men", "mixed_men"})

# Cultures available as sub-picks for the umbrella races. Both Common Men
# and Mixed Men can map onto any of the 7 specific Men cultures per
# RMSS Cultures & Races — we don't restrict Mixed Men any further since
# the source rules let the GM/player blend either parent culture.
UMBRELLA_CULTURE_SLUGS: tuple[str, ...] = (
    "hillmen", "mariners", "nomads", "ruralmen", "urbanmen", "woodmen",
    "high_men",
)


def is_umbrella_race(race: dict | None) -> bool:
    """True when the race is a Common Men / Mixed Men umbrella category."""
    return race is not None and race["slug"] in UMBRELLA_RACE_SLUGS


def list_races(conn: sqlite3.Connection) -> list[dict]:
    """All races, alphabetical by name."""
    return [dict(r) for r in conn.execute(
        f"{_RACE_SELECT} ORDER BY name"
    ).fetchall()]


def get_race_by_id(conn: sqlite3.Connection, race_id: int) -> dict | None:
    row = conn.execute(
        f"{_RACE_SELECT} WHERE race_id = ?", (race_id,)
    ).fetchone()
    return dict(row) if row else None


def get_race_by_slug(conn: sqlite3.Connection, slug: str) -> dict | None:
    row = conn.execute(
        f"{_RACE_SELECT} WHERE slug = ?", (slug,)
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Apply race mods
# ---------------------------------------------------------------------------

def race_stat_mods(race: dict | None) -> dict[StatCode, int]:
    """Return per-StatCode integer mods from a race row, or zeros for None."""
    if race is None:
        return {code: 0 for code in STAT_CODES}
    return {code: int(race[f"stat_{code.lower()}"]) for code in STAT_CODES}


def race_rr_mods(race: dict | None) -> dict[str, int]:
    """Map race rr_ess/rr_chan/rr_ment/rr_pois/rr_dis onto the 9 RR categories
    the web API exposes. The mapping mirrors how RMSS layers race RR onto
    each formula:

      * Pure-realm RRs get that realm's mod (Channeling -> rr_chan, etc.).
      * Hybrid RRs (Chan/Ess, Chan/Ment, Ess/Ment) sum both contributing
        realms' mods, because the RR formula sums those stat temps too.
      * Arcane (Em + In + Pr) sums all three realm mods.
      * Poison/Disease uses rr_pois — RMSS T-1.1 splits poison vs disease
        race mods (e.g. Dwarves Pois=+20 Dis=+15), but the Record Sheet
        T-6.1 collapses them to one "Poison/Disease" RR. We default to
        poison because it's the more common in-play threat; the disease
        delta surfaces via a separate `rr_dis` field on the race object
        for callers who care.
      * Fear has no race RR mod in T-1.1, so it stays at zero.
    """
    if race is None:
        return {
            "channeling": 0, "essence": 0, "mentalism": 0,
            "chan_ess": 0, "chan_ment": 0, "ess_ment": 0,
            "arcane": 0, "poison_disease": 0, "fear": 0,
        }
    chan = int(race["rr_chan"])
    ess  = int(race["rr_ess"])
    ment = int(race["rr_ment"])
    pois = int(race["rr_pois"])
    return {
        "channeling":     chan,
        "essence":        ess,
        "mentalism":      ment,
        "chan_ess":       chan + ess,
        "chan_ment":      chan + ment,
        "ess_ment":       ess + ment,
        "arcane":         chan + ess + ment,
        "poison_disease": pois,
        "fear":           0,
    }


def apply_stat_mods(temps: Mapping[StatCode, int],
                    race: dict | None) -> dict[StatCode, int]:
    """DEPRECATED. Race stat mods do NOT modify the stat value — they
    modify the resulting bonus per RMSS T-1.1. Kept as a passthrough
    for callers that haven't been migrated; remove once the test suite
    no longer imports it."""
    return {code: int(temps[code]) for code in temps}
