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


# ---------------------------------------------------------------------------
# Per-race Body Development and Power Point Development progressions
# ---------------------------------------------------------------------------

# Maps realm name (as stored in profession_realm.realm_name) to the race
# column that carries that realm's PP-Dev progression string.
_REALM_TO_PP_COL: dict[str, str] = {
    "Channeling": "chan_pp_prog",
    "Essence":    "ess_pp_prog",
    "Mentalism":  "ment_pp_prog",
}

# RMSS realm → stat code mapping for Power Point Development:
#   Channeling → Intuition  (In)
#   Essence    → Empathy    (Em)
#   Mentalism  → Presence   (Pr)
# Hybrid spellcasters use the AVERAGE of their contributing realms'
# stat bonuses, rounded down (per RMSS Spell Law / Character Law).
_REALM_TO_PP_STAT: dict[str, StatCode] = {
    "Channeling": "In",
    "Essence":    "Em",
    "Mentalism":  "Pr",
}


def _parse_dotted_to_floats(text: str) -> list[float]:
    """Parse "0 • 7 • 4 • 2 • 1" into [0, 7, 4, 2, 1].

    Returns [] for empty / non-numeric input; callers fall back to
    Standard. Mirrors the parser in core/chargen/skills.py so we
    don't have to depend on that module from here."""
    out: list[float] = []
    for part in text.replace("•", "·").split("·"):
        t = part.strip()
        if not t:
            continue
        try:
            out.append(float(t))
        except ValueError:
            return []
    return out


def _format_dotted(tokens: list[float]) -> str:
    """Inverse of _parse_dotted_to_floats — render as "0 • 7 • 4 • 2 • 1".
    Integers come out as ints (no ".0" tails) so the string round-trips
    against race-file expectations."""
    parts = []
    for t in tokens:
        parts.append(str(int(t)) if t == int(t) else str(t))
    return " • ".join(parts)


def _strip_rank_zero_cell(prog: str) -> str:
    """Race files store progressions in T-2.2 column order — five cells
    where the FIRST is the rank-0 bonus and the remaining four are the
    per-rank rates for bands 1-10, 11-20, 21-30, 31+. The skills.py
    dispatcher, in contrast, treats tokens[0] as the rate for band 1-10
    (it has no rank-0 cell — the dispatcher caller handles "no ranks"
    via the named "Standard" default returning -15).

    We strip the leading rank-0 cell here so the dispatcher gets a
    correctly-shaped 4-band progression string. Blank / unparseable
    input passes through unchanged so the caller's fallback still
    triggers (empty -> Standard).

    No-op if the string only has four tokens (already band-only) or
    fewer (something's wrong with the source data — caller falls back)."""
    tokens = _parse_dotted_to_floats(prog)
    if len(tokens) <= 4:
        # Already band-only, or unparseable / too short — let the caller
        # decide what to do with the original.
        return prog.strip()
    return _format_dotted(tokens[1:])


def body_dev_progression(race: dict | None) -> str:
    """Race-specific Body Development *skill* progression per RMSS T-2.2.

    The category itself uses Standard Category — only the skill is
    race-specific. The race file stores 5 cells (rank-0 + 4 bands); we
    drop the rank-0 cell so the dispatcher reads it as a 4-band string.
    Returns "" when the race is unknown or the field is blank, letting
    the caller fall through to its default."""
    if race is None:
        return ""
    raw = (race.get("body_dev_prog") or "").strip()
    if not raw:
        return ""
    return _strip_rank_zero_cell(raw)


def pp_dev_progression(race: dict | None, realms: list[str]) -> str:
    """Race + realm Power Point Development *skill* progression.

    `realms` is the profession's realm list (e.g. ["Essence"] for a
    Magician, ["Channeling", "Essence"] for a Sorcerer hybrid). For
    one realm we return that race column verbatim. For hybrids we
    take the per-rank minimum across the contributing realms — RMSS
    hybrids land on the worse progression per band, which approximates
    the canonical "halved PP" rule without inventing math the source
    doesn't sanction.

    Returns "" when race is None, realms is empty, or every realm's
    string is unparseable / blank — the caller falls through to
    Standard."""
    if race is None or not realms:
        return ""
    progs: list[list[float]] = []
    for realm in realms:
        col = _REALM_TO_PP_COL.get(realm)
        if col is None:
            continue
        tokens = _parse_dotted_to_floats((race.get(col) or "").strip())
        if tokens:
            progs.append(tokens)
    if not progs:
        return ""
    # Strip each progression's rank-0 cell (same convention as
    # body_dev_progression — race files store 5 cells where the first
    # is the rank-0 bonus and the rest are per-band rates). Drop only
    # when the cell count is >4; shorter strings already band-only.
    def _without_rank_zero(p: list[float]) -> list[float]:
        return p[1:] if len(p) > 4 else p
    progs = [_without_rank_zero(p) for p in progs]

    if len(progs) == 1:
        return _format_dotted(progs[0])
    # Per-rank MIN across contributing realms. Pad to the longest
    # progression with zeros so a missing tail band doesn't accidentally
    # "win" the min — if one realm doesn't grant beyond band 3, the
    # hybrid shouldn't either.
    width = max(len(p) for p in progs)
    padded = [p + [0.0] * (width - len(p)) for p in progs]
    merged = [min(col) for col in zip(*padded)]
    return _format_dotted(merged)


def pp_dev_stat_codes(realms: list[str]) -> list[StatCode]:
    """Realm-driven stat codes that apply to Power Point Development.

    Returns the in-order list of stat codes for the contributing realms,
    deduplicated while preserving order. Magician (Essence) -> ["Em"].
    Sorcerer (Channeling, Essence) -> ["In", "Em"] (in realm-name order).
    Empty if no recognised realm is supplied (non-spell-using profession;
    PP Dev shouldn't get a stat bonus)."""
    out: list[StatCode] = []
    for realm in realms:
        code = _REALM_TO_PP_STAT.get(realm)
        if code is not None and code not in out:
            out.append(code)
    return out


def pp_dev_stat_bonus(
    realms: list[str], raw_temps: Mapping[StatCode, int],
) -> int:
    """Per-character PP Dev stat bonus from the realm-mapped stats.

    Single realm: that realm's stat bonus directly.
    Hybrid 2 realms: the AVERAGE of the two stat bonuses, rounded down
        per RMSS convention for hybrid spellcasters.
    Hybrid 3 realms (Arcane): the average of all three.

    Returns 0 for non-spell-users (no recognised realm) or when raw_temps
    doesn't carry the required stat — caller falls through to no bonus."""
    # Late import to avoid pulling skills.py into race.py; the helper we
    # need is a thin wrapper over T-2.1 that lives in core.chargen.stats.
    from .stats import basic_stat_bonus

    codes = pp_dev_stat_codes(realms)
    if not codes:
        return 0
    bonuses: list[int] = []
    for code in codes:
        if code not in raw_temps:
            continue
        bonuses.append(basic_stat_bonus(int(raw_temps[code])))
    if not bonuses:
        return 0
    # Floor division gives RMSS "rounded down" for the average. For one
    # realm this is just that realm's bonus.
    return sum(bonuses) // len(bonuses)
