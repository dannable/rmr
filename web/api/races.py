"""GET /api/v1/races — the race list the SPA picker dropdown consumes.

Read-only endpoint; race data is loaded from `data/chargen/races/*.txt`
by `load.py` and lives in the `race` table. Login-gated, like every
other character-builder route.
"""

from __future__ import annotations

import json

from fastapi import APIRouter
from pydantic import BaseModel

from core.chargen.stats import STAT_CODES, StatCode
from core.chargen.race import list_races, race_stat_mods, race_rr_mods

from ..auth.deps import CurrentUser
from ..db import connect_rw

router = APIRouter(prefix="/api/v1/races", tags=["races"])


class RaceRRMods(BaseModel):
    channeling: int
    essence: int
    mentalism: int
    chan_ess: int
    chan_ment: int
    ess_ment: int
    arcane: int
    poison_disease: int
    fear: int


class Race(BaseModel):
    """One playable race. Mods are pre-projected onto the 9 RR categories
    the StatsEditor uses so the SPA doesn't need to re-implement T-1.1.

    `culture_data` holds the rich text fields extracted from the RMSS
    Cultures & Races appendix — languages, hobby skills, weapons, armor,
    money, professions, demeanor, religion, etc. Keys are stable slugs
    (e.g. `starting_languages`, `hobby_skills`); values are plain strings.
    Missing keys mean that field wasn't in the source for this race
    (Common Men + Mixed Men currently have an empty object).
    """
    slug: str
    name: str
    stat_mods: dict[StatCode, int]
    rr_mods: RaceRRMods
    bg_opts: int
    body_dev_prog: str
    chan_pp_prog: str
    ess_pp_prog: str
    ment_pp_prog: str
    culture_data: dict[str, str] = {}


def _row_to_race(row: dict) -> Race:
    # culture_data is stored as JSON-encoded TEXT; default to '{}' if NULL
    # (older deployments before the migration applied the column DEFAULT).
    raw = row.get("culture_data") or "{}"
    try:
        culture = json.loads(raw)
        if not isinstance(culture, dict):
            culture = {}
    except (TypeError, ValueError):
        culture = {}
    return Race(
        slug=row["slug"],
        name=row["name"],
        stat_mods=race_stat_mods(row),
        rr_mods=RaceRRMods(**race_rr_mods(row)),
        bg_opts=row["bg_opts"],
        body_dev_prog=row["body_dev_prog"],
        chan_pp_prog=row["chan_pp_prog"],
        ess_pp_prog=row["ess_pp_prog"],
        ment_pp_prog=row["ment_pp_prog"],
        culture_data=culture,
    )


@router.get("", response_model=list[Race])
def get_races(user: dict = CurrentUser) -> list[Race]:
    """All races, alphabetical by name."""
    with connect_rw() as conn:
        rows = list_races(conn)
    return [_row_to_race(r) for r in rows]
