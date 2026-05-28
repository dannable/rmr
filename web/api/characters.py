"""Character CRUD endpoints.

Routes here cover the "skeleton" of a character — list/create/view/delete —
plus the first wizard step (stats). The chargen wizard's later steps
(race / profession / skills / spells / outfit) layer on top as additional
nested resources following the same shape.

Every endpoint requires a logged-in user (CurrentUser) and ownership-scopes
characters by owner_user_id — there is no public/shared mode yet.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from core.chargen.stats import (
    STAT_CODES,
    STAT_NAMES,
    StatCode,
    basic_stat_bonus,
    rr_bonus,
    RR_FORMULAS,
)
from core.chargen.race import (
    apply_stat_mods,
    get_race_by_id,
    get_race_by_slug,
    is_umbrella_race,
    race_rr_mods,
    race_stat_mods,
    UMBRELLA_CULTURE_SLUGS,
    UMBRELLA_RACE_SLUGS,
)
from core.chargen.adolescence import grouped_ranks, adolescence_ranks
from core.chargen.weapons import (
    category_for_t16_row,
    filter_race_weapons_by_category,
    all_race_weapons,
)
from core.chargen.weapon_costs import (
    effective_weapon_costs,
    profession_weapon_costs,
    rank_cap_for_cost,
    set_assignments as set_weapon_cost_assignments,
    validate_assignments as validate_weapon_cost_assignments,
    WeaponCostAssignmentError,
)

from ..auth.deps import CurrentUser
from ..db import connect_rw

router = APIRouter(prefix="/api/v1/characters", tags=["characters"])


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------

class Character(BaseModel):
    character_id: int
    owner_user_id: int
    name: str
    level: int
    created_at: str
    updated_at: str
    # Chargen progress. NULL until the picker is used. *_name is denormalised
    # in the response so the client can label without a second fetch.
    race_id: int | None = None
    race_slug: str | None = None
    race_name: str | None = None
    profession_id: int | None = None
    profession_slug: str | None = None
    profession_name: str | None = None
    # Culture sub-pick — only meaningful when race_slug is an umbrella race
    # (Common Men / Mixed Men). Set via PUT /characters/{id}/culture.
    culture_slug: str | None = None
    culture_name: str | None = None
    # True when the current race is one of the RMSS umbrella categories
    # that need a culture sub-pick (Common Men / Mixed Men). The SPA uses
    # this to decide whether to show the Culture picker beside Race.
    race_is_umbrella: bool = False


class CharacterCreate(BaseModel):
    # Name is the only required field for now. Everything else is derived
    # from defaults until the chargen wizard fills it in.
    name: str = Field(..., min_length=1, max_length=80)


class CharacterRacePick(BaseModel):
    # Pass null to clear the character's race. `slug` is preferred over
    # race_id because slugs are stable across `load.py --reset` runs.
    slug: str | None = None


class CharacterCulturePick(BaseModel):
    # Sub-culture under an umbrella race. Pass null to clear. The endpoint
    # validates the character's race is umbrella and the slug is in
    # UMBRELLA_CULTURE_SLUGS — picking a non-Men slug as a "culture" makes
    # no sense in RMSS so we reject it.
    slug: str | None = None


# ---- weapon-cost reassignment (RMSS Character Law §6.2) ----

class WeaponCostRow(BaseModel):
    """One weapon category + its effective cost for this character."""
    weapon_category: str
    cost: str
    # Maximum ranks/level — derived from the cost: "1/5" → 2, "5" → 1.
    rank_cap_per_level: int
    # True when the character has overridden the profession default for
    # this category; the SPA can highlight "moved from default".
    is_override: bool


class WeaponCostsResponse(BaseModel):
    """Per-character weapon-cost view.

    `rows` is the effective cost per category (after any reassignment).
    `pool` is the profession's underlying multiset — the same costs
    re-listed in their default order so the SPA can show "what costs
    can be swapped around". When the character has no profession set,
    both lists are empty.
    """
    profession_slug: str | None
    rows: list[WeaponCostRow]
    pool: list[str]


class WeaponCostAssignment(BaseModel):
    """One row of a PUT body — {weapon_category, cost}."""
    weapon_category: str = Field(..., min_length=1)
    cost: str = Field(..., min_length=1)


class WeaponCostsUpdate(BaseModel):
    """Wholesale replace the character's weapon-cost assignments.

    Pass an empty `assignments` list to clear all overrides (revert to
    profession defaults). Otherwise the list must cover every weapon
    category in the profession's pool, and the multiset of costs must
    equal the pool's multiset. Validation lives in
    core/chargen/weapon_costs.py.
    """
    assignments: list[WeaponCostAssignment] = []


class CharacterProfessionPick(BaseModel):
    # Pass null to clear the character's profession. Same slug-keyed
    # rationale as the race picker.
    slug: str | None = None


# ---- stats sub-resource ----

class StatRow(BaseModel):
    code: StatCode
    name: str
    temp: int
    potential: int
    race_mod: int = 0          # T-1.1 racial stat-bonus modifier (0 when no race).
    basic_bonus: int           # T-2.1(temp) — bonus from temp alone, no race.
    total_bonus: int = 0       # basic_bonus + race_mod — the value used in play.
    # RMSS T-1.2 stat-buy cost for the temporary value (1-90 = face
    # value; 91-100 ramps; 100+ extrapolates). Surfaced so the SPA can
    # show the per-stat cost inline as the user types.
    temp_cost: int = 0
    # True when this stat is one of the profession's prime stats (per
    # profession_prime_stat). RMSS requires primes ≥ 90 at creation.
    is_prime: bool = False


class StatsRR(BaseModel):
    # Race-inclusive totals: the formula-based base plus the relevant race
    # mod. Matches the labels on Character Record Sheet T-6.1.
    channeling: int
    essence: int
    mentalism: int
    chan_ess: int
    chan_ment: int
    ess_ment: int
    arcane: int
    poison_disease: int
    fear: int


class StatsRaceInfo(BaseModel):
    """Slim race header surfaced alongside the stats payload — used by the
    SPA to label which race's mods are being applied."""
    slug: str
    name: str


class StatsBudget(BaseModel):
    """RMSS T-1.2 budget summary for the temporary-stat allocation.

    `spent` is the sum of stat_cost(temp) across all 10 stats. `budget`
    is the standard RMSS fixed allocation (660 points; the alternate
    `600 + 10d10` is the player's call and not modelled here).
    `prime_stats` lists the profession's two primes; the SPA uses
    these to highlight rows that don't meet the ≥90 requirement.
    """
    spent: int
    budget: int
    prime_stats: list[StatCode] = []
    prime_min: int


class CharacterStats(BaseModel):
    stats: list[StatRow]
    resistance_rolls: StatsRR              # totals (formula + race contribution)
    # Race RR mods only (zero for an unraced character). Exposed in
    # parallel so the SPA can render the Base / Race / Total breakdown
    # without re-implementing T-1.1.
    race_rr_mods: StatsRR
    race: StatsRaceInfo | None = None
    budget: StatsBudget
    # Per-level Development Points = (Ag + Co + Me + Re + SD) ÷ 5
    # (round normally). Recomputed server-side from the saved temps; the
    # SPA also mirrors the formula for a live preview as the user types.
    development_points: int = 0


class StatUpdate(BaseModel):
    code: StatCode
    temp: int = Field(..., ge=1, le=102)
    potential: int = Field(..., ge=1, le=102)


class CharacterStatsUpdate(BaseModel):
    stats: list[StatUpdate] = Field(..., min_length=10, max_length=10)


# ---- adolescence-ranks sub-resource ----

class AdolescenceSkill(BaseModel):
    name: str
    value: str
    # When set, the player must pick a specific instance before this row
    # can be applied as a character skill. `choice_kind` is "text"
    # (free-form input, e.g. Riding mount) or "select" (dropdown).
    choice_kind: str | None = None
    # Dropdown options (only populated for choice_kind == "select"). For
    # weapon rows, these are the race's outfitting weapons filtered to
    # the row's RMSS weapon category.
    choice_options: list[str] | None = None
    # The player's current pick for this row (persisted via PUT
    # /adolescence-choices). None if not yet picked.
    choice: str | None = None


class AdolescenceGroup(BaseModel):
    category: str          # e.g. "Armor • Light skill category", or "Summary"
    value: str             # category-level rank (often empty for synthetic groups)
    skills: list[AdolescenceSkill]


class CharacterAdolescence(BaseModel):
    """Starting skill ranks granted to a character during adolescence,
    derived from RMSS T-1.6 by their race/culture. Empty groups list when
    no race is set yet — the SPA shows a "pick a race" empty state.
    """
    culture_slug: str | None      # None when character is unraced
    culture_name: str | None
    groups: list[AdolescenceGroup]


class AdolescenceChoiceItem(BaseModel):
    t16_row: str = Field(..., min_length=1)
    choice:  str = Field(..., max_length=120)   # "" clears the choice


class AdolescenceChoicesUpdate(BaseModel):
    choices: list[AdolescenceChoiceItem]


