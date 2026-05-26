"""Background Options (RMSS Character Law Table T-1.5).

A new character spends a race-dependent number of background option
"slots" (per `race.bg_opts`) on entries from a fixed menu. The picks
go into `character_background_option`, one row per slot spent. The
menu is short and stable enough to hardcode here rather than carry as
loadable reference data.

Each option may carry an optional `detail` text the player types in
(e.g. specifying which language for a language-rank pick). The
catalog tells the SPA whether a detail input should be shown and
suggests a placeholder.
"""

from __future__ import annotations


# RMSS T-1.5 background-options menu. The `key` is stable (used as the
# stored option_key); `label` + `description` show in the picker.
# `wants_detail=True` triggers an inline text input next to the
# dropdown for player-specified specifics.
BACKGROUND_OPTIONS: tuple[dict, ...] = (
    {
        "key": "extra_languages",
        "label": "Extra Language Ranks (+5)",
        "description": "Add 5 ranks to one specific spoken or written "
                       "language already in your repertoire (or a new "
                       "one cleared with the GM).",
        "wants_detail": True,
        "detail_placeholder": "e.g. Sindarin (spoken)",
    },
    {
        "key": "extra_weapon_ranks",
        "label": "Extra Weapon Skill Ranks (+5)",
        "description": "Add 5 ranks of skill in one specific weapon.",
        "wants_detail": True,
        "detail_placeholder": "e.g. Broadsword",
    },
    {
        "key": "stat_gain_roll",
        "label": "Extra Stat Gain Roll",
        "description": "Roll an extra stat gain on one of your prime "
                       "stats (or any stat the GM permits).",
        "wants_detail": True,
        "detail_placeholder": "e.g. St",
    },
    {
        "key": "special_skill_ranks",
        "label": "Special Skill Ranks (+5)",
        "description": "Add 5 ranks in one specific non-weapon skill.",
        "wants_detail": True,
        "detail_placeholder": "e.g. Cooking",
    },
    {
        "key": "extra_money",
        "label": "Extra Money (1d10 × 10 GP)",
        "description": "Adds 1d10 × 10 gold pieces to your starting "
                       "money. Roll with the GM.",
        "wants_detail": False,
        "detail_placeholder": "",
    },
    {
        "key": "special_item",
        "label": "Special Item",
        "description": "Receive a special item appropriate to your "
                       "race and background. Work with the GM.",
        "wants_detail": True,
        "detail_placeholder": "e.g. Heirloom dagger",
    },
    {
        "key": "talent",
        "label": "Talent (Companion books)",
        "description": "Spend the option on a Talent from RMSS "
                       "Companion supplements (subject to GM approval "
                       "and any extra BG-opt cost the Talent demands).",
        "wants_detail": True,
        "detail_placeholder": "e.g. Lucky",
    },
)


BACKGROUND_OPTION_KEYS: frozenset[str] = frozenset(
    o["key"] for o in BACKGROUND_OPTIONS
)
