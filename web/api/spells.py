"""Spell-explorer REST endpoints (browse + edit).

All routes require a logged-in user (CurrentUser). Reads are open to any
authenticated user, and per the design (any logged-in user can edit), the
PUT handler is also gated only by `current_user` — there's no separate
editor role yet.

The PUT handler is the interesting one. It does, in order:

  1. UPDATE the `spell` row in SQLite (uncommitted).
  2. Re-serialise the affected list's `data/spell_lists/<realm>/<slug>.txt`
     atomically via tempfile + os.replace.
  3. Commit the SQLite transaction.

If the file write fails, the DB is rolled back so the on-disk file stays
the source of truth. If the DB commit fails after a successful file write
(extremely unlikely with SQLite), the file is ahead of the DB — but the
next `load.py --reload-ref` cycle restores symmetry from the .txt file.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from core.spell import (
    EDITABLE_SPELL_FIELDS,
    classes_for_list,
    get_spell_by_list_id,
    list_classes,
    lists_for_class,
    search_spells,
    spells_on_list,
    update_spell,
    write_spell_list_file,
)

from ..auth.deps import CurrentUser
from ..db import connect_rw

router = APIRouter(prefix="/api/v1/spells", tags=["spells"])

# web/api/spells.py → web/api/ → web/ → project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------

class SpellClassRow(BaseModel):
    class_name: str
    realm_name: str


class SpellListRow(BaseModel):
    """One row in a list-of-lists view (no classes joined in)."""
    list_id: int
    name: str
    list_number: str
    category: str
    realm_name: str


class ClassListRow(BaseModel):
    """A list within one class's curriculum — no realm (it's implied by the class)."""
    name: str
    list_number: str
    category: str


class SpellListDetail(BaseModel):
    """A spell list with the classes that have access to it."""
    list_id: int
    name: str
    list_number: str
    category: str
    realm_name: str
    classes: list[str]


class SpellSummary(BaseModel):
    """Chart-row view of a spell — what shows on the list page."""
    level: int
    name: str
    area_effect: str | None = None
    duration: str | None = None
    range_str: str | None = None
    spell_type: str | None = None
    starred: bool = False


class Spell(BaseModel):
    """Full spell detail, including description and edit audit."""
    list_id: int
    list_name: str
    list_number: str
    category: str
    realm_name: str
    level: int
    name: str
    area_effect: str | None = None
    duration: str | None = None
    range_str: str | None = None
    spell_type: str | None = None
    starred: bool = False
    description: str | None = None
    updated_at: str | None = None
    updated_by_user_id: int | None = None


class SpellUpdate(BaseModel):
    """Partial edit payload. All fields optional; missing keys are unchanged."""
    name: str | None = Field(default=None, min_length=1, max_length=120)
    area_effect: str | None = None
    duration: str | None = None
    range_str: str | None = None
    spell_type: str | None = None
    description: str | None = None
    starred: bool | None = None


class SpellSearchHit(BaseModel):
    """Result row from the global-search endpoint."""
    level: int
    name: str
    spell_type: str | None = None
    list_name: str
    list_number: str
    category: str


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _spell_summary(row: dict) -> SpellSummary:
    return SpellSummary(
        level=row["level"],
        name=row["name"],
        area_effect=row.get("area_effect"),
        duration=row.get("duration"),
        range_str=row.get("range_str"),
        spell_type=row.get("spell_type"),
        starred=bool(row.get("starred")),
    )


def _spell(row: dict) -> Spell:
    return Spell(
        list_id=row["list_id"],
        list_name=row["list_name"],
        list_number=row["list_number"],
        category=row["category"],
        realm_name=row["realm_name"],
        level=row["level"],
        name=row["name"],
        area_effect=row.get("area_effect"),
        duration=row.get("duration"),
        range_str=row.get("range_str"),
        spell_type=row.get("spell_type"),
        starred=bool(row.get("starred")),
        description=row.get("description"),
        updated_at=row.get("updated_at"),
        updated_by_user_id=row.get("updated_by_user_id"),
    )


def _fetch_list_row(conn, list_id: int) -> dict | None:
    """Look up list metadata by list_id (vs core.spell.get_spell_list by name)."""
    row = conn.execute(
        """SELECT sl.list_id, sl.name, sl.list_number, sl.category,
                  sr.name AS realm_name
             FROM spell_list sl
             JOIN spell_realm sr ON sl.realm_id = sr.realm_id
            WHERE sl.list_id = ?""",
        (list_id,),
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# routes — classes
# ---------------------------------------------------------------------------

@router.get("/classes", response_model=list[SpellClassRow])
def get_classes(user: dict = CurrentUser) -> list[SpellClassRow]:
    """All caster classes, grouped (sorted) by realm then name."""
    with connect_rw() as conn:
        rows = list_classes(conn)
    return [SpellClassRow(**r) for r in rows]


@router.get("/classes/{class_name}/lists", response_model=list[ClassListRow])
def get_class_lists(class_name: str, user: dict = CurrentUser) -> list[ClassListRow]:
    """Spell lists accessible to one class, in canonical Base→Open→Closed order."""
    with connect_rw() as conn:
        rows = lists_for_class(conn, class_name)
    if not rows:
        # Empty result could mean "unknown class" OR "real class with no lists yet".
        # We currently load Channeling only, so any class outside that realm will
        # legitimately return []. Don't 404 — let the SPA show "no lists".
        return []
    return [ClassListRow(**r) for r in rows]


# ---------------------------------------------------------------------------
# routes — lists
# ---------------------------------------------------------------------------

@router.get("/lists", response_model=list[SpellListRow])
def get_lists(user: dict = CurrentUser) -> list[SpellListRow]:
    """All spell lists across all realms, sorted by list_number.

    `core.spell.list_spell_lists` doesn't include `list_id` (the bot only
    needs names + numbers); the SPA navigates by list_id, so we query
    directly here.
    """
    with connect_rw() as conn:
        rows = conn.execute(
            """SELECT sl.list_id, sl.name, sl.list_number, sl.category,
                      sr.name AS realm_name
                 FROM spell_list sl
                 JOIN spell_realm sr USING (realm_id)
                ORDER BY length(sl.list_number), sl.list_number"""
        ).fetchall()
    return [SpellListRow(**dict(r)) for r in rows]


@router.get("/lists/{list_id}", response_model=SpellListDetail)
def get_list(list_id: int, user: dict = CurrentUser) -> SpellListDetail:
    with connect_rw() as conn:
        meta = _fetch_list_row(conn, list_id)
        if meta is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spell list not found")
        classes = classes_for_list(conn, list_id)
    return SpellListDetail(**meta, classes=classes)


@router.get("/lists/{list_id}/spells", response_model=list[SpellSummary])
def get_list_spells(list_id: int, user: dict = CurrentUser) -> list[SpellSummary]:
    """All spells on one list (chart view — no descriptions)."""
    with connect_rw() as conn:
        meta = _fetch_list_row(conn, list_id)
        if meta is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spell list not found")
        rows = spells_on_list(conn, list_id)
    return [_spell_summary(r) for r in rows]


@router.get("/lists/{list_id}/spells/{level}", response_model=Spell)
def get_one_spell(list_id: int, level: int, user: dict = CurrentUser) -> Spell:
    """One spell, full detail including description + edit audit."""
    with connect_rw() as conn:
        row = get_spell_by_list_id(conn, list_id, level)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spell not found")
    return _spell(row)


@router.put("/lists/{list_id}/spells/{level}", response_model=Spell)
def edit_spell(
    list_id: int,
    level: int,
    body: SpellUpdate,
    user: dict = CurrentUser,
) -> Spell:
    """Edit one spell. Updates the DB row, then re-serialises the .txt file.

    Any logged-in user may edit; we record who via `updated_by_user_id`.
    The DB write and the file write are sequenced so the file is regenerated
    from post-update DB state, then the transaction commits. If the file
    write raises, the DB is rolled back so the .txt stays canonical.
    """
    # model_dump(exclude_unset=True) keeps unset keys out so update_spell only
    # touches what the client actually sent.
    fields = body.model_dump(exclude_unset=True)
    # Defence in depth: silently drop anything outside the allowed set.
    fields = {k: v for k, v in fields.items() if k in EDITABLE_SPELL_FIELDS}

    with connect_rw() as conn:
        updated = update_spell(
            conn,
            list_id=list_id,
            level=level,
            fields=fields,
            user_id=user["user_id"],
        )
        if updated is None:
            # Don't commit — the UPDATE matched zero rows but SQLite still
            # has an implicit txn open. Rollback is harmless.
            conn.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spell not found")
        try:
            write_spell_list_file(conn, list_id=list_id, project_root=_PROJECT_ROOT)
        except Exception:
            # File write failed — undo the DB change so the .txt remains
            # authoritative. Re-raise so the client gets a 500.
            conn.rollback()
            raise
        conn.commit()
    return _spell(updated)


# ---------------------------------------------------------------------------
# routes — search
# ---------------------------------------------------------------------------

@router.get("/search", response_model=list[SpellSearchHit])
def search(
    q: str = Query(..., min_length=1, max_length=80, description="Substring of spell name"),
    limit: int = Query(25, ge=1, le=100),
    user: dict = CurrentUser,
) -> list[SpellSearchHit]:
    with connect_rw() as conn:
        rows = search_spells(conn, q, limit=limit)
    return [SpellSearchHit(**r) for r in rows]
