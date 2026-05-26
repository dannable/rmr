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
    get_race_by_id,
    get_race_by_slug,
    race_stat_mods,
    race_rr_mods,
    apply_stat_mods,
)
from core.chargen.adolescence import grouped_ranks, adolescence_ranks
from core.chargen.weapons import (
    category_for_t16_row,
    filter_race_weapons_by_category,
    all_race_weapons,
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


class CharacterCreate(BaseModel):
    # Name is the only required field for now. Everything else is derived
    # from defaults until the chargen wizard fills it in.
    name: str = Field(..., min_length=1, max_length=80)


class CharacterRacePick(BaseModel):
    # Pass null to clear the character's race. `slug` is preferred over
    # race_id because slugs are stable across `load.py --reset` runs.
    slug: str | None = None


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
    race_mod: int = 0      # Race modifier from T-1.1, 0 when no race set.
    basic_bonus: int       # T-2.1 bonus computed from (temp + race_mod).
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
    # Race join columns are nullable — the LEFT JOIN may return Nones, or
    # an older read path may not have them in the row at all.
    def _opt(key: str):
        try:
            return row[key]
        except (KeyError, IndexError):
            return None
    return Character(
        character_id=row["character_id"],
        owner_user_id=row["owner_user_id"],
        name=row["name"],
        level=row["level"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        race_id=_opt("race_id"),
        race_slug=_opt("race_slug"),
        race_name=_opt("race_name"),
        profession_id=_opt("profession_id"),
        profession_slug=_opt("profession_slug"),
        profession_name=_opt("profession_name"),
    )


# Reusable SELECT clauses; the race + profession joins are LEFT so an
# unraced / unprofessioned character still comes back with NULLs for the
# joined columns.
_CHARACTER_SELECT = """
    SELECT ch.character_id, ch.owner_user_id, ch.name, ch.level,
           ch.created_at, ch.updated_at, ch.race_id, ch.profession_id,
           r.slug AS race_slug, r.name AS race_name,
           p.slug AS profession_slug, p.name AS profession_name
      FROM character ch
      LEFT JOIN race r ON r.race_id = ch.race_id
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

    When `race` is provided, race stat mods are folded into the effective
    temp before the T-2.1 basic-stat bonus is computed, and race RR mods
    are added to each RR total. When None, behaviour matches the pre-race
    version exactly (race_mod=0, no RR mod).

    `prime_stats` (the profession's primes, by 2-letter code) tags the
    StatRows for the SPA's "prime stats need ≥90" check.
    """
    from core.chargen.stats import stat_cost, total_stat_cost, TEMP_STAT_BUDGET, PRIME_STAT_MIN

    by_code: dict[StatCode, dict] = {r["stat_code"]: dict(r) for r in rows}
    stat_mods = race_stat_mods(race)
    rr_mods = race_rr_mods(race)

    raw_temps = {code: by_code[code]["temp"] for code in STAT_CODES}
    eff_temps = apply_stat_mods(raw_temps, race)

    primes_set = set(prime_stats or [])
    stats = [
        StatRow(
            code=code,
            name=STAT_NAMES[code],
            temp=by_code[code]["temp"],
            potential=by_code[code]["potential"],
            race_mod=stat_mods[code],
            basic_bonus=basic_stat_bonus(eff_temps[code]),
            temp_cost=stat_cost(by_code[code]["temp"]),
            is_prime=(code in primes_set),
        )
        for code in STAT_CODES
    ]
    rr = StatsRR(
        channeling=rr_bonus(eff_temps, "Channeling")        + rr_mods["channeling"],
        essence=rr_bonus(eff_temps, "Essence")              + rr_mods["essence"],
        mentalism=rr_bonus(eff_temps, "Mentalism")          + rr_mods["mentalism"],
        chan_ess=rr_bonus(eff_temps, "Chan/Ess")            + rr_mods["chan_ess"],
        chan_ment=rr_bonus(eff_temps, "Chan/Ment")          + rr_mods["chan_ment"],
        ess_ment=rr_bonus(eff_temps, "Ess/Ment")            + rr_mods["ess_ment"],
        arcane=rr_bonus(eff_temps, "Arcane")                + rr_mods["arcane"],
        poison_disease=rr_bonus(eff_temps, "Poison/Disease") + rr_mods["poison_disease"],
        fear=rr_bonus(eff_temps, "Fear")                     + rr_mods["fear"],
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

    Each row carries per-row metadata identifying whether the player must
    pick a specifier before the rank can be applied — `choice_kind` is
    "text" (free input) or "select" (dropdown), with `choice_options`
    populated for selects and `choice` reflecting the player's saved pick.
    """
    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])
        race = _load_character_race(conn, character_id)
        if race is None:
            return CharacterAdolescence(culture_slug=None, culture_name=None, groups=[])
        # Pull the race's weapons text out of culture_data for the
        # dropdown options.
        import json
        weapons_text = ""
        try:
            cd = json.loads(race.get("culture_data") or "{}")
            if isinstance(cd, dict):
                weapons_text = cd.get("weapons", "") or ""
        except (TypeError, ValueError):
            pass
        groups = grouped_ranks(conn, race["slug"])
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
        culture_slug=race["slug"],
        culture_name=race["name"],
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
        rows = adolescence_ranks(conn, race["slug"])
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
            if r["kind"] != "leaf":
                # Categories don't become character_skill rows directly;
                # they're aggregate counters for the DP allocator.
                continue
            try:
                rank = int(r["value"])
            except ValueError:
                # "Hobby Ranks" etc. have non-integer values; skip here.
                continue
            if rank <= 0:
                continue
            resolved = _resolved_skill_name(r["skill"], choice_by_row.get(r["skill"]))
            if resolved is None:
                skipped.append(r["skill"])
                continue
            conn.execute(
                "INSERT INTO character_skill (character_id, skill, rank, source) "
                "VALUES (?, ?, ?, 'adolescence') ON CONFLICT(character_id, skill) "
                "DO UPDATE SET rank = excluded.rank, source = excluded.source",
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
    don't lose their race if reference data is rebuilt. Returns the updated
    Character (with race fields populated).
    """
    now = _utcnow()
    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])
        if body.slug is None:
            race_id = None
        else:
            race = get_race_by_slug(conn, body.slug)
            if race is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Unknown race slug: {body.slug!r}",
                )
            race_id = race["race_id"]
        conn.execute(
            "UPDATE character SET race_id = ?, updated_at = ? WHERE character_id = ?",
            (race_id, now, character_id),
        )
        row = conn.execute(
            f"{_CHARACTER_SELECT} WHERE ch.character_id = ?",
            (character_id,),
        ).fetchone()
        conn.commit()
    return _row_to_character(row)


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
