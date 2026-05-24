"""GET /api/v1/professions — profession list + detail for the character builder.

Read-only; profession data is loaded from data/chargen/professions/*.txt
by load.py (decoded from `ERA/rmfrpCharacterLaw.professions.era`). All
routes are login-gated, matching the rest of the character builder.

Routes:
    GET /api/v1/professions              — list all 20 professions (lightweight)
    GET /api/v1/professions/{slug}       — one profession + bonuses/costs/favorites
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from core.chargen.profession import (
    get_profession_by_slug,
    list_professions,
)

from ..auth.deps import CurrentUser
from ..db import connect_rw

router = APIRouter(prefix="/api/v1/professions", tags=["professions"])


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------

class ProfessionRow(BaseModel):
    """Lightweight row for the picker grid."""
    slug: str
    name: str
    description: str
    realms: list[str]
    prime_stats: list[str]
    portrait_path: str | None = None
    # Source book tag: 'character_law' for the 20 base professions,
    # 'essence_companion' for the 3 EC additions, 'sohk' reserved.
    source: str = "character_law"


class GroupBonus(BaseModel):
    group_name: str
    bonus: int


class CategoryBonus(BaseModel):
    group_name: str
    category_name: str
    bonus: int


class CategoryCost(BaseModel):
    group_name: str
    category_name: str
    # Source string, e.g. "2/5" (slash form) or "4/4/4-4/4/4-..." (dash form
    # used for spell-list categories). Parsing is deferred to the DP allocator.
    cost: str


class SkillCostModifier(BaseModel):
    group_name: str
    category_name: str
    skill_name: str
    classification: str
    modifier: float


class FavoriteSkill(BaseModel):
    group_name: str
    category_name: str
    skill_name: str
    classification: str


class ProfessionDetail(BaseModel):
    slug: str
    name: str
    description: str
    portrait_path: str | None = None
    source: str = "character_law"
    realms: list[str]
    prime_stats: list[str]
    group_bonuses: list[GroupBonus]
    category_bonuses: list[CategoryBonus]
    category_costs: list[CategoryCost]
    skill_cost_modifiers: list[SkillCostModifier]
    favorite_skills: list[FavoriteSkill]


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------

@router.get("", response_model=list[ProfessionRow])
def get_professions(user: dict = CurrentUser) -> list[ProfessionRow]:
    """All 20 RMSS Character Law professions, alphabetical."""
    with connect_rw() as conn:
        rows = list_professions(conn)
    return [ProfessionRow(**r) for r in rows]


@router.get("/{slug}", response_model=ProfessionDetail)
def get_profession(slug: str, user: dict = CurrentUser) -> ProfessionDetail:
    """One profession — description, prime stats, realm(s), bonuses,
    DP costs per category, per-skill cost modifiers, and favorite skills.
    404 if `slug` is unknown."""
    with connect_rw() as conn:
        data = get_profession_by_slug(conn, slug)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profession not found",
        )
    return ProfessionDetail(**data)
