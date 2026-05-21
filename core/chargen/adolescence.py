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


def adolescence_ranks(conn: sqlite3.Connection, culture_slug: str) -> list[dict]:
    """Return the ordered skill-rank rows for one culture, in source order.

    Each row: {"skill": "<label>", "value": "<text>", "kind": "category"|"leaf"}.
    """
    rows = conn.execute(
        "SELECT skill, value FROM adolescence_rank "
        "WHERE culture_slug = ? "
        "ORDER BY rowid",
        (culture_slug,),
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        skill = r["skill"]
        # Check for the suffix specifically (not just "in") — leaf rows for
        # weapons carry a [Weapon • 1-H Edged skill category] prefix that
        # the loader adds to disambiguate duplicate "1 Weapon Based..." rows,
        # and a substring check would mis-tag them as categories.
        kind = "category" if skill.endswith("skill category") else "leaf"
        out.append({"skill": skill, "value": r["value"], "kind": kind})
    return out


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
    summary_skills = ("Hobby Ranks", "Number of Background Options")

    def open_group(label: str, value: str) -> None:
        nonlocal current
        if current is not None:
            groups.append(current)
        current = {"category": label, "value": value, "skills": []}

    for r in rows:
        skill = r["skill"]
        value = r["value"]
        # Summary rows live in their own pseudo-group at the bottom.
        if any(skill.startswith(s) for s in summary_skills):
            if current is None or current["category"] != "Summary":
                open_group("Summary", "")
            current["skills"].append({"name": skill, "value": value})
            continue
        if r["kind"] == "category":
            open_group(skill, value)
        else:
            if current is None:
                # Leaves before any category — synthetic bucket.
                open_group("Other", "")
            current["skills"].append({"name": skill, "value": value})

    if current is not None:
        groups.append(current)
    return groups
