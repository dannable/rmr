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


class CharacterCreate(BaseModel):
    # Name is the only required field for now. Everything else is derived
    # from defaults until the chargen wizard fills it in.
    name: str = Field(..., min_length=1, max_length=80)


# ---- stats sub-resource ----

class StatRow(BaseModel):
    code: StatCode
    name: str
    temp: int
    potential: int
    basic_bonus: int  # computed from temp via T-2.1


class StatsRR(BaseModel):
    # Computed from temp stats; matches the labels on Character Record Sheet T-6.1.
    channeling: int
    essence: int
    mentalism: int
    chan_ess: int
    chan_ment: int
    ess_ment: int
    arcane: int
    poison_disease: int
    fear: int


class CharacterStats(BaseModel):
    stats: list[StatRow]
    resistance_rolls: StatsRR


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
    return Character(
        character_id=row["character_id"],
        owner_user_id=row["owner_user_id"],
        name=row["name"],
        level=row["level"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------

@router.get("", response_model=list[Character])
def list_characters(user: dict = CurrentUser) -> list[Character]:
    """List the current user's characters, newest first."""
    with connect_rw() as conn:
        rows = conn.execute(
            """
            SELECT character_id, owner_user_id, name, level, created_at, updated_at
              FROM character
             WHERE owner_user_id = ?
             ORDER BY created_at DESC
            """,
            (user["user_id"],),
        ).fetchall()
    return [_row_to_character(r) for r in rows]


@router.post("", response_model=Character, status_code=status.HTTP_201_CREATED)
def create_character(body: CharacterCreate, user: dict = CurrentUser) -> Character:
    """Create a blank character owned by the current user.

    Seeds the 10 RMSS stats at 50/50 (temp/potential), which gives a neutral
    +0 bonus across the board. The wizard's stats step lets the user pick
    actual values.
    """
    now = _utcnow()
    with connect_rw() as conn:
        cur = conn.execute(
            """
            INSERT INTO character (owner_user_id, name, level, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            RETURNING character_id, owner_user_id, name, level, created_at, updated_at
            """,
            (user["user_id"], body.name.strip(), now, now),
        )
        row = cur.fetchone()
        character_id = row["character_id"]
        conn.executemany(
            "INSERT INTO character_stat (character_id, stat_code, temp, potential) "
            "VALUES (?, ?, 50, 50)",
            [(character_id, code) for code in STAT_CODES],
        )
        conn.commit()
    return _row_to_character(row)


@router.get("/{character_id}", response_model=Character)
def get_character(character_id: int, user: dict = CurrentUser) -> Character:
    with connect_rw() as conn:
        row = conn.execute(
            """
            SELECT character_id, owner_user_id, name, level, created_at, updated_at
              FROM character
             WHERE character_id = ?
            """,
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


def _build_stats_payload(rows: list) -> CharacterStats:
    """Turn `character_stat` rows into the API payload, computing bonuses + RRs."""
    by_code: dict[StatCode, dict] = {r["stat_code"]: dict(r) for r in rows}
    stats = [
        StatRow(
            code=code,
            name=STAT_NAMES[code],
            temp=by_code[code]["temp"],
            potential=by_code[code]["potential"],
            basic_bonus=basic_stat_bonus(by_code[code]["temp"]),
        )
        for code in STAT_CODES
    ]
    temps = {code: by_code[code]["temp"] for code in STAT_CODES}
    rr = StatsRR(
        channeling=rr_bonus(temps, "Channeling"),
        essence=rr_bonus(temps, "Essence"),
        mentalism=rr_bonus(temps, "Mentalism"),
        chan_ess=rr_bonus(temps, "Chan/Ess"),
        chan_ment=rr_bonus(temps, "Chan/Ment"),
        ess_ment=rr_bonus(temps, "Ess/Ment"),
        arcane=rr_bonus(temps, "Arcane"),
        poison_disease=rr_bonus(temps, "Poison/Disease"),
        fear=rr_bonus(temps, "Fear"),
    )
    return CharacterStats(stats=stats, resistance_rolls=rr)


@router.get("/{character_id}/stats", response_model=CharacterStats)
def get_character_stats(character_id: int, user: dict = CurrentUser) -> CharacterStats:
    """Return the 10 stats for a character plus derived bonuses + RR totals."""
    with connect_rw() as conn:
        _assert_owned(conn, character_id, user["user_id"])
        rows = conn.execute(
            "SELECT stat_code, temp, potential FROM character_stat WHERE character_id = ?",
            (character_id,),
        ).fetchall()
    if len(rows) != len(STAT_CODES):
        # Legacy rows (pre-stats migration) — backfill defaults on the fly.
        # The CHECK constraint on stat_code guarantees we won't insert garbage.
        with connect_rw() as conn:
            _assert_owned(conn, character_id, user["user_id"])
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
    return _build_stats_payload(rows)


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
        conn.commit()
    return _build_stats_payload(rows)
