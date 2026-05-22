"""GET /api/v1/training-packages — read-only TP catalog for the SPA.

Data flow mirrors the professions endpoint: TP data is loaded by
load.py from data/chargen/training_packages/*.txt (decoded from
`ERA/rmfrpCharacterLaw.trainingPackages.era`). Login-gated, no
character coupling yet — picking TPs for a character lands in a
follow-up PR.

Routes:
    GET /api/v1/training-packages              — list all 36 TPs (light)
    GET /api/v1/training-packages/{slug}       — one TP, fully hydrated
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from core.chargen.training_package import (
    get_training_package_by_slug,
    list_training_packages,
)

from ..auth.deps import CurrentUser
from ..db import connect_rw

router = APIRouter(prefix="/api/v1/training-packages", tags=["training-packages"])


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------

class TrainingPackageRow(BaseModel):
    """Lightweight row for the browse grid."""
    slug: str
    name: str
    category: str
    description: str
    default_cost: int


class Special(BaseModel):
    chance: int                           # 0..100
    description: str


class StatGain(BaseModel):
    """Either a guaranteed gain (stat_code set, choices empty) or a
    pick-one slot (stat_code null, choices listing the alternatives)."""
    stat_code: str | None = None
    choices: list[str] = []


class CategoryOption(BaseModel):
    group_name: str
    category_name: str


class SkillOption(BaseModel):
    skill_name: str
    classification: str


class RankAssignment(BaseModel):
    """One slot inside a TP. Either a fixed (group, category) — both
    populated, `reference_label` null — or a flexible slot with a
    human-readable `reference_label` (e.g. "Melee Weapon") plus
    `category_options` listing the allowed (group, category) pairs.

    `skill_options` is the within-category constraint: if present,
    the ranks must be spent on one of these specific skills."""
    reference_label: str | None = None
    group_name: str | None = None
    category_name: str | None = None
    cat_ranks: int = 0
    skill_ranks: int = 0
    cat_spread_max: int | None = None
    skill_spread_max: int | None = None
    ranks_assigned_max: int | None = None
    category_options: list[CategoryOption] = []
    skill_options: list[SkillOption] = []


class ProfessionCost(BaseModel):
    profession_name: str
    cost: int


class TrainingPackageDetail(BaseModel):
    slug: str
    name: str
    category: str
    description: str
    default_cost: int
    specials: list[Special]
    stat_gains: list[StatGain]
    rank_assignments: list[RankAssignment]
    profession_costs: list[ProfessionCost]


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------

@router.get("", response_model=list[TrainingPackageRow])
def get_training_packages(user: dict = CurrentUser) -> list[TrainingPackageRow]:
    """All training packages, alphabetical by name."""
    with connect_rw() as conn:
        rows = list_training_packages(conn)
    return [TrainingPackageRow(**r) for r in rows]


@router.get("/{slug}", response_model=TrainingPackageDetail)
def get_training_package(slug: str, user: dict = CurrentUser) -> TrainingPackageDetail:
    """One TP, fully hydrated. 404 if `slug` is unknown."""
    with connect_rw() as conn:
        data = get_training_package_by_slug(conn, slug)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Training package not found",
        )
    return TrainingPackageDetail(**data)
