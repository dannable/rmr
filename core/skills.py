"""Read helpers for the skills catalog (RMSS Appendix A-1).

All reference data is loaded by load.py from data/skills/*.txt into the
skill_category_group / skill_category / skill / skill_table tables.
These helpers compose the rows back into the structured payload the web
API (and future skill DP allocator) consumes.

This module also owns the web edit path: `update_skill_group` applies a
wholesale payload to one group (wipe-and-replace the category / skill /
table / row children, plus update group-level metadata), and
`write_skill_group_file` re-serialises the corresponding
data/skills/<slug>.txt so the on-disk source-of-truth stays in sync.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def list_skill_groups(conn: sqlite3.Connection) -> list[dict]:
    """All 34 category-groups, ordered by section."""
    rows = conn.execute(
        """SELECT slug, section, name, page_div, page_content
             FROM skill_category_group
            ORDER BY CAST(SUBSTR(section, 5) AS INTEGER)"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_skill_group(conn: sqlite3.Connection, slug: str) -> dict | None:
    """One group with everything nested: categories, skills, tables, rows."""
    row = conn.execute(
        """SELECT group_id, slug, section, name, page_div, page_content,
                  updated_at, updated_by_user_id
             FROM skill_category_group WHERE slug = ?""",
        (slug,),
    ).fetchone()
    if row is None:
        return None
    g = dict(row)
    g["categories"] = [
        dict(r) for r in conn.execute(
            """SELECT name, skills_list, restricted, stat_bonuses,
                      rank_progression, category_progression, parent_group,
                      classification, description
                 FROM skill_category
                WHERE group_id = ?
                ORDER BY category_id""",
            (g["group_id"],),
        ).fetchall()
    ]
    g["skills"] = [
        dict(r) for r in conn.execute(
            """SELECT name, stat, description
                 FROM skill
                WHERE group_id = ?
                ORDER BY skill_id""",
            (g["group_id"],),
        ).fetchall()
    ]
    tables_rows = conn.execute(
        """SELECT table_id, name, columns, general_mods
             FROM skill_table
            WHERE group_id = ?
            ORDER BY table_id""",
        (g["group_id"],),
    ).fetchall()
    g["tables"] = []
    for t in tables_rows:
        rows = conn.execute(
            """SELECT roll, result, percent, time, mod, description
                 FROM skill_table_row
                WHERE table_id = ?
                ORDER BY sort_order""",
            (t["table_id"],),
        ).fetchall()
        # general_mods is stored newline-separated; split + drop blanks so
        # callers get a list of "Label: value" strings ready to render.
        gm_raw = (t["general_mods"] or "").strip()
        general_mods = [ln.strip() for ln in gm_raw.split("\n") if ln.strip()] if gm_raw else []
        g["tables"].append({
            "name": t["name"],
            "columns": [c.strip() for c in (t["columns"] or "").split("|")],
            "general_mods": general_mods,
            "rows": [dict(r) for r in rows],
        })
    return g


def update_skill_group(
    conn: sqlite3.Connection,
    *,
    slug: str,
    payload: dict,
    user_id: int | None,
) -> dict | None:
    """Wholesale replace one group's editable children.

    `payload` mirrors the shape returned by `get_skill_group`:
        {
          "categories": [{name, skills_list, restricted, stat_bonuses,
                          rank_progression, category_progression, parent_group,
                          classification, description}, ...],
          "skills":     [{name, stat, description}, ...],
          "tables":     [{name, columns: [...], general_mods: [...],
                          rows: [{roll, result, percent, time, mod, description}, ...]}],
        }

    Strategy is wipe-and-replace per group: DELETE every dependent row,
    INSERT fresh from the payload. This keeps the JSON shape simple
    (no surrogate IDs to thread through) at the cost of churning
    AUTOINCREMENT IDs on every save — acceptable for an admin-edit
    flow that runs rarely.

    Does NOT commit. The caller controls the transaction so the file
    write can be sequenced atomically against the DB change.

    Returns the freshly-loaded group dict (same shape as
    get_skill_group), or None if `slug` is unknown.
    """
    row = conn.execute(
        "SELECT group_id FROM skill_category_group WHERE slug = ?", (slug,)
    ).fetchone()
    if row is None:
        return None
    group_id = row[0]

    # FK CASCADE handles skill_table_row from skill_table, but the other
    # children sit directly under the group — wipe them all explicitly so
    # the order is obvious.
    conn.execute("DELETE FROM skill_table WHERE group_id = ?", (group_id,))
    conn.execute("DELETE FROM skill WHERE group_id = ?", (group_id,))
    conn.execute("DELETE FROM skill_category WHERE group_id = ?", (group_id,))

    for cat in payload.get("categories", []):
        conn.execute(
            """INSERT INTO skill_category (
                group_id, name, skills_list, restricted, stat_bonuses,
                rank_progression, category_progression, parent_group,
                classification, description
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (group_id, cat.get("name", ""), cat.get("skills_list"),
             cat.get("restricted"), cat.get("stat_bonuses"),
             cat.get("rank_progression"), cat.get("category_progression"),
             cat.get("parent_group"), cat.get("classification"),
             cat.get("description")),
        )

    for sk in payload.get("skills", []):
        conn.execute(
            "INSERT INTO skill (group_id, name, stat, description) VALUES (?, ?, ?, ?)",
            (group_id, sk.get("name", ""), sk.get("stat"), sk.get("description")),
        )

    for t in payload.get("tables", []):
        cols = t.get("columns") or []
        cols_text = " | ".join(cols)
        gm_list = t.get("general_mods") or []
        gm_text = "\n".join(gm_list)
        cur = conn.execute(
            "INSERT INTO skill_table (group_id, name, columns, general_mods) "
            "VALUES (?, ?, ?, ?)",
            (group_id, t.get("name", ""), cols_text, gm_text),
        )
        table_id = cur.lastrowid
        for i, row in enumerate(t.get("rows") or []):
            conn.execute(
                """INSERT INTO skill_table_row (
                    table_id, sort_order, roll, result, percent, time, mod, description
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (table_id, i, row.get("roll"), row.get("result"),
                 row.get("percent"), row.get("time"), row.get("mod"),
                 row.get("description")),
            )

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        "UPDATE skill_category_group "
        "   SET updated_at = ?, updated_by_user_id = ? "
        " WHERE group_id = ?",
        (now, user_id, group_id),
    )
    return get_skill_group(conn, slug)


