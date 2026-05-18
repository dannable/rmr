"""Character CRUD endpoints.

Day-1 scope is intentionally narrow: list, get, create-blank, delete.
The full chargen wizard (stats / race / profession / skills) layers on top
of these as separate PATCH endpoints per phase, per the original plan.

Every endpoint requires a logged-in user (CurrentUser) and ownership-scopes
characters by owner_user_id — there is no public/shared mode yet.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

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
    """Create a blank character owned by the current user."""
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