class AdolescenceApplyResult(BaseModel):
    """Returned by POST /apply-adolescence — what got written into
    character_skill, including any 'pending' rows skipped because the
    player hasn't filled in their specifier yet."""
    applied: int            # number of character_skill rows written
    skipped_pending: list[str]    # t16_row labels needing a choice still


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_character(row) -> Character:
    # Race / culture / profession join columns are nullable — the LEFT JOIN
    # may return Nones, or an older read path may not have them in the row
    # at all.
    def _opt(key: str):
        try:
            return row[key]
        except (KeyError, IndexError):
            return None
    race_slug = _opt("race_slug")
    return Character(
        character_id=row["character_id"],
        owner_user_id=row["owner_user_id"],
        name=row["name"],
        level=row["level"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        race_id=_opt("race_id"),
        race_slug=race_slug,
        race_name=_opt("race_name"),
        profession_id=_opt("profession_id"),
        profession_slug=_opt("profession_slug"),
        profession_name=_opt("profession_name"),
        culture_slug=_opt("culture_slug"),
        culture_name=_opt("culture_name"),
        # Tells the SPA whether the Culture picker should appear next to
        # the Race picker. Only true for Common Men / Mixed Men.
        race_is_umbrella=race_slug in UMBRELLA_RACE_SLUGS if race_slug else False,
    )


# Reusable SELECT clauses; the race + culture + profession joins are LEFT
# so an unraced / unprofessioned character still comes back with NULLs for
# the joined columns. The `c` (culture) join is keyed on slug because
# character.culture_slug is a slug — not an FK to race_id — so swapping
# out the race reference data doesn't break the culture pointer.
_CHARACTER_SELECT = """
    SELECT ch.character_id, ch.owner_user_id, ch.name, ch.level,
           ch.created_at, ch.updated_at, ch.race_id, ch.profession_id,
           r.slug AS race_slug, r.name AS race_name,
           ch.culture_slug AS culture_slug, c.name AS culture_name,
           p.slug AS profession_slug, p.name AS profession_name
      FROM character ch
      LEFT JOIN race r ON r.race_id = ch.race_id
      LEFT JOIN race c ON c.slug = ch.culture_slug
      LEFT JOIN profession p ON p.profession_id = ch.profession_id
"""


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------

@router.get("", response_model=list[Character])
def list_characters(user: dict = CurrentUser) -> list[Character]:
    """List the current user's characters, newest first."""
    with connect_rw() as conn:
        rows = conn.execute(
            f"{_CHARACTER_SELECT} WHERE ch.owner_user_id = ? ORDER BY ch.created_at DESC",
            (user["user_id"],),
        ).fetchall()
    return [_row_to_character(r) for r in rows]


@router.post("", response_model=Character, status_code=status.HTTP_201_CREATED)
def create_character(body: CharacterCreate, user: dict = CurrentUser) -> Character:
    """Create a blank character owned by the current user.

    Seeds the 10 RMSS stats at 50/50 (temp/potential), which gives a neutral
    +0 bonus across the board. The wizard's stats step lets the user pick
    actual values. Race starts NULL; the picker fills it in.
    """
    now = _utcnow()
    with connect_rw() as conn:
        cur = conn.execute(
            """
            INSERT INTO character (owner_user_id, name, level, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            RETURNING character_id
            """,
            (user["user_id"], body.name.strip(), now, now),
        )
        character_id = cur.fetchone()["character_id"]
        conn.executemany(
            "INSERT INTO character_stat (character_id, stat_code, temp, potential) "
            "VALUES (?, ?, 50, 50)",
            [(character_id, code) for code in STAT_CODES],
        )
        # Re-SELECT through the race-aware view so the response shape matches
        # the other endpoints (race_id/slug/name fields populated as NULL).
        row = conn.execute(
            f"{_CHARACTER_SELECT} WHERE ch.character_id = ?",
            (character_id,),
        ).fetchone()
        conn.commit()
    return _row_to_character(row)


@router.get("/{character_id}", response_model=Character)
def get_character(character_id: int, user: dict = CurrentUser) -> Character:
    with connect_rw() as conn:
        row = conn.execute(
            f"{_CHARACTER_SELECT} WHERE ch.character_id = ?",
            (character_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    # Don't reveal existence of characters owned by other users — same 404.
    if row["owner_user_id"] != user["user_id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    return _row_to_character(row)


@router.delete("/{character_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_character(character_id: int, user: dict = CurrentUser) -> None:
    with connect_rw() as conn:
        # Two-step so we can return 404 vs 204 distinctly while still scoping
        # to owner_user_id in the DELETE itself (defence in depth).
        row = conn.execute(
            "SELECT owner_user_id FROM character WHERE character_id = ?",
            (character_id,),
        ).fetchone()
        if row is None or row["owner_user_id"] != user["user_id"]:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
        conn.execute(
            "DELETE FROM character WHERE character_id = ? AND owner_user_id = ?",
            (character_id, user["user_id"]),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# stats sub-resource
# ---------------------------------------------------------------------------

def _assert_owned(conn: sqlite3.Connection, character_id: int, user_id: int) -> None:
    """Raise 404 if character_id doesn't exist or isn't owned by user_id."""
    row = conn.execute(
        "SELECT owner_user_id FROM character WHERE character_id = ?",
        (character_id,),
    ).fetchone()
    if row is None or row["owner_user_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")


def _build_stats_payload(
    rows: list,
    race: dict | None = None,
    prime_stats: list[StatCode] | None = None,
) -> CharacterStats:
    """Turn `character_stat` rows into the API payload.

    Per RMSS T-1.1, a racial stat modifier is added to the *bonus*
    (T-2.1 result), not to the temp value itself. So:

        stat_bonus    = T-2.1(temp)
        total_bonus   = stat_bonus + race_stat_mod
        RR_total      = multiplier × Σ total_bonus[stats] + race_RR_mod

    `prime_stats` (the profession's primes, by 2-letter code) tags the
    StatRows for the SPA's "prime stats need ≥90" check.
    """
    from core.chargen.stats import (
        development_points,
        PRIME_STAT_MIN,
        stat_cost,
        TEMP_STAT_BUDGET,
        total_stat_cost,
    )

    by_code: dict[StatCode, dict] = {r["stat_code"]: dict(r) for r in rows}
    stat_mods = race_stat_mods(race)
    rr_mods = race_rr_mods(race)

    raw_temps = {code: by_code[code]["temp"] for code in STAT_CODES}
    # Per-stat final bonus = T-2.1(temp) + race stat mod. This is the
    # "Total" column the SPA renders and the value RR formulas plug in.
    stat_bonuses_by_code: dict[StatCode, int] = {
        code: basic_stat_bonus(raw_temps[code]) + stat_mods[code]
        for code in STAT_CODES
    }

    primes_set = set(prime_stats or [])
    stats = [
        StatRow(
            code=code,
            name=STAT_NAMES[code],
            temp=by_code[code]["temp"],
            potential=by_code[code]["potential"],
            race_mod=stat_mods[code],
            basic_bonus=basic_stat_bonus(raw_temps[code]),
            total_bonus=stat_bonuses_by_code[code],
            temp_cost=stat_cost(by_code[code]["temp"]),
            is_prime=(code in primes_set),
        )
        for code in STAT_CODES
    ]
    # RR rolls multiply the relevant stat *bonuses* (not raw temps),
    # then add the race RR mod.
    rr = StatsRR(
        channeling=rr_bonus(stat_bonuses_by_code, "Channeling")    + rr_mods["channeling"],
        essence=rr_bonus(stat_bonuses_by_code, "Essence")          + rr_mods["essence"],
        mentalism=rr_bonus(stat_bonuses_by_code, "Mentalism")      + rr_mods["mentalism"],
        chan_ess=rr_bonus(stat_bonuses_by_code, "Chan/Ess")        + rr_mods["chan_ess"],
        chan_ment=rr_bonus(stat_bonuses_by_code, "Chan/Ment")      + rr_mods["chan_ment"],
        ess_ment=rr_bonus(stat_bonuses_by_code, "Ess/Ment")        + rr_mods["ess_ment"],
        arcane=rr_bonus(stat_bonuses_by_code, "Arcane")            + rr_mods["arcane"],
        poison_disease=rr_bonus(stat_bonuses_by_code, "Poison/Disease") + rr_mods["poison_disease"],
        fear=rr_bonus(stat_bonuses_by_code, "Fear")                 + rr_mods["fear"],
    )
    race_info = (
        StatsRaceInfo(slug=race["slug"], name=race["name"]) if race else None
    )
    budget = StatsBudget(
        spent=total_stat_cost(raw_temps),
        budget=TEMP_STAT_BUDGET,
        prime_stats=list(prime_stats or []),
        prime_min=PRIME_STAT_MIN,
    )
    return CharacterStats(
        stats=stats,
        resistance_rolls=rr,
        race_rr_mods=StatsRR(**rr_mods),
        race=race_info,
        budget=budget,
        development_points=development_points(raw_temps),
    )


def _load_character_race(conn: sqlite3.Connection, character_id: int) -> dict | None:
    """Look up the character's race row (or None if unraced / unknown char)."""
    row = conn.execute(
        "SELECT race_id FROM character WHERE character_id = ?",
        (character_id,),
    ).fetchone()
    if row is None or row["race_id"] is None:
        return None
    return get_race_by_id(conn, row["race_id"])


def _load_character_prime_stats(conn: sqlite3.Connection,
                                character_id: int) -> list[StatCode]:
    """Return the profession's prime stat codes for a character, or []."""
    row = conn.execute(
        "SELECT profession_id FROM character WHERE character_id = ?",
        (character_id,),
    ).fetchone()
    if row is None or row["profession_id"] is None:
        return []
    return [
        r[0] for r in conn.execute(
            "SELECT stat_code FROM profession_prime_stat "
            "WHERE profession_id = ? ORDER BY stat_code",
            (row["profession_id"],),
        ).fetchall()
    ]


@router.get("/{character_id}/stats", response_model=CharacterStats)
def get_character_stats(character_id: int, user: dict = CurrentUser) -> CharacterStats:
    """Return the 10 stats for a character plus race-folded bonuses + RR totals."""
    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])
        rows = conn.execute(
            "SELECT stat_code, temp, potential FROM character_stat WHERE character_id = ?",
            (character_id,),
        ).fetchall()
        if len(rows) != len(STAT_CODES):
            # Legacy rows (pre-stats migration) — backfill defaults on the fly.
            existing = {r["stat_code"] for r in rows}
            missing = [c for c in STAT_CODES if c not in existing]
            conn.executemany(
                "INSERT INTO character_stat (character_id, stat_code, temp, potential) "
                "VALUES (?, ?, 50, 50)",
                [(character_id, code) for code in missing],
            )
            conn.commit()
            rows = conn.execute(
                "SELECT stat_code, temp, potential FROM character_stat WHERE character_id = ?",
                (character_id,),
            ).fetchall()
        race = _load_character_race(conn, character_id)
        primes = _load_character_prime_stats(conn, character_id)
    return _build_stats_payload(rows, race=race, prime_stats=primes)


@router.put("/{character_id}/stats", response_model=CharacterStats)
def update_character_stats(
    character_id: int,
    body: CharacterStatsUpdate,
    user: dict = CurrentUser,
) -> CharacterStats:
    """Replace the 10 stats wholesale. Body must contain exactly the 10 codes."""
    seen: set[StatCode] = {s.code for s in body.stats}
    if seen != set(STAT_CODES):
        missing = set(STAT_CODES) - seen
        extra = seen - set(STAT_CODES)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"missing": sorted(missing), "extra": sorted(extra)},
        )

    now = _utcnow()
    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])
        for s in body.stats:
            conn.execute(
                """
                UPDATE character_stat
                   SET temp = ?, potential = ?
                 WHERE character_id = ? AND stat_code = ?
                """,
                (s.temp, s.potential, character_id, s.code),
            )
        conn.execute(
            "UPDATE character SET updated_at = ? WHERE character_id = ?",
            (now, character_id),
        )
        rows = conn.execute(
            "SELECT stat_code, temp, potential FROM character_stat WHERE character_id = ?",
            (character_id,),
        ).fetchall()
        race = _load_character_race(conn, character_id)
        primes = _load_character_prime_stats(conn, character_id)
        conn.commit()
    return _build_stats_payload(rows, race=race, prime_stats=primes)


