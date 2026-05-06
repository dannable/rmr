"""Core lookup logic for RMR — pure functions over rmfrp.db.

Both the CLI (lookup.py, roll.py) and the Discord bot (bot/) import from here.
No I/O beyond SQLite reads; no printing, no Discord types, no argparse.
"""

from .db import connect, DB_PATH
from .roll import d100, open_ended_d100, format_rolls
from .attack import (
    CRIT_TYPE_NAMES,
    SIZE_NAMES,
    RANK_NAMES,
    DEGREE_LABELS,
    degree_label,
    get_weapon,
    list_weapons,
    search_weapons,
    attack_lookup,
    size_cap,
)
from .crit import (
    CRIT_TYPE_TO_TABLE,
    list_crit_tables,
    search_crit_tables,
    resolve_crit_table_id,
    crit_lookup,
    crit_lookup_by_name,
)
from .fumble import (
    CRIT_WORD_TO_TABLE,
    FUMBLE_CRIT_RE,
    list_fumble_tables,
    search_fumble_tables,
    fumble_columns,
    fumble_lookup,
    parse_fumble_crit_chain,
)

__all__ = [
    "connect", "DB_PATH",
    "d100", "open_ended_d100", "format_rolls",
    "CRIT_TYPE_NAMES", "SIZE_NAMES", "RANK_NAMES", "DEGREE_LABELS",
    "degree_label",
    "get_weapon", "list_weapons", "search_weapons",
    "attack_lookup", "size_cap",
    "CRIT_TYPE_TO_TABLE",
    "list_crit_tables", "search_crit_tables",
    "resolve_crit_table_id", "crit_lookup", "crit_lookup_by_name",
    "CRIT_WORD_TO_TABLE", "FUMBLE_CRIT_RE",
    "list_fumble_tables", "search_fumble_tables", "fumble_columns",
    "fumble_lookup", "parse_fumble_crit_chain",
]
