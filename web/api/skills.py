"""Skills catalog endpoints (RMSS Appendix A-1).

Read-only; the catalog data is loaded from data/skills/*.txt by load.py.
All endpoints are login-gated, matching the rest of the character builder.

Routes:
    GET /api/v1/skills                       — list all 34 groups
    GET /api/v1/skills/{slug}                — one group + categories + skills + tables
    GET /api/v1/skills/search?q=<substring>  — skill-name search
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from core.skills import list_skill_groups, get_skill_group, search_skills

from ..auth.deps import CurrentUser
from ..db import connect_rw

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


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


class Skill(BaseModel):
    name: str
    stat: str | None = None
    description: str | None = None


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
    rows: list[SkillTableRow]


class SkillGroupDetail(BaseModel):
    slug: str
    section: str
    name: str
    page_div: int
    page_content: int
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