# ---- stats sub-resource: T-1.3 potential generators ------------------------

def _refresh_potentials(
    character_id: int,
    user_id: int,
    fn,
) -> CharacterStats:
    """Read each temp, run `fn(temp)` per stat, write back potentials,
    and return the freshened CharacterStats payload. `fn` is either
    `random_potential` (T-1.3 roll) or `fixed_potential` (T-1.3 Fixed
    Mod alternative)."""
    now = _utcnow()
    with connect_rw() as conn:
        _assert_owned(conn, character_id, user_id)
        rows = conn.execute(
            "SELECT stat_code, temp, potential FROM character_stat WHERE character_id = ?",
            (character_id,),
        ).fetchall()
        for r in rows:
            new_potential = fn(int(r["temp"]))
            conn.execute(
                "UPDATE character_stat SET potential = ? "
                "WHERE character_id = ? AND stat_code = ?",
                (new_potential, character_id, r["stat_code"]),
            )
        conn.execute(
            "UPDATE character SET updated_at = ? WHERE character_id = ?",
            (now, character_id),
        )
        rows = conn.execute(
            "SELECT stat_code, temp, potential FROM character_stat WHERE character_id = ?",
            (character_id,),
        ).fetchall()
        race = _load_character_race(conn, character_id)
        primes = _load_character_prime_stats(conn, character_id)
        conn.commit()
    return _build_stats_payload(rows, race=race, prime_stats=primes)


@router.post("/{character_id}/roll-potentials", response_model=CharacterStats)
def roll_character_potentials(
    character_id: int,
    user: dict = CurrentUser,
) -> CharacterStats:
    """Roll all 10 potential stats per RMSS T-1.3 dice formulas.

    Wholesale replacement: every stat's potential is re-rolled from its
    current temp. The "potential ≥ temp" floor from the table's footnote
    is applied. Source of randomness is `random.SystemRandom()` so the
    roll can't be reverse-engineered from a previous one.
    """
    from core.chargen.stats import random_potential
    return _refresh_potentials(character_id, user["user_id"], random_potential)


@router.post("/{character_id}/apply-fixed-potentials", response_model=CharacterStats)
def apply_fixed_potentials(
    character_id: int,
    user: dict = CurrentUser,
) -> CharacterStats:
    """Apply the RMSS T-1.3 Fixed Mod alternative to every stat.

    Per the table's "†" footnote, players may opt to skip dice and add
    the printed fixed mod to each temp (e.g. +44 for temps 20-24, +6
    for 85-91, etc.). Wholesale replacement, like the roll endpoint.
    """
    from core.chargen.stats import fixed_potential
    return _refresh_potentials(character_id, user["user_id"], fixed_potential)


@router.post("/{character_id}/raise-primes-to-90", response_model=CharacterStats)
def raise_primes_to_90(
    character_id: int,
    user: dict = CurrentUser,
) -> CharacterStats:
    """Bump every prime stat (per the character's profession) that's
    below 90 up to exactly 90. Potentials are raised to match if they'd
    otherwise be below the new temp.

    RMSS requires each prime ≥ 90 at creation; this is the one-click
    way to enforce that without re-typing. The cost shows up in the
    SPA's budget banner — the endpoint doesn't enforce budget caps,
    matching the existing PUT /stats behaviour.
    """
    from core.chargen.stats import PRIME_STAT_MIN
    now = _utcnow()
    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])
        primes = _load_character_prime_stats(conn, character_id)
        if primes:
            for code in primes:
                conn.execute(
                    "UPDATE character_stat "
                    "   SET temp = MAX(temp, ?), "
                    "       potential = MAX(potential, ?) "
                    " WHERE character_id = ? AND stat_code = ?",
                    (PRIME_STAT_MIN, PRIME_STAT_MIN, character_id, code),
                )
            conn.execute(
                "UPDATE character SET updated_at = ? WHERE character_id = ?",
                (now, character_id),
            )
        rows = conn.execute(
            "SELECT stat_code, temp, potential FROM character_stat WHERE character_id = ?",
            (character_id,),
        ).fetchall()
        race = _load_character_race(conn, character_id)
        conn.commit()
    return _build_stats_payload(rows, race=race, prime_stats=primes)


# ---------------------------------------------------------------------------
# race sub-resource
# ---------------------------------------------------------------------------

def _resolved_skill_name(t16_row: str, choice: str | None) -> str | None:
    """Compose the canonical character_skill name for a T-1.6 row + choice.

    Rows that DO NOT require a choice are returned as the row label minus
    the boilerplate " skill" suffix. Rows requiring a choice but missing
    one return None — the apply step skips those.
    """
    kind, _options = _choice_metadata(t16_row, weapons_text="")
    if kind is None:
        return t16_row.removesuffix(" skill").strip()
    if not choice:
        return None   # specifier required but not picked yet
    if kind == "select":
        # Weapon row: weapon-category prefix + selected weapon name.
        cat = category_for_t16_row(t16_row) or "Weapon"
        return f"{cat}: {choice}"
    # text → "<Skill> (<specifier>)" form. Strip the trailing parenthetical
    # hint and the boilerplate " skill" word out of the label first so we
    # produce e.g. "Riding (horses)" not "Riding skill (usually horses)".
    base = re.sub(r"\s*\(.*?\)\s*$", "", t16_row).strip()
    base = base.removesuffix(" skill").strip()
    return f"{base} ({choice})"


def _choice_metadata(t16_row: str, weapons_text: str) -> tuple[str | None, list[str] | None]:
    """Decide whether a T-1.6 row needs user input.

    Returns (choice_kind, options) where:
      * choice_kind = "select"  → dropdown (options populated)
      * choice_kind = "text"    → free-text input (options=None)
      * choice_kind = None      → no input needed (rank applies directly)
    """
    # 1 Weapon Based on Culture/Race ‡ — under each weapon-category prefix.
    if t16_row.endswith("1 Weapon Based on Culture/Race ‡"):
        cat = category_for_t16_row(t16_row)
        if cat:
            options = filter_race_weapons_by_category(weapons_text, cat)
            if not options:
                # Fall back to the full race weapons list when the filter
                # finds nothing (e.g. the race's outfitting doesn't include
                # a weapon in this category). User can still pick something.
                options = all_race_weapons(weapons_text)
            return "select", options
        return "text", None
    # Riding skill — free-text for the mount.
    if t16_row.startswith("Riding skill"):
        return "text", None
    return None, None


