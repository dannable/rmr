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

__all__ = [
    "STAT_CODES",
    "STAT_NAMES",
    "StatCode",
    "basic_stat_bonus",
    "stat_bonuses",
    "rr_bonus",
    "Realm",
    "RR_FORMULAS",
]
