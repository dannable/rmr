"""Skills catalog endpoints (RMSS Appendix A-1).

Read endpoints surface the catalog loaded from data/skills/*.txt by
load.py. The PUT endpoint lets any logged-in user fix extraction errors
by editing the whole group payload (categories + skills + tables) at
once; on save we wipe + re-insert the group's children and then re-
serialise data/skills/<slug>.txt so the on-disk source-of-truth stays
in sync (same pattern as the spells edit handler).

Routes:
    GET /api/v1/skills                       — list all 34 groups
    GET /api/v1/skills/{slug}                — one group + categories + skills + tables
    PUT /api/v1/skills/{slug}                — replace the group's editable contents
    GET /api/v1/skills/search?q=<substring>  — skill-name search
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from core.skills import (
    get_skill_group,
    list_skill_groups,
    search_skills,
    update_skill_group,
    write_skill_group_file,
)

from ..auth.deps import CurrentUser
from ..db import connect_rw

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])

# web/api/skills.py → web/api/ → web/ → project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------

class SkillGroupRow(BaseModel):
    slug: str
    section: str
    name: str
    page_div: int
    page_content: int


class SkillCategory(BaseModel):
    name: str
    skills_list: str | None = None
    restricted: str | None = None
    stat_bonuses: str | None = None
    rank_progression: str | None = None
    category_progression: str | None = None
    parent_group: str | None = None
    classification: str | None = None
    description: str | None = None
    # Category-specific notes from "School of Hard Knocks" (book 5808).
    # Currently always empty — SOHK's Section 5 prose lives at the
    # group level on SkillGroupDetail.sohk_notes. Reserved for future
    # category-specific notes (e.g. if SOHK adds Section 5.X.Y in a
    # later edition).
    sohk_notes: str = ""


class SOHKData(BaseModel):
    """Per-skill supplemental data from "School of Hard Knocks". Empty
    fields mean SOHK either doesn't address that aspect of this skill
    or doesn't elaborate this skill at all (the 4 placeholder umbrella
    skills — Armor / Weapon / Spells / etc. — get an all-empty payload).
    """
    optional_stats: str = ""           # e.g. "Ag/Qu/Ag"
    ep_cost: str = ""                  # e.g. "1 every 6 rounds"
    distance_multiplier: str = ""      # e.g. "1"
    notes: str = ""                    # GM-facing maneuver-resolution prose
    specialties: list[str] = []
    example_difficulties: dict[str, str] = {}


class Skill(BaseModel):
    name: str
    stat: str | None = None
    description: str | None = None
    sohk_data: SOHKData = SOHKData()


class SkillTableRow(BaseModel):
    roll: str | None = None
    result: str | None = None
    percent: str | None = None
    time: str | None = None
    mod: str | None = None
    description: str | None = None


class SkillTable(BaseModel):
    name: str
    columns: list[str]
    # "General and GM-Assigned Modifers" entries the source PDF prints
    # below the table proper (e.g. "Practiced piece: +(1-3 x Memory bonus)").
    # Empty list when the table has no such footer in the source.
    general_mods: list[str] = []
    rows: list[SkillTableRow]


class SkillGroupDetail(BaseModel):
    slug: str
    section: str
    name: str
    page_div: int
    page_content: int
    # Group-level prose from "School of Hard Knocks" Section 5 — general
    # rules / GM guidance that applies to the whole category family.
    # Empty when SOHK doesn't cover this group.
    sohk_notes: str = ""
    categories: list[SkillCategory]
    skills: list[Skill]
    tables: list[SkillTable]
    # Audit metadata stamped by the PUT handler; both NULL until the first save.
    updated_at: str | None = None
    updated_by_user_id: int | None = None


class SkillGroupUpdate(BaseModel):
    """Wholesale payload for `PUT /api/v1/skills/{slug}`.

    The shape mirrors the GET response (minus slug/section/page_* —
    those identify the group but aren't editable). Everything in
    categories/skills/tables is replaced wholesale: send the full
    desired list, and the server wipes + re-inserts.

    `sohk_notes` is optional — when omitted, the server leaves the
    existing value alone (clients that don't know about SOHK can keep
    sending the old payload shape without wiping it).
    """
    name: str | None = None
    sohk_notes: str | None = None
    categories: list[SkillCategory]
    skills: list[Skill]
    tables: list[SkillTable]


class SkillSearchHit(BaseModel):
    name: str
    stat: str | None = None
    group_slug: str
    section: str
    group_name: str


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------

@router.get("", response_model=list[SkillGroupRow])
def get_groups(user: dict = CurrentUser) -> list[SkillGroupRow]:
    """All 34 skill-category-groups, ordered by A-1.X section number."""
    with connect_rw() as conn:
        rows = list_skill_groups(conn)
    return [SkillGroupRow(**r) for r in rows]


@router.get("/search", response_model=list[SkillSearchHit])
def search(
    q: str = Query(..., min_length=1, max_length=80,
                   description="Substring of skill name"),
    limit: int = Query(25, ge=1, le=100),
    user: dict = CurrentUser,
) -> list[SkillSearchHit]:
    with connect_rw() as conn:
        rows = search_skills(conn, q, limit=limit)
    return [SkillSearchHit(**r) for r in rows]


@router.get("/{slug}", response_model=SkillGroupDetail)
def get_group(slug: str, user: dict = CurrentUser) -> SkillGroupDetail:
    """One skill group — categories, per-skill descriptions, and any
    embedded maneuver / lookup tables. 404 if `slug` is unknown."""
    with connect_rw() as conn:
        g = get_skill_group(conn, slug)
    if g is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill group not found",
        )
    return SkillGroupDetail(**g)


@router.put("/{slug}", response_model=SkillGroupDetail)
def update_group(
    slug: str,
    body: SkillGroupUpdate,
    user: dict = CurrentUser,
) -> SkillGroupDetail:
    """Replace one group's editable contents and re-serialise its .txt file.

    The sequence — DB UPDATE → file write → COMMIT — mirrors the spells
    edit handler: if the file write raises, the DB is rolled back so the
    on-disk file stays canonical.
    """
    # exclude_unset=True keeps sohk_notes out of the payload when the
    # client didn't send it — that lets update_skill_group keep the
    # existing value instead of clobbering it with "".
    payload = body.model_dump(exclude_unset=True)
    # `name` is allowed to drift if the user fixes a typo; the loader-level
    # @group_name field gets re-serialised from the DB row.
    new_name = payload.get("name")

    with connect_rw() as conn:
        if new_name:
            conn.execute(
                "UPDATE skill_category_group SET name = ? WHERE slug = ?",
                (new_name, slug),
            )
        updated = update_skill_group(
            conn,
            slug=slug,
            payload=payload,
            user_id=user["user_id"],
        )
        if updated is None:
            conn.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Skill group not found",
            )
        try:
            write_skill_group_file(conn, slug=slug, project_root=_PROJECT_ROOT)
        except Exception:
            conn.rollback()
            raise
        conn.commit()
    return SkillGroupDetail(**updated)