@router.get("/{character_id}/adolescence-ranks", response_model=CharacterAdolescence)
def get_character_adolescence(
    character_id: int,
    user: dict = CurrentUser,
) -> CharacterAdolescence:
    """Look up the starting skill ranks for the character's race/culture.

    For umbrella races (Common Men / Mixed Men), T-1.6 data is keyed
    by the SUB-culture; we fall through to character.culture_slug and
    look up the row whose slug matches. If the race is umbrella but no
    culture is picked yet, return (umbrella_race, [], pending=true) so
    the SPA can point the user at the Culture picker. For concrete
    races, culture_slug == race.slug as before.

    Each leaf row carries per-row metadata identifying whether the player
    must pick a specifier before the rank can be applied — `choice_kind`
    is "text" (free input) or "select" (dropdown), with `choice_options`
    populated for selects and `choice` reflecting the player's saved pick.
    """
    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])
        race = _load_character_race(conn, character_id)
        if race is None:
            return CharacterAdolescence(culture_slug=None, culture_name=None, groups=[])

        # Resolve the row whose adolescence data we actually want. For an
        # umbrella race, that's the picked culture (if any); otherwise the
        # race row itself doubles as the culture row.
        effective = race
        if is_umbrella_race(race):
            culture_slug_picked = conn.execute(
                "SELECT culture_slug FROM character WHERE character_id = ?",
                (character_id,),
            ).fetchone()
            picked = culture_slug_picked["culture_slug"] if culture_slug_picked else None
            if not picked:
                # Race is umbrella but no culture picked — the SPA will
                # show the Culture picker; return the umbrella race
                # header with empty groups so the user can still see what
                # they've selected.
                return CharacterAdolescence(
                    culture_slug=race["slug"],
                    culture_name=race["name"],
                    groups=[],
                )
            culture_row = get_race_by_slug(conn, picked)
            if culture_row is not None:
                effective = culture_row
            # else: stale slug (reference data wiped) — fall back to the
            # umbrella row, which yields empty groups.

        # Pull the effective row's weapons text out of culture_data for
        # the dropdown options.
        import json
        weapons_text = ""
        try:
            cd = json.loads(effective.get("culture_data") or "{}")
            if isinstance(cd, dict):
                weapons_text = cd.get("weapons", "") or ""
        except (TypeError, ValueError):
            pass
        groups = grouped_ranks(conn, effective["slug"])
        # Load existing player picks for this character.
        choices_rows = conn.execute(
            "SELECT t16_row, choice FROM character_adolescence_choice "
            "WHERE character_id = ?",
            (character_id,),
        ).fetchall()
        choice_by_row = {r["t16_row"]: r["choice"] for r in choices_rows}

    # Enrich each leaf skill with choice metadata + saved pick.
    out_groups: list[AdolescenceGroup] = []
    for g in groups:
        enriched: list[AdolescenceSkill] = []
        for s in g["skills"]:
            kind, options = _choice_metadata(s["name"], weapons_text)
            enriched.append(AdolescenceSkill(
                name=s["name"],
                value=s["value"],
                choice_kind=kind,
                choice_options=options,
                choice=choice_by_row.get(s["name"]),
            ))
        out_groups.append(AdolescenceGroup(
            category=g["category"], value=g["value"], skills=enriched,
        ))
    return CharacterAdolescence(
        culture_slug=effective["slug"],
        culture_name=effective["name"],
        groups=out_groups,
    )


@router.put("/{character_id}/adolescence-choices", response_model=CharacterAdolescence)
def update_character_adolescence_choices(
    character_id: int,
    body: AdolescenceChoicesUpdate,
    user: dict = CurrentUser,
) -> CharacterAdolescence:
    """Set the player's picks for "specify-required" T-1.6 rows.

    Empty `choice` strings clear the existing pick for a row. Returns the
    refreshed adolescence-ranks payload so the SPA can re-render without
    a second round-trip.
    """
    now = _utcnow()
    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])
        for item in body.choices:
            choice = item.choice.strip()
            if choice:
                conn.execute(
                    "INSERT INTO character_adolescence_choice (character_id, t16_row, choice) "
                    "VALUES (?, ?, ?) ON CONFLICT(character_id, t16_row) DO UPDATE SET "
                    "choice = excluded.choice",
                    (character_id, item.t16_row, choice),
                )
            else:
                conn.execute(
                    "DELETE FROM character_adolescence_choice "
                    "WHERE character_id = ? AND t16_row = ?",
                    (character_id, item.t16_row),
                )
        conn.execute(
            "UPDATE character SET updated_at = ? WHERE character_id = ?",
            (now, character_id),
        )
        conn.commit()
    return get_character_adolescence(character_id, user)


@router.post("/{character_id}/apply-adolescence", response_model=AdolescenceApplyResult)
def apply_character_adolescence(
    character_id: int,
    user: dict = CurrentUser,
) -> AdolescenceApplyResult:
    """Translate the current T-1.6 ranks + picks into character_skill rows.

    Idempotent within source='adolescence' — re-applying clears the
    previous adolescence-sourced ranks and writes the current view, so
    swapping a weapon pick + re-applying does the right thing. Skills
    where the player hasn't yet picked a required specifier are skipped
    and their t16_row labels returned in `skipped_pending`.
    """
    now = _utcnow()
    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])
        race = _load_character_race(conn, character_id)
        if race is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Pick a race before applying adolescence ranks.",
            )
        # Umbrella race? Apply uses the culture's T-1.6 rows. If no
        # culture picked, there's nothing to apply — error so the SPA
        # doesn't silently no-op a click.
        effective_slug = race["slug"]
        if is_umbrella_race(race):
            culture_row = conn.execute(
                "SELECT culture_slug FROM character WHERE character_id = ?",
                (character_id,),
            ).fetchone()
            picked = culture_row["culture_slug"] if culture_row else None
            if not picked:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Pick a culture before applying adolescence ranks "
                           f"({race['name']} is an umbrella category in RMSS).",
                )
            effective_slug = picked
        rows = adolescence_ranks(conn, effective_slug)
        choices_rows = conn.execute(
            "SELECT t16_row, choice FROM character_adolescence_choice "
            "WHERE character_id = ?",
            (character_id,),
        ).fetchall()
        choice_by_row = {r["t16_row"]: r["choice"] for r in choices_rows}

        # Wipe existing adolescence-sourced rows, write the fresh set.
        conn.execute(
            "DELETE FROM character_skill WHERE character_id = ? AND source = 'adolescence'",
            (character_id,),
        )
        applied = 0
        skipped: list[str] = []
        for r in rows:
            row_kind = r["kind"]
            if row_kind == "summary":
                # "Hobby Ranks", "Number of Background Options" — not skills.
                continue
            try:
                rank = int(r["value"])
            except ValueError:
                continue
            if rank <= 0:
                continue
            if row_kind == "category":
                # Adolescence-granted CATEGORY rank. Strip the
                # " skill category" suffix so it matches the allocator's
                # canonical "{group} • {category}" storage.
                cat_name = r["skill"]
                for suffix in (" skill category", " skill_category"):
                    if cat_name.endswith(suffix):
                        cat_name = cat_name[:-len(suffix)]
                        break
                cat_name = cat_name.strip()
                if not cat_name:
                    continue
                conn.execute(
                    "INSERT INTO character_skill "
                    "(character_id, skill, kind, rank, source) "
                    "VALUES (?, ?, 'category', ?, 'adolescence') "
                    "ON CONFLICT (character_id, kind, skill, source) "
                    "DO UPDATE SET rank = excluded.rank",
                    (character_id, cat_name, rank),
                )
                applied += 1
                continue
            # leaf row
            resolved = _resolved_skill_name(r["skill"], choice_by_row.get(r["skill"]))
            if resolved is None:
                skipped.append(r["skill"])
                continue
            conn.execute(
                "INSERT INTO character_skill "
                "(character_id, skill, kind, rank, source) "
                "VALUES (?, ?, 'skill', ?, 'adolescence') "
                "ON CONFLICT (character_id, kind, skill, source) "
                "DO UPDATE SET rank = excluded.rank",
                (character_id, resolved, rank),
            )
            applied += 1
        conn.execute(
            "UPDATE character SET updated_at = ? WHERE character_id = ?",
            (now, character_id),
        )
        conn.commit()
    return AdolescenceApplyResult(applied=applied, skipped_pending=skipped)


@router.put("/{character_id}/race", response_model=Character)
def update_character_race(
    character_id: int,
    body: CharacterRacePick,
    user: dict = CurrentUser,
) -> Character:
    """Set (or clear, when slug is null) the character's race.

    The race lookup uses slug — race_id is internal — so saved characters
    don't lose their race if reference data is rebuilt. Changing the race
    away from an umbrella (Common Men / Mixed Men) clears the existing
    culture_slug, since a sub-culture pick is meaningless under a concrete
    race; the SPA stops showing the Culture picker in that state too.
    Returns the updated Character (with race fields populated).
    """
    now = _utcnow()
    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])
        if body.slug is None:
            race_id = None
            new_race_slug: str | None = None
        else:
            race = get_race_by_slug(conn, body.slug)
            if race is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Unknown race slug: {body.slug!r}",
                )
            race_id = race["race_id"]
            new_race_slug = race["slug"]

        # If the new race isn't umbrella, drop any stale culture pick so we
        # don't leak data into a state the picker can't reach. We do this
        # unconditionally on the SET — picking the same umbrella race twice
        # keeps the existing culture intact because the slug is still in
        # UMBRELLA_RACE_SLUGS.
        clear_culture = new_race_slug not in UMBRELLA_RACE_SLUGS
        if clear_culture:
            conn.execute(
                "UPDATE character SET race_id = ?, culture_slug = NULL, updated_at = ? "
                "WHERE character_id = ?",
                (race_id, now, character_id),
            )
        else:
            conn.execute(
                "UPDATE character SET race_id = ?, updated_at = ? "
                "WHERE character_id = ?",
                (race_id, now, character_id),
            )
        row = conn.execute(
            f"{_CHARACTER_SELECT} WHERE ch.character_id = ?",
            (character_id,),
        ).fetchone()
        conn.commit()
    return _row_to_character(row)