# ---------------------------------------------------------------------------
# file write-back: keep data/skills/<slug>.txt in sync with the DB
# ---------------------------------------------------------------------------

_FILE_HEADER_TMPL = """\
# Skill Category Group: {name} ({section})
# Source: rmss skills.pdf, pages {page_div}-{page_content}
# Regenerated by the web edit endpoint at {timestamp}.
#
@section: {section}
@group_name: {name}
@page_div: {page_div}
@page_content: {page_content}
"""


def _format_multiline(field: str, text: str | None) -> list[str]:
    """Render a @<field>: text block. Long single-line text is emitted as a
    one-liner; explicit-newline text becomes a multi-line block with
    1-space continuation indents that the loader picks up.
    """
    if text is None or text == "":
        return [f"@{field}:"]
    if "\n" not in text:
        return [f"@{field}: {text}"]
    out = [f"@{field}:"]
    for ln in text.splitlines():
        out.append(f" {ln}" if ln else "")
    return out


def write_skill_group_file(
    conn: sqlite3.Connection,
    *,
    slug: str,
    project_root: Path,
) -> Path:
    """Re-serialise one group's data/skills/<slug>.txt file from current DB state.

    Atomic via tempfile + os.replace so a crashed write can't leave a
    half-written file. Returns the path written. Raises ValueError when
    `slug` is unknown.
    """
    g = get_skill_group(conn, slug)
    if g is None:
        raise ValueError(f"skill group {slug!r} not found")

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines: list[str] = [_FILE_HEADER_TMPL.format(
        name=g["name"],
        section=g["section"],
        page_div=g["page_div"],
        page_content=g["page_content"],
        timestamp=timestamp,
    ).rstrip("\n")]

    # Categories block.
    if g["categories"]:
        lines.append("")
        lines.append("# " + "=" * 67)
        lines.append("# CATEGORIES")
        lines.append("# " + "=" * 67)
        for cat in g["categories"]:
            lines.append("")
            lines.append(f"@category: {cat['name']}")
            lines.extend(_format_multiline("skills",               cat.get("skills_list")))
            lines.extend(_format_multiline("restricted",           cat.get("restricted")))
            lines.extend(_format_multiline("stat_bonuses",         cat.get("stat_bonuses")))
            lines.extend(_format_multiline("rank_progression",     cat.get("rank_progression")))
            lines.extend(_format_multiline("category_progression", cat.get("category_progression")))
            lines.extend(_format_multiline("group",                cat.get("parent_group")))
            lines.extend(_format_multiline("classification",       cat.get("classification")))
            lines.extend(_format_multiline("description",          cat.get("description")))

    # Skill descriptions block.
    if g["skills"]:
        lines.append("")
        lines.append("# " + "=" * 67)
        lines.append("# SKILL DESCRIPTIONS")
        lines.append("# " + "=" * 67)
        for sk in g["skills"]:
            lines.append("")
            lines.append(f"@@ {sk['name']}")
            if sk.get("stat"):
                lines.append(f"@stat: {sk['stat']}")
            lines.extend(_format_multiline("description", sk.get("description")))

    # Tables block.
    if g["tables"]:
        lines.append("")
        lines.append("# " + "=" * 67)
        lines.append("# TABLES")
        lines.append("# " + "=" * 67)
        for t in g["tables"]:
            lines.append("")
            lines.append(f"@table: {t['name']}")
            lines.append(f"@columns: {' | '.join(t['columns'])}")
            for row in t["rows"]:
                cells = [row.get(c) or "" for c in t["columns"]]
                lines.append(" | ".join(cells))
            if t.get("general_mods"):
                lines.append("")
                lines.append("@general_mods:")
                for entry in t["general_mods"]:
                    lines.append(entry)

    body = "\n".join(lines).rstrip() + "\n"
    target = project_root / "data" / "skills" / f"{slug}.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8", newline="\n")
    os.replace(tmp, target)
    return target


def search_skills(conn: sqlite3.Connection, query: str,
                  limit: int = 25) -> list[dict]:
    """Search skills by name (case-insensitive substring).

    Returns rows with skill metadata + the parent group's name and section
    so the SPA can deep-link to the group page.
    """
    rows = conn.execute(
        """SELECT s.name, s.stat, scg.slug AS group_slug,
                  scg.section, scg.name AS group_name
             FROM skill s
             JOIN skill_category_group scg ON s.group_id = scg.group_id
            WHERE LOWER(s.name) LIKE LOWER(?)
            ORDER BY s.name
            LIMIT ?""",
        (f"%{query}%", limit),
    ).fetchall()
    return [dict(r) for r in rows]
