"""Lookup + grouping helpers for the Adolescence Rank Table T-1.6.

The `adolescence_rank` table is a flat (skill, culture_slug, value) matrix
loaded from data/chargen/adolescence_ranks.txt in source-row order. Most
"skill category" rows are immediately followed by their leaf-skill rows
in the same source — we re-group that hierarchy here so the SPA can
render with indentation.

Used by the character builder to show "Starting skill ranks granted by
race/culture during adolescence" once a race is picked.
"""

from __future__ import annotations

import sqlite3


# Bottom-of-table T-1.6 rows that are NOT leaf skills — they're per-level
# counters (Hobby Ranks) or background-option budget (Number of Background
# Options). The apply path must NOT turn these into character_skill rows;
# the SPA pseudo-group "Summary" shows them in a separate bucket instead.
_SUMMARY_PREFIXES: tuple[str, ...] = (
    "Hobby Ranks",
    "Number of Background Options",
)


def _classify_row(skill: str) -> str:
    """Tag an adolescence_rank row as "category", "leaf", or "summary".

    Summary rows live at the bottom of T-1.6 — they're aggregate counters
    (e.g. "Hobby Ranks 12") that the apply step must skip, otherwise they
    end up in character_skill alongside real skills.
    """
    if any(skill.startswith(p) for p in _SUMMARY_PREFIXES):
        return "summary"
    # Suffix check is specific (not substring) — leaf rows for weapons
    # carry a [Weapon • 1-H Edged skill category] PREFIX that disambiguates
    # duplicate "1 Weapon Based..." rows; a substring check would mis-tag
    # them as categories.
    return "category" if skill.endswith("skill category") else "leaf"


def adolescence_ranks(conn: sqlite3.Connection, culture_slug: str) -> list[dict]:
    """Return the ordered skill-rank rows for one culture, in source order.

    Each row: {"skill": "<label>", "value": "<text>",
               "kind": "category"|"leaf"|"summary"}.
    """
    rows = conn.execute(
        "SELECT skill, value FROM adolescence_rank "
        "WHERE culture_slug = ? "
        "ORDER BY rowid",
        (culture_slug,),
    ).fetchall()
    return [
        {"skill": r["skill"], "value": r["value"], "kind": _classify_row(r["skill"])}
        for r in rows
    ]


def grouped_ranks(conn: sqlite3.Connection, culture_slug: str) -> list[dict]:
    """Same data, regrouped into a hierarchy for tabular display.

    Returns a list of group dicts:
        [
          {
            "category": "Armor • Light skill category",
            "value": "1",
            "skills": [
              {"name": "Soft Leather skill", "value": "0"},
              {"name": "Rigid Leather skill", "value": "1"},
            ],
          },
          ...
        ]

    Leaves before the first category become a synthetic "Other" group.
    Bottom-of-table summary rows ("Hobby Ranks", "Number of Background
    Options") aren't categories per se but they're flat — we surface them
    under a final "Summary" pseudo-group so the SPA can display them too.
    """
    rows = adolescence_ranks(conn, culture_slug)
    groups: list[dict] = []
    current: dict | None = None

    def open_group(label: str, value: str) -> None:
        nonlocal current
        if current is not None:
            groups.append(current)
        current = {"category": label, "value": value, "skills": []}

    for r in rows:
        skill = r["skill"]
        value = r["value"]
        kind = r["kind"]
        if kind == "summary":
            # Summary rows live in their own pseudo-group at the bottom.
            if current is None or current["category"] != "Summary":
                open_group("Summary", "")
            current["skills"].append({"name": skill, "value": value})
            continue
        if kind == "category":
            open_group(skill, value)
        else:  # "leaf"
            if current is None:
                # Leaves before any category — synthetic bucket.
                open_group("Other", "")
            current["skills"].append({"name": skill, "value": value})

    if current is not None:
        groups.append(current)
    return groups