@router.put("/{character_id}/culture", response_model=Character)
def update_character_culture(
    character_id: int,
    body: CharacterCulturePick,
    user: dict = CurrentUser,
) -> Character:
    """Set (or clear) the character's culture sub-pick.

    Only valid when the character's race is one of the RMSS umbrella
    categories (Common Men / Mixed Men). The slug must be one of the 7
    Men cultures in UMBRELLA_CULTURE_SLUGS; picking, say, "dwarves" as a
    Common-Men culture is nonsensical and gets a 422.
    """
    now = _utcnow()
    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])
        race = _load_character_race(conn, character_id)
        if not is_umbrella_race(race):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Culture is only meaningful when race is Common Men "
                       "or Mixed Men.",
            )
        if body.slug is None:
            culture_slug: str | None = None
        else:
            if body.slug not in UMBRELLA_CULTURE_SLUGS:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Unknown culture slug: {body.slug!r}. "
                           f"Valid: {', '.join(UMBRELLA_CULTURE_SLUGS)}.",
                )
            # Belt-and-braces: confirm the slug actually exists in the race
            # table (load.py keeps these in sync, but a half-loaded DB
            # shouldn't 500).
            if get_race_by_slug(conn, body.slug) is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Culture {body.slug!r} not found in reference data.",
                )
            culture_slug = body.slug
        conn.execute(
            "UPDATE character SET culture_slug = ?, updated_at = ? "
            "WHERE character_id = ?",
            (culture_slug, now, character_id),
        )
        row = conn.execute(
            f"{_CHARACTER_SELECT} WHERE ch.character_id = ?",
            (character_id,),
        ).fetchone()
        conn.commit()
    return _row_to_character(row)


# ---------------------------------------------------------------------------
# weapon-cost reassignment sub-resource (RMSS Character Law §6.2)
# ---------------------------------------------------------------------------

def _load_character_profession_id(
    conn: sqlite3.Connection, character_id: int,
) -> int | None:
    """Return the character's profession_id (or None if unprofessioned)."""
    row = conn.execute(
        "SELECT profession_id FROM character WHERE character_id = ?",
        (character_id,),
    ).fetchone()
    if row is None:
        return None
    return row["profession_id"]


def _cost_sort_key(cost: str) -> tuple[int, int, str]:
    """Sort costs so cheaper / higher-rank-cap costs come first. '1/5'
    (2 ranks, 1 DP) sorts before '5' (1 rank, 5 DP), matching how players
    prioritise picks. Returns (-rank_count, first_dp, raw)."""
    parts = [p.strip() for p in cost.split("/")]
    try:
        first = int(parts[0]) if parts and parts[0] else 999
    except ValueError:
        first = 999
    return (-len(parts), first, cost)


def _build_weapon_costs_response(
    conn: sqlite3.Connection,
    character_id: int,
    profession_slug: str | None,
    profession_id: int | None,
) -> "WeaponCostsResponse":
    """Snapshot the character's effective weapon costs + the profession pool."""
    if profession_id is None:
        return WeaponCostsResponse(
            profession_slug=profession_slug, rows=[], pool=[],
        )
    defaults = profession_weapon_costs(conn, profession_id)
    effective = effective_weapon_costs(conn, character_id, profession_id)
    rows = [
        WeaponCostRow(
            weapon_category=cat,
            cost=effective[cat],
            rank_cap_per_level=rank_cap_for_cost(effective[cat]),
            is_override=(defaults.get(cat) != effective[cat]),
        )
        for cat in sorted(effective)
    ]
    pool = sorted(defaults.values(), key=_cost_sort_key)
    return WeaponCostsResponse(
        profession_slug=profession_slug, rows=rows, pool=pool,
    )


@router.get("/{character_id}/weapon-costs", response_model=WeaponCostsResponse)
def get_character_weapon_costs(
    character_id: int,
    user: dict = CurrentUser,
) -> WeaponCostsResponse:
    """Effective per-category weapon costs + the profession's pool.

    Empty rows + pool when the character has no profession picked yet.
    The SPA uses this to render the WeaponCostPicker; the player can
    reassign which category gets which cost, subject to the pool
    multiset matching.
    """
    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])
        prof_id = _load_character_profession_id(conn, character_id)
        prof_slug_row = conn.execute(
            "SELECT p.slug FROM character ch "
            "LEFT JOIN profession p ON p.profession_id = ch.profession_id "
            "WHERE ch.character_id = ?",
            (character_id,),
        ).fetchone()
        prof_slug = prof_slug_row[0] if prof_slug_row else None
        return _build_weapon_costs_response(conn, character_id, prof_slug, prof_id)


@router.put("/{character_id}/weapon-costs", response_model=WeaponCostsResponse)
def update_character_weapon_costs(
    character_id: int,
    body: WeaponCostsUpdate,
    user: dict = CurrentUser,
) -> WeaponCostsResponse:
    """Replace the character's weapon-cost overrides.

    Send an empty `assignments` list to clear all overrides (revert to
    profession defaults). Otherwise the assignment must cover every
    weapon category in the profession's pool, and the cost multiset
    must equal the pool's multiset — see
    core.chargen.weapon_costs.validate_assignments for rules.

    Returns the refreshed snapshot so the SPA can re-render without a
    second round-trip.
    """
    now = _utcnow()
    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])
        prof_id = _load_character_profession_id(conn, character_id)
        if prof_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Pick a profession before reassigning weapon costs.",
            )
        prof_slug_row = conn.execute(
            "SELECT slug FROM profession WHERE profession_id = ?",
            (prof_id,),
        ).fetchone()
        prof_slug = prof_slug_row[0] if prof_slug_row else None

        assignments = {row.weapon_category: row.cost for row in body.assignments}
        if assignments:
            try:
                validate_weapon_cost_assignments(
                    profession_weapon_costs(conn, prof_id), assignments,
                )
            except WeaponCostAssignmentError as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(e),
                )
        set_weapon_cost_assignments(conn, character_id, assignments)
        conn.execute(
            "UPDATE character SET updated_at = ? WHERE character_id = ?",
            (now, character_id),
        )
        conn.commit()
        return _build_weapon_costs_response(conn, character_id, prof_slug, prof_id)


class BackgroundOptionPick(BaseModel):
    """One row in the /background-options payload."""
    option_key: str = Field(..., min_length=1)
    detail: str = Field("", max_length=200)


class BackgroundOptionsUpdate(BaseModel):
    """Wholesale replace the character's background-option picks. The
    server takes the list verbatim — over-budget picks are still
    persisted (the SPA renders a warning), so the GM can grant
    exceptions without the API gatekeeping."""
    picks: list[BackgroundOptionPick]


class BackgroundOptionCatalogEntry(BaseModel):
    """One T-1.5 menu entry surfaced for the SPA."""
    key: str
    label: str
    description: str
    wants_detail: bool
    detail_placeholder: str


class BackgroundOptionsResponse(BaseModel):
    """GET / PUT response payload — current picks + max + the static
    T-1.5 catalog so the SPA doesn't need a second fetch."""
    picks: list[BackgroundOptionPick]
    max_options: int
    catalog: list[BackgroundOptionCatalogEntry]


@router.get("/{character_id}/background-options",
            response_model=BackgroundOptionsResponse)
def get_character_background_options(
    character_id: int,
    user: dict = CurrentUser,
) -> BackgroundOptionsResponse:
    """Return the character's current background-options picks + the
    full T-1.5 catalog + how many options the player may still take."""
    from core.chargen.background import BACKGROUND_OPTIONS
    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])
        race = _load_character_race(conn, character_id)
        max_options = int(race.get("bg_opts") or 0) if race else 0
        picks = [
            BackgroundOptionPick(option_key=r["option_key"], detail=r["detail"])
            for r in conn.execute(
                "SELECT sort_order, option_key, detail "
                "FROM character_background_option "
                "WHERE character_id = ? ORDER BY sort_order",
                (character_id,),
            ).fetchall()
        ]
    return BackgroundOptionsResponse(
        picks=picks,
        max_options=max_options,
        catalog=[BackgroundOptionCatalogEntry(**o) for o in BACKGROUND_OPTIONS],
    )


@router.put("/{character_id}/background-options",
            response_model=BackgroundOptionsResponse)
def update_character_background_options(
    character_id: int,
    body: BackgroundOptionsUpdate,
    user: dict = CurrentUser,
) -> BackgroundOptionsResponse:
    """Replace the character's background-option picks wholesale.

    Each unknown option_key is rejected (422); detail strings pass
    through verbatim. The endpoint does NOT enforce the race-dependent
    cap on total picks — the SPA shows a warning when over-budget, but
    GM-granted exceptions can still be saved."""
    from core.chargen.background import (
        BACKGROUND_OPTION_KEYS,
        BACKGROUND_OPTIONS,
    )
    bad = [p.option_key for p in body.picks if p.option_key not in BACKGROUND_OPTION_KEYS]
    if bad:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown background option(s): {sorted(set(bad))}",
        )

    now = _utcnow()
    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])
        conn.execute(
            "DELETE FROM character_background_option WHERE character_id = ?",
            (character_id,),
        )
        for i, p in enumerate(body.picks):
            conn.execute(
                "INSERT INTO character_background_option "
                "(character_id, sort_order, option_key, detail) "
                "VALUES (?, ?, ?, ?)",
                (character_id, i, p.option_key, p.detail or ""),
            )
        conn.execute(
            "UPDATE character SET updated_at = ? WHERE character_id = ?",
            (now, character_id),
        )
        race = _load_character_race(conn, character_id)
        max_options = int(race.get("bg_opts") or 0) if race else 0
        conn.commit()

    return BackgroundOptionsResponse(
        picks=[BackgroundOptionPick(**p.model_dump()) for p in body.picks],
        max_options=max_options,
        catalog=[BackgroundOptionCatalogEntry(**o) for o in BACKGROUND_OPTIONS],
    )


