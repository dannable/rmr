"""Pure-function game logic for RMSS character generation.

Modules in here MUST NOT import from web/, bot/, or any I/O layer. They
operate on dataclasses/dicts and return new ones. The web app and the
Discord bot both consume the same functions to keep results consistent.
"""

from .stats import (
    STAT_CODES,
    STAT_NAMES,
    StatCode,
    basic_stat_bonus,
    stat_bonuses,
    rr_bonus,
    Realm,
    RR_FORMULAS,
)
from .race import (
    list_races,
    get_race_by_id,
    get_race_by_slug,
    race_stat_mods,
    race_rr_mods,
    apply_stat_mods,
)

__all__ = [
    "STAT_CODES",
    "STAT_NAMES",
    "StatCode",
    "basic_stat_bonus",
    "stat_bonuses",
    "rr_bonus",
    "Realm",
    "RR_FORMULAS",
    "list_races",
    "get_race_by_id",
    "get_race_by_slug",
    "race_stat_mods",
    "race_rr_mods",
    "apply_stat_mods",
]
