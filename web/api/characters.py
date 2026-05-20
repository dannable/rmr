"""Character CRUD endpoints.

Routes here cover the "skeleton" of a character — list/create/view/delete —
plus the first wizard step (stats). The chargen wizard's later steps
(race / profession / skills / spells / outfit) layer on top as additional
nested resources following the same shape.

Every endpoint requires a logged-in user (CurrentUser) and ownership-scopes
characters by owner_user_id — there is no public/shared mode yet.
"""

from __future__ import annotations

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
    # Chargen progress. NULL until the picker is used. `race_name` is denormalised
    # in the response so the client can label without a second fetch.
    race_id: int | None = None
    race_slug: str | None = None
    race_name: str | None = None


class CharacterCreate(BaseModel):
    # Name is the only required field for now. Everything else is derived
    # from defaults until the chargen wizard fills it in.
    name: str = Field(..., min_length=1, max_length=80)


class CharacterRacePick(BaseModel):
    # Pass null to clear the character's race. `slug` is preferred over
    # race_id because slugs are stable across `load.py --reset` runs.
    slug: str | None = None


# ---- stats sub-resource ----

class StatRow(BaseModel):
    code: StatCode
    name: str
    temp: int
    potential: int
    race_mod: int = 0      # Race modifier from T-1.1, 0 when no race set.
    basic_bonus: int       # T-2.1 bonus computed from (temp + race_mod).


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


class CharacterStats(BaseModel):
    stats: list[StatRow]
    resistance_rolls: StatsRR
    race: StatsRaceInfo | None = None


class StatUpdate(BaseModel):
    code: StatCode
    temp: int = Field(..., ge=1, le=102)
    potential: int = Field(..., ge=1, le=102)


class CharacterStatsUpdate(BaseModel):
    stats: list[StatUpdate] = Field(..., min_length=10, max_length=10)


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
    )


# Reusable SELECT clauses; the race join is LEFT so unraced characters still
# come back with `race_*` columns set to NULL.
_CHARACTER_SELECT = """
    SELECT ch.character_id, ch.owner_user_id, ch.name, ch.level,
           ch.created_at, ch.updated_at, ch.race_id,
           r.slug AS race_slug, r.name AS race_name
      FROM character ch
      LEFT JOIN race r ON r.race_id = ch.race_id
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


def _build_stats_payload(rows: list, race: dict | None = None) -> CharacterStats:
    """Turn `character_stat` rows into the API payload.

    When `race` is provided, race stat mods are folded into the effective
    temp before the T-2.1 basic-stat bonus is computed, and race RR mods
    are added to each RR total. When None, behaviour matches the pre-race
    version exactly (race_mod=0, no RR mod).
    """
    by_code: dict[StatCode, dict] = {r["stat_code"]: dict(r) for r in rows}
    stat_mods = race_stat_mods(race)
    rr_mods = race_rr_mods(race)

    raw_temps = {code: by_code[code]["temp"] for code in STAT_CODES}
    eff_temps = apply_stat_mods(raw_temps, race)

    stats = [
        StatRow(
            code=code,
            name=STAT_NAMES[code],
            temp=by_code[code]["temp"],
            potential=by_code[code]["potential"],
            race_mod=stat_mods[code],
            basic_bonus=basic_stat_bonus(eff_temps[code]),
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
    return CharacterStats(stats=stats, resistance_rolls=rr, race=race_info)


def _load_character_race(conn: sqlite3.Connection, character_id: int) -> dict | None:
    """Look up the character's race row (or None if unraced / unknown char)."""
    row = conn.execute(
        "SELECT race_id FROM character WHERE character_id = ?",
        (character_id,),
    ).fetchone()
    if row is None or row["race_id"] is None:
        return None
    return get_race_by_id(conn, row["race_id"])


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
    return _build_stats_payload(rows, race=race)


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
        conn.commit()
    return _build_stats_payload(rows, race=race)


# ---------------------------------------------------------------------------
# race sub-resource
# ---------------------------------------------------------------------------

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