@router.put("/{character_id}/profession", response_model=Character)
def update_character_profession(
    character_id: int,
    body: CharacterProfessionPick,
    user: dict = CurrentUser,
) -> Character:
    """Set (or clear, when slug is null) the character's profession.

    Mirrors the race PUT: slug-keyed, returns the freshened Character.
    """
    # Imported here to avoid circular-ish wiring; profession lookup belongs
    # to core.chargen but doesn't need to leak into the top-of-file imports.
    from core.chargen.profession import get_profession_by_slug

    now = _utcnow()
    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])
        if body.slug is None:
            profession_id = None
        else:
            prof = get_profession_by_slug(conn, body.slug)
            if prof is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Unknown profession slug: {body.slug!r}",
                )
            profession_id = prof["profession_id"]
        conn.execute(
            "UPDATE character SET profession_id = ?, updated_at = ? "
            "WHERE character_id = ?",
            (profession_id, now, character_id),
        )
        row = conn.execute(
            f"{_CHARACTER_SELECT} WHERE ch.character_id = ?",
            (character_id,),
        ).fetchone()
        conn.commit()
    return _row_to_character(row)


# ---------------------------------------------------------------------------
# Skill allocator (RMSS Character Law §6 — DP allocation) + TP market
# ---------------------------------------------------------------------------

class SkillRow(BaseModel):
    """One leaf skill under a category.

    Per RMSS, stat bonuses and profession bonuses apply at the CATEGORY
    level only — they're already folded into the parent category's
    total_bonus, which cascades into the skill total below. Skill rows
    therefore don't carry stat / class fields; they only carry the
    skill-specific layers (item + special) that the category total
    doesn't already include.

    skill_total = skill_rank_bonus + category_total
                + item_bonus + special_bonus
    """
    skill_name: str
    ranks_bought: int = 0
    dp_spent: int = 0
    next_rank_cost_dp: int | None = None
    # Total ranks from ALL sources (DP purchase + adolescence + hobby
    # + TP-granted). At chargen with only DP purchases this equals
    # ranks_bought, but it lets the SPA distinguish "ranks the player
    # already has" from "additional ranks they buy this level".
    current_ranks: int = 0
    # Skill-specific layers — both 0 today, layered later:
    #   item_bonus    = magical items, etc. (a +5 sword's contribution)
    #   special_bonus = TP / racial talents / other GM-granted bonuses
    item_bonus: int = 0
    special_bonus: int = 0
    total_bonus: int = 0


class SkillCategoryRow(BaseModel):
    """One skill category — Weapon/1-H Edged, Athletic/Brawn, etc."""
    group_name: str
    category_name: str
    classification: str | None = None
    cost: str
    rank_cap_per_level: int
    # Stat codes that drive the category's stat bonus, slash-separated
    # ("St/Co/Ag"). Surfaced verbatim so the SPA can render the column
    # showing WHICH stats contribute; the computed integer goes in
    # stat_bonus below. Empty string when the category has no stat
    # bonus (e.g. Body Development).
    stat_bonuses: str = ""
    ranks_bought: int = 0
    dp_spent: int = 0
    next_rank_cost_dp: int | None = None
    # Same conventions as SkillRow.
    current_ranks: int = 0
    stat_bonus: int = 0
    class_bonus: int = 0
    special_bonus: int = 0
    total_bonus: int = 0
    # Rank progression string ("Standard", "Combined", "Limited",
    # "Special", or a dotted form like "0 • 7 • 5 • 3 • 1"). The SPA
    # uses this to compute the rank-bonus locally for the live
    # recompute on +/- click — so totals update without waiting for
    # the server round-trip.
    category_progression: str = ""
    skill_progression: str = ""
    skills: list[SkillRow] = []


class TrainingPackagePurchase(BaseModel):
    slug: str
    name: str
    dp_paid: int
    purchased_at: str


class TrainingPackageOption(BaseModel):
    slug: str
    name: str
    category: str
    source: str
    effective_cost: int
    affordable: bool


class DPBudget(BaseModel):
    dp_total: int
    dp_spent: int
    dp_remaining: int


class SkillAllocatorResponse(BaseModel):
    budget: DPBudget
    categories: list[SkillCategoryRow]
    training_packages_purchased: list[TrainingPackagePurchase]


class CategoryRanksUpdate(BaseModel):
    group_name: str = Field(..., min_length=1)
    category_name: str = Field(..., min_length=1)
    ranks_bought: int = Field(..., ge=0, le=50)


class SkillRanksUpdate(BaseModel):
    group_name: str = Field(..., min_length=1)
    category_name: str = Field(..., min_length=1)
    skill_name: str = Field(..., min_length=1)
    ranks_bought: int = Field(..., ge=0, le=50)


def _load_character_raw_temps(
    conn: sqlite3.Connection, character_id: int,
) -> dict:
    rows = conn.execute(
        "SELECT stat_code, temp FROM character_stat WHERE character_id = ?",
        (character_id,),
    ).fetchall()
    return {r["stat_code"]: int(r["temp"]) for r in rows}


def _effective_cost_for_category(
    conn: sqlite3.Connection,
    character_id: int,
    profession_id: int | None,
    profession_costs: dict[tuple[str, str], str],
    group_name: str,
    category_name: str,
) -> str:
    """Effective cost string for a category. Weapon categories honour the
    character's reassignment overrides; everything else flows from
    profession_category_cost as-is. Returns "" when untrainable."""
    if group_name == "Weapon" and profession_id is not None:
        eff = effective_weapon_costs(conn, character_id, profession_id)
        if category_name in eff:
            return eff[category_name]
    return profession_costs.get((group_name, category_name), "")


def _build_skill_allocator(
    conn: sqlite3.Connection, character_id: int,
) -> SkillAllocatorResponse:
    """Snapshot every category + skill with current purchases + bonuses.

    Driven by `profession_category_cost` rather than the skill catalog —
    the cost table is the authoritative list of what the player can
    actually train, and its vocabulary (group_name / category_name) is
    the one cost lookups need. For each cost row we JOIN to the catalog
    by category name to enrich with rank progression / stat bonuses /
    leaf skills, but cost rows without a catalog match still surface
    (e.g. profession's "Spells • Own Realm Closed Lists" — purchasable
    but the skill catalog doesn't enumerate it).

    A second pass appends skill_category rows that the profession has
    NO cost for ("untrainable" — restricted, professionally locked).
    Those carry the catalog's progression metadata but cost="" so the
    SPA can grey them out and the buy endpoints reject them.
    """
    from core.chargen.skills import (
        category_purchase_state, skill_purchase_state, total_dp_spent,
        progression_bonus, standard_skill_bonus, standard_category_bonus,
        stat_bonus_for, parse_stat_codes, rank_cap_per_level,
        dp_for_rank, find_skill_catalog_match, list_skills_in_skill_category,
        profession_category_costs, profession_category_bonuses,
        profession_group_bonuses,
    )
    from core.chargen.stats import basic_stat_bonus, development_points

    raw_temps = _load_character_raw_temps(conn, character_id)
    dp_total = development_points(raw_temps) if raw_temps else 0
    dp_spent = total_dp_spent(conn, character_id, level=1)

    prof_id = _load_character_profession_id(conn, character_id)
    prof_costs = profession_category_costs(conn, prof_id) if prof_id else {}
    cat_bonuses = profession_category_bonuses(conn, prof_id) if prof_id else {}
    grp_bonuses = profession_group_bonuses(conn, prof_id) if prof_id else {}

    cat_state = category_purchase_state(conn, character_id, level=1)
    skill_state = skill_purchase_state(conn, character_id, level=1)

    # Ranks already on the character from non-DP sources — adolescence
    # apply, TP grants (source='tp:<slug>'), future hobby ranks. Summed
    # across sources: a character_skill with two rows for "Climbing"
    # (adolescence:5 + tp:my_tp:1) yields current_ranks 6.
    skill_other_ranks: dict[str, int] = {}
    category_other_ranks: dict[str, int] = {}
    for r in conn.execute(
        "SELECT skill, kind, SUM(rank) AS rank FROM character_skill "
        "WHERE character_id = ? GROUP BY skill, kind",
        (character_id,),
    ).fetchall():
        if r["kind"] == "category":
            category_other_ranks[r["skill"]] = int(r["rank"])
        else:
            skill_other_ranks[r["skill"]] = int(r["rank"])

    out_categories: list[SkillCategoryRow] = []
    seen_keys: set[tuple[str, str]] = set()

    def emit_category_row(
        group: str, cat_short: str, cost: str,
        catalog: dict | None,
    ) -> None:
        """Compose one SkillCategoryRow + its leaf skills.

        `catalog` is the skill_category row (from find_skill_catalog_match)
        — None when the profession has a cost for a category the catalog
        doesn't list (e.g. "Spells • Own Realm Closed Lists").
        """
        cat_buy = cat_state.get((group, cat_short),
                                 {"ranks_bought": 0, "dp_spent": 0})
        ranks = cat_buy["ranks_bought"]
        cap = rank_cap_per_level(cost)
        next_cost = dp_for_rank(cost, ranks + 1) if cost else None

        # Adolescence-applied and TP-granted category ranks land in
        # character_skill under "Group • Category". Sum them in.
        cat_label_for_lookup = f"{group} • {cat_short}"
        cat_other = category_other_ranks.get(cat_label_for_lookup, 0)
        cat_current_ranks = ranks + cat_other

        cat_prog = (catalog or {}).get("category_progression") or ""
        cat_stat_str = (catalog or {}).get("stat_bonuses") or ""

        # Bonus math uses TOTAL ranks (DP + applied), per RMSS.
        cat_rank_b = progression_bonus(
            cat_prog, standard_category_bonus, cat_current_ranks,
            is_category=True,
        )
        cat_stat_b = stat_bonus_for(cat_stat_str, raw_temps)
        class_b = cat_bonuses.get((group, cat_short), 0) + grp_bonuses.get(group, 0)
        special_b = 0   # race/TP/item bonuses to come in Phase C+
        cat_total = int(round(cat_rank_b + cat_stat_b + class_b + special_b))

        # Per-skill rows.
        leaves: list[SkillRow] = []
        skill_prog = (catalog or {}).get("rank_progression") or ""
        if catalog is not None:
            for sk in list_skills_in_skill_category(conn, catalog):
                sk_name = sk["name"]
                sk_buy = skill_state.get((group, cat_short, sk_name),
                                          {"ranks_bought": 0, "dp_spent": 0})
                sk_ranks = sk_buy["ranks_bought"]
                sk_other = skill_other_ranks.get(sk_name, 0)
                current_ranks = sk_ranks + sk_other
                sk_rank_b = progression_bonus(
                    skill_prog, standard_skill_bonus, current_ranks,
                )
                # RMSS: stat bonuses + profession bonuses apply at the
                # CATEGORY level only. The skill total cascades from
                # cat_total (which already has rank + stat + class +
                # special at the category level) and adds the skill-
                # specific layers — rank, item, special.
                sk_item_b = 0      # placeholder for magical items etc.
                sk_special_b = 0   # placeholder for per-skill TP / GM bonuses
                sk_total = int(round(sk_rank_b + cat_total
                                       + sk_item_b + sk_special_b))
                next_sk_cost = dp_for_rank(cost, sk_ranks + 1) if cost else None
                leaves.append(SkillRow(
                    skill_name=sk_name,
                    ranks_bought=sk_ranks,
                    current_ranks=current_ranks,
                    dp_spent=sk_buy["dp_spent"],
                    next_rank_cost_dp=next_sk_cost,
                    item_bonus=sk_item_b,
                    special_bonus=sk_special_b,
                    total_bonus=sk_total,
                ))

        out_categories.append(SkillCategoryRow(
            group_name=group,
            # Always use the profession-side spelling (the cost-table is
            # the source of truth for what's purchasable, and that
            # vocabulary is what the SPA's stripGroupPrefix expects).
            # The catalog's own spelling (e.g. "Communication" singular)
            # may differ; that's a display issue we don't surface here.
            category_name=f"{group} • {cat_short}",
            classification=(catalog or {}).get("classification"),
            cost=cost or "",
            rank_cap_per_level=cap,
            stat_bonuses=cat_stat_str,
            ranks_bought=ranks,
            current_ranks=cat_current_ranks,
            dp_spent=cat_buy["dp_spent"],
            next_rank_cost_dp=next_cost,
            stat_bonus=cat_stat_b,
            class_bonus=class_b,
            special_bonus=special_b,
            total_bonus=cat_total,
            category_progression=cat_prog,
            skill_progression=skill_prog,
            skills=leaves,
        ))
        seen_keys.add((group, cat_short))

    # Pass 1: every (group, category) the profession has a cost for.
    # Sort by group then category for stable output.
    for (group, cat_short), raw_cost in sorted(prof_costs.items()):
        cost = _effective_cost_for_category(
            conn, character_id, prof_id, prof_costs, group, cat_short,
        )
        catalog = find_skill_catalog_match(conn, group, cat_short)
        emit_category_row(group, cat_short, cost, catalog)

    # Pass 2: catalog categories the profession DOESN'T list — surfaced
    # as untrainable so the SPA can show them when its "Show categories
    # with no profession cost" toggle is on.
    from core.chargen.skills import list_skill_categories
    for sc in list_skill_categories(conn):
        # Re-derive (group, category_short) using the same alias logic
        # that find_skill_catalog_match uses, so this pass dedupes
        # against pass 1.
        parent = (sc.get("category_name") or "")
        # Pull parent_group from skill_category directly; the convenience
        # wrapper doesn't return it, so re-query.
        sc_row = conn.execute(
            "SELECT parent_group FROM skill_category WHERE name = ?",
            (sc.get("category_name") or "",),
        ).fetchone()
        pgrp = (sc_row["parent_group"] or "").strip() if sc_row else ""
        # Use skill_category_group.name when parent_group is empty/None.
        group = pgrp if pgrp and pgrp != "None" else sc.get("group_name") or ""
        # Apply alias forward (Craft → Crafts, Communication → Communications)
        # so we dedupe against profession_costs that use the plural form.
        from core.chargen.skills import _GROUP_ALIASES
        group = _GROUP_ALIASES.get(group, group)

        cat_label = sc.get("category_name") or ""
        prefix = group + " • "
        cat_short = cat_label[len(prefix):] if cat_label.startswith(prefix) else cat_label
        if (group, cat_short) in seen_keys:
            continue
        emit_category_row(group, cat_short, "", sc)

    tp_rows = conn.execute(
        "SELECT ctp.training_package_slug AS slug, tp.name, "
        "       ctp.dp_paid, ctp.purchased_at "
        "FROM character_training_package ctp "
        "LEFT JOIN training_package tp "
        "  ON tp.slug = ctp.training_package_slug "
        "WHERE ctp.character_id = ? "
        "ORDER BY ctp.purchased_at",
        (character_id,),
    ).fetchall()
    tps = [
        TrainingPackagePurchase(
            slug=r["slug"],
            name=r["name"] or r["slug"],
            dp_paid=int(r["dp_paid"]),
            purchased_at=r["purchased_at"],
        ) for r in tp_rows
    ]

    return SkillAllocatorResponse(
        budget=DPBudget(
            dp_total=dp_total,
            dp_spent=dp_spent,
            dp_remaining=dp_total - dp_spent,
        ),
        categories=out_categories,
        training_packages_purchased=tps,
    )


@router.get("/{character_id}/skill-allocator",
            response_model=SkillAllocatorResponse)
def get_character_skill_allocator(
    character_id: int,
    user: dict = CurrentUser,
) -> SkillAllocatorResponse:
    """Snapshot of every category + skill: ranks bought, DP spent, total
    bonus computed, per-rank cost, and the character's DP budget."""
    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])
        return _build_skill_allocator(conn, character_id)


@router.put("/{character_id}/category-ranks",
            response_model=SkillAllocatorResponse)
def update_character_category_ranks(
    character_id: int,
    body: CategoryRanksUpdate,
    user: dict = CurrentUser,
) -> SkillAllocatorResponse:
    """Set the character's category ranks for the current level (=1 at chargen)."""
    from core.chargen.skills import (
        cumulative_cost, profession_category_costs, rank_cap_per_level,
    )

    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])
        prof_id = _load_character_profession_id(conn, character_id)
        if prof_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Pick a profession before buying category ranks.",
            )
        prof_costs = profession_category_costs(conn, prof_id)
        cost = _effective_cost_for_category(
            conn, character_id, prof_id, prof_costs,
            body.group_name, body.category_name,
        )
        if not cost:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Category {body.group_name}/{body.category_name} "
                       "is not in this profession's cost table.",
            )
        cap = rank_cap_per_level(cost)
        if body.ranks_bought > cap:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"At most {cap} rank(s)/level for cost '{cost}'.",
            )
        dp_spent = cumulative_cost(cost, body.ranks_bought) or 0
        conn.execute(
            "INSERT INTO character_category_purchase "
            "(character_id, group_name, category_name, level, ranks_bought, dp_spent) "
            "VALUES (?, ?, ?, 1, ?, ?) "
            "ON CONFLICT(character_id, group_name, category_name, level) "
            "DO UPDATE SET ranks_bought = excluded.ranks_bought, "
            "              dp_spent     = excluded.dp_spent",
            (character_id, body.group_name, body.category_name,
             body.ranks_bought, dp_spent),
        )
        conn.execute(
            "UPDATE character SET updated_at = ? WHERE character_id = ?",
            (_utcnow(), character_id),
        )
        conn.commit()
        return _build_skill_allocator(conn, character_id)


@router.put("/{character_id}/skill-ranks",
            response_model=SkillAllocatorResponse)
def update_character_skill_ranks(
    character_id: int,
    body: SkillRanksUpdate,
    user: dict = CurrentUser,
) -> SkillAllocatorResponse:
    """Set a per-skill rank count (level 1). Skill ranks use the SAME cost
    table as their parent category — RMSS lets you spend DP on either
    the category as a whole or on specific skills inside it."""
    from core.chargen.skills import (
        cumulative_cost, profession_category_costs, rank_cap_per_level,
    )

    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])
        prof_id = _load_character_profession_id(conn, character_id)
        if prof_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Pick a profession before buying skill ranks.",
            )
        prof_costs = profession_category_costs(conn, prof_id)
        cost = _effective_cost_for_category(
            conn, character_id, prof_id, prof_costs,
            body.group_name, body.category_name,
        )
        if not cost:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="That category isn't in the profession's cost table.",
            )
        cap = rank_cap_per_level(cost)
        if body.ranks_bought > cap:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"At most {cap} rank(s)/level for cost '{cost}'.",
            )
        dp_spent = cumulative_cost(cost, body.ranks_bought) or 0
        conn.execute(
            "INSERT INTO character_skill_purchase "
            "(character_id, group_name, category_name, skill_name, level, "
            " ranks_bought, dp_spent) "
            "VALUES (?, ?, ?, ?, 1, ?, ?) "
            "ON CONFLICT(character_id, group_name, category_name, skill_name, level) "
            "DO UPDATE SET ranks_bought = excluded.ranks_bought, "
            "              dp_spent     = excluded.dp_spent",
            (character_id, body.group_name, body.category_name, body.skill_name,
             body.ranks_bought, dp_spent),
        )
        conn.execute(
            "UPDATE character SET updated_at = ? WHERE character_id = ?",
            (_utcnow(), character_id),
        )
        conn.commit()
        return _build_skill_allocator(conn, character_id)


class TrainingPackagesAvailableResponse(BaseModel):
    options: list[TrainingPackageOption]
    purchased_slugs: list[str]
    dp_remaining: int


@router.get("/{character_id}/training-packages-available",
            response_model=TrainingPackagesAvailableResponse)
def get_character_training_packages_available(
    character_id: int,
    user: dict = CurrentUser,
) -> TrainingPackagesAvailableResponse:
    """List every training package + the effective DP cost for this character.

    Effective cost = the per-profession cost from
    `training_package_profession_cost` if there's a row for the
    character's profession, else the TP's `default_cost`."""
    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])

        snap = _build_skill_allocator(conn, character_id)
        purchased = {tp.slug for tp in snap.training_packages_purchased}
        dp_remaining = snap.budget.dp_remaining

        prof_row = conn.execute(
            "SELECT p.name FROM character ch "
            "LEFT JOIN profession p ON p.profession_id = ch.profession_id "
            "WHERE ch.character_id = ?",
            (character_id,),
        ).fetchone()
        prof_name = prof_row[0] if prof_row else None

        tp_rows = conn.execute(
            "SELECT tp.slug, tp.name, tp.category, tp.source, tp.default_cost, "
            "       tpc.cost AS prof_cost "
            "  FROM training_package tp "
            "  LEFT JOIN training_package_profession_cost tpc "
            "    ON tpc.training_package_id = tp.training_package_id "
            "       AND tpc.profession_name = ? "
            " ORDER BY tp.name",
            (prof_name,),
        ).fetchall()
        options: list[TrainingPackageOption] = []
        for r in tp_rows:
            eff = r["prof_cost"] if r["prof_cost"] is not None else r["default_cost"]
            eff_int = int(eff) if eff is not None else 999
            options.append(TrainingPackageOption(
                slug=r["slug"],
                name=r["name"],
                category=r["category"] or "",
                source=r["source"] or "character_law",
                effective_cost=eff_int,
                affordable=(eff_int <= dp_remaining),
            ))
        return TrainingPackagesAvailableResponse(
            options=options,
            purchased_slugs=sorted(purchased),
            dp_remaining=dp_remaining,
        )


@router.post("/{character_id}/training-packages/{slug}",
             response_model=SkillAllocatorResponse,
             status_code=status.HTTP_201_CREATED)
def purchase_character_training_package(
    character_id: int,
    slug: str,
    user: dict = CurrentUser,
) -> SkillAllocatorResponse:
    """Buy a training package. Pays the per-profession cost (or default_cost
    when the profession isn't in the TP's cost table)."""
    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])
        prof_id = _load_character_profession_id(conn, character_id)
        if prof_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Pick a profession before buying training packages.",
            )
        tp_row = conn.execute(
            "SELECT training_package_id, name, default_cost "
            "  FROM training_package WHERE slug = ?",
            (slug,),
        ).fetchone()
        if tp_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown training package: {slug!r}",
            )
        existing = conn.execute(
            "SELECT 1 FROM character_training_package "
            "WHERE character_id = ? AND training_package_slug = ?",
            (character_id, slug),
        ).fetchone()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Training package already purchased.",
            )
        prof_name_row = conn.execute(
            "SELECT name FROM profession WHERE profession_id = ?",
            (prof_id,),
        ).fetchone()
        prof_name = prof_name_row[0] if prof_name_row else None
        cost_row = conn.execute(
            "SELECT cost FROM training_package_profession_cost "
            "WHERE training_package_id = ? AND profession_name = ?",
            (tp_row["training_package_id"], prof_name),
        ).fetchone()
        eff_cost = int(cost_row["cost"]) if cost_row else int(tp_row["default_cost"])

        now = _utcnow()
        conn.execute(
            "INSERT INTO character_training_package "
            "(character_id, training_package_slug, dp_paid, purchased_at) "
            "VALUES (?, ?, ?, ?)",
            (character_id, slug, eff_cost, now),
        )
        _apply_tp_rank_grants(
            conn, character_id, tp_row["training_package_id"], slug,
        )
        conn.execute(
            "UPDATE character SET updated_at = ? WHERE character_id = ?",
            (now, character_id),
        )
        conn.commit()
        return _build_skill_allocator(conn, character_id)


def _apply_tp_rank_grants(
    conn: sqlite3.Connection,
    character_id: int,
    training_package_id: int,
    slug: str,
) -> None:
    """Write character_skill rows for the TP's rank assignments.

    For each FIXED assignment (reference_label is None, group/category
    set), we write a category-rank row + a skill-rank row (when the
    assignment lists exactly one skill_option). FLEXIBLE assignments
    (reference_label set — "Melee Weapon", etc.) need a player pick
    and are skipped here; a follow-up will surface them in the SPA.

    All grants share the source tag f'tp:{slug}', which the refund
    endpoint uses to wipe them cleanly when the TP is un-bought.
    """
    src = f"tp:{slug}"
    ras = conn.execute(
        "SELECT sort_order, reference_label, group_name, category_name, "
        "       cat_ranks, skill_ranks "
        "  FROM training_package_rank_assignment "
        " WHERE training_package_id = ? "
        " ORDER BY sort_order",
        (training_package_id,),
    ).fetchall()
    for ra in ras:
        if ra["reference_label"] is not None:
            # Flexible — player needs to pick a category. Defer.
            continue
        group = ra["group_name"]
        cat = ra["category_name"]
        if not group or not cat:
            continue
        cat_ranks = int(ra["cat_ranks"] or 0)
        skill_ranks = int(ra["skill_ranks"] or 0)
        if cat_ranks > 0:
            cat_label = f"{group} • {cat}"
            conn.execute(
                "INSERT INTO character_skill "
                "(character_id, skill, kind, rank, source) "
                "VALUES (?, ?, 'category', ?, ?) "
                "ON CONFLICT (character_id, kind, skill, source) "
                "DO UPDATE SET rank = excluded.rank",
                (character_id, cat_label, cat_ranks, src),
            )
        if skill_ranks > 0:
            # Skill ranks land on the assignment's listed skill_options.
            # When there's exactly one option we apply automatically;
            # multi-option distribution needs a player pick we'll add
            # in a follow-up.
            opts = conn.execute(
                "SELECT skill_name FROM training_package_ra_skill_option "
                "WHERE training_package_id = ? AND sort_order = ?",
                (training_package_id, ra["sort_order"]),
            ).fetchall()
            if len(opts) == 1:
                conn.execute(
                    "INSERT INTO character_skill "
                    "(character_id, skill, kind, rank, source) "
                    "VALUES (?, ?, 'skill', ?, ?) "
                    "ON CONFLICT (character_id, kind, skill, source) "
                    "DO UPDATE SET rank = excluded.rank",
                    (character_id, opts[0]["skill_name"], skill_ranks, src),
                )
            # else: ambiguous — leave for a future picker UI


@router.delete("/{character_id}/training-packages/{slug}",
               response_model=SkillAllocatorResponse)
def refund_character_training_package(
    character_id: int,
    slug: str,
    user: dict = CurrentUser,
) -> SkillAllocatorResponse:
    """Refund a previously-purchased TP. The DP comes back into the budget."""
    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])
        existing = conn.execute(
            "SELECT 1 FROM character_training_package "
            "WHERE character_id = ? AND training_package_slug = ?",
            (character_id, slug),
        ).fetchone()
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Training package not in this character's purchases.",
            )
        conn.execute(
            "DELETE FROM character_training_package "
            "WHERE character_id = ? AND training_package_slug = ?",
            (character_id, slug),
        )
        # Wipe the rank grants this TP made (tagged source = 'tp:<slug>').
        # Other sources (adolescence, other TPs) on the same skills are
        # left alone.
        conn.execute(
            "DELETE FROM character_skill "
            "WHERE character_id = ? AND source = ?",
            (character_id, f"tp:{slug}"),
        )
        conn.execute(
            "UPDATE character SET updated_at = ? WHERE character_id = ?",
            (_utcnow(), character_id),
        )
        conn.commit()
        return _build_skill_allocator(conn, character_id)
