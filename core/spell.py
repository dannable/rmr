"""Spell-list and spell lookups (Channeling realm; Phase 1+2 schema).

Includes:
  * Read helpers used by the Discord bot and the web API.
  * `update_spell`: mutating helper used by the web edit handler.
  * `write_spell_list_file`: re-serialise a list's data/spell_lists/<realm>/
    <slug>.txt file from current DB state, so the on-disk source-of-truth
    stays in sync with web edits.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# classes / lists
# ---------------------------------------------------------------------------

def list_classes(conn: sqlite3.Connection) -> list[dict]:
    """All caster classes, ordered by realm then name."""
    return [dict(r) for r in conn.execute(
        """SELECT sc.name AS class_name, sr.name AS realm_name
             FROM spell_class sc
             JOIN spell_realm sr USING (realm_id)
            ORDER BY sr.name, sc.name"""
    ).fetchall()]


def search_classes(conn: sqlite3.Connection, prefix: str,
                   limit: int = 25) -> list[str]:
    """Case-insensitive substring match for autocomplete dropdowns."""
    rows = conn.execute(
        "SELECT name FROM spell_class WHERE LOWER(name) LIKE LOWER(?) "
        "ORDER BY name LIMIT ?",
        (f"%{prefix}%", limit),
    ).fetchall()
    return [r[0] for r in rows]


def lists_for_class(conn: sqlite3.Connection, class_name: str) -> list[dict]:
    """All lists accessible to the given class, grouped by category.

    Returns rows with: name, list_number, category. Sort is Base→Open→Closed
    then by list_number within each category.
    """
    rows = conn.execute(
        """SELECT sl.name, sl.list_number, sl.category
             FROM spell_list sl
             JOIN class_spell_list csl ON sl.list_id = csl.list_id
             JOIN spell_class sc ON sc.class_id = csl.class_id
            WHERE sc.name = ?
            ORDER BY CASE sl.category
                       WHEN 'Base'   THEN 1
                       WHEN 'Open'   THEN 2
                       WHEN 'Closed' THEN 3
                       ELSE 99
                     END,
                     -- Natural-sort list_number: "2.1.2" sorts before "2.1.10"
                     -- by ordering on (string length, value).
                     length(sl.list_number), sl.list_number""",
        (class_name,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_spell_lists(conn: sqlite3.Connection) -> list[dict]:
    """Every spell list across all realms (debug / /spells without args)."""
    return [dict(r) for r in conn.execute(
        """SELECT sl.name, sl.list_number, sl.category, sr.name AS realm_name
             FROM spell_list sl
             JOIN spell_realm sr USING (realm_id)
            ORDER BY length(sl.list_number), sl.list_number"""
    ).fetchall()]


def list_realms(conn: sqlite3.Connection) -> list[str]:
    """All loaded realm names, alphabetical (`['Channeling', 'Essence']` today)."""
    return [r[0] for r in conn.execute(
        "SELECT name FROM spell_realm ORDER BY name"
    ).fetchall()]


def search_spell_lists(conn: sqlite3.Connection, prefix: str,
                       limit: int = 25,
                       realm: str | None = None) -> list[str]:
    """Substring search across spell-list names. Pass `realm` (case-insensitive)
    to scope results to a single realm — useful when the bot's /spell or
    /spell-list commands narrow the autocomplete after the user picks a realm.
    """
    if realm:
        rows = conn.execute(
            """SELECT sl.name FROM spell_list sl
                 JOIN spell_realm sr ON sl.realm_id = sr.realm_id
                WHERE LOWER(sl.name) LIKE LOWER(?)
                  AND LOWER(sr.name) = LOWER(?)
                ORDER BY sl.name LIMIT ?""",
            (f"%{prefix}%", realm, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT name FROM spell_list WHERE LOWER(name) LIKE LOWER(?) "
            "ORDER BY name LIMIT ?",
            (f"%{prefix}%", limit),
        ).fetchall()
    return [r[0] for r in rows]


def get_spell_list(conn: sqlite3.Connection, name: str,
                   realm: str | None = None) -> dict | None:
    """Look up a spell list by name (case-insensitive). Returns None if absent.

    Pass `realm` to disambiguate when the same list name exists in two realms;
    without it, the first match by realm-then-name order wins.
    """
    if realm:
        row = conn.execute(
            """SELECT sl.list_id, sl.name, sl.list_number, sl.category,
                      sr.name AS realm_name
                 FROM spell_list sl
                 JOIN spell_realm sr USING (realm_id)
                WHERE LOWER(sl.name) = LOWER(?)
                  AND LOWER(sr.name) = LOWER(?)""",
            (name, realm),
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT sl.list_id, sl.name, sl.list_number, sl.category,
                      sr.name AS realm_name
                 FROM spell_list sl
                 JOIN spell_realm sr USING (realm_id)
                WHERE LOWER(sl.name) = LOWER(?)""",
            (name,),
        ).fetchone()
    return dict(row) if row else None


def spells_on_list(conn: sqlite3.Connection, list_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """SELECT level, name, area_effect, duration, range_str, spell_type,
                  starred, description
             FROM spell
            WHERE list_id = ?
            ORDER BY level""",
        (list_id,),
    ).fetchall()]


def classes_for_list(conn: sqlite3.Connection, list_id: int) -> list[str]:
    """Return the class names that have access to this list."""
    rows = conn.execute(
        """SELECT sc.name
             FROM spell_class sc
             JOIN class_spell_list csl ON sc.class_id = csl.class_id
            WHERE csl.list_id = ?
            ORDER BY sc.name""",
        (list_id,),
    ).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# individual spell lookup + search
# ---------------------------------------------------------------------------

def get_spell(conn: sqlite3.Connection, list_name: str, level: int,
              realm: str | None = None) -> dict | None:
    """Look up one spell by its list name + level.

    Pass `realm` to disambiguate when the same list name exists in two realms.
    """
    if realm:
        row = conn.execute(
            """SELECT s.level, s.name, s.area_effect, s.duration, s.range_str,
                      s.spell_type, s.starred, s.description,
                      sl.name AS list_name, sl.list_number, sl.category,
                      sr.name AS realm_name
                 FROM spell s
                 JOIN spell_list sl ON s.list_id = sl.list_id
                 JOIN spell_realm sr ON sl.realm_id = sr.realm_id
                WHERE LOWER(sl.name) = LOWER(?) AND s.level = ?
                  AND LOWER(sr.name) = LOWER(?)""",
            (list_name, level, realm),
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT s.level, s.name, s.area_effect, s.duration, s.range_str,
                      s.spell_type, s.starred, s.description,
                      sl.name AS list_name, sl.list_number, sl.category,
                      sr.name AS realm_name
                 FROM spell s
                 JOIN spell_list sl ON s.list_id = sl.list_id
                 JOIN spell_realm sr ON sl.realm_id = sr.realm_id
                WHERE LOWER(sl.name) = LOWER(?) AND s.level = ?""",
            (list_name, level),
        ).fetchone()
    return dict(row) if row else None


def search_spells(conn: sqlite3.Connection, query: str,
                  limit: int = 25) -> list[dict]:
    """Search across all spells by name (case-insensitive substring).

    Returns rows with the spell + its containing list info.
    """
    rows = conn.execute(
        """SELECT s.level, s.name, s.spell_type,
                  sl.name AS list_name, sl.list_number, sl.category
             FROM spell s
             JOIN spell_list sl ON s.list_id = sl.list_id
            WHERE LOWER(s.name) LIKE LOWER(?)
            ORDER BY s.name, sl.list_number
            LIMIT ?""",
        (f"%{query}%", limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# mutations + serializer (Phase 3: web edit)
# ---------------------------------------------------------------------------

# Fields the web edit handler may change on a spell row.
EDITABLE_SPELL_FIELDS: tuple[str, ...] = (
    "name", "area_effect", "duration", "range_str",
    "spell_type", "description", "starred",
)


def update_spell(
    conn: sqlite3.Connection,
    *,
    list_id: int,
    level: int,
    fields: dict,
    user_id: int | None,
) -> dict | None:
    """Apply a partial update to one spell row and stamp audit fields.

    Only keys in EDITABLE_SPELL_FIELDS are honored. Returns the fully
    refreshed row dict (joined with the list metadata) or None if no
    spell exists at that (list_id, level). Does NOT commit; the caller
    is responsible for transaction control.
    """
    valid = {k: v for k, v in fields.items() if k in EDITABLE_SPELL_FIELDS}
    if not valid:
        # Still bump updated_at so we can tell when somebody hit "save"
        # without changing anything; doesn't hurt downstream.
        valid = {}
    set_clauses = [f"{k} = ?" for k in valid] + ["updated_at = ?", "updated_by_user_id = ?"]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    params: list = list(valid.values()) + [now, user_id, list_id, level]
    cur = conn.execute(
        f"UPDATE spell SET {', '.join(set_clauses)} WHERE list_id = ? AND level = ?",
        params,
    )
    if cur.rowcount == 0:
        return None
    return get_spell_by_list_id(conn, list_id, level)


def get_spell_by_list_id(conn: sqlite3.Connection, list_id: int,
                         level: int) -> dict | None:
    """Look up one spell by list_id + level (vs get_spell, which uses list NAME)."""
    row = conn.execute(
        """SELECT s.level, s.name, s.area_effect, s.duration, s.range_str,
                  s.spell_type, s.starred, s.description,
                  s.updated_at, s.updated_by_user_id,
                  sl.list_id, sl.name AS list_name, sl.list_number, sl.category,
                  sr.name AS realm_name
             FROM spell s
             JOIN spell_list sl ON s.list_id = sl.list_id
             JOIN spell_realm sr ON sl.realm_id = sr.realm_id
            WHERE sl.list_id = ? AND s.level = ?""",
        (list_id, level),
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# file write-back: keep data/spell_lists/<realm>/<slug>.txt in sync with the DB
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    """Same slug rule the Phase-1 build script used.

    "Nature's Movement/Senses" -> "natures_movement_senses"
    """
    s = name.lower()
    s = re.sub(r"[''’]", "", s)
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


_LIST_FILE_HEADER_TMPL = """\
# Spell List {number} — {name} ({category})
# Generated from rmfrp.db on {timestamp}.
# Source of truth: this file. The web edit endpoint regenerates it
# atomically whenever a spell on this list is changed.
#
@realm:    {realm}
@name:     {name}
@number:   {number}
@category: {category}
{class_line}#
# Format: <level> | <spell_name> | <area_effect> | <duration> | <range> | <type>
# A trailing '*' in the source chart (a Concentration / continuing-effect
# marker) is recorded as the starred flag rather than in the name.
#
"""

_DESC_BLOCK_HEADER = """\

# Descriptions
# Format: each spell description starts with `@@ <level>` on its
# own line. The block continues until the next `@@` or end-of-file.
# Multi-paragraph text is preserved; whitespace is normalised.
#
"""


def _list_file_path(root: Path, realm: str, list_name: str) -> Path:
    realm_dir = realm.lower().replace(" ", "_")
    return root / "data" / "spell_lists" / realm_dir / f"{_slugify(list_name)}.txt"


def write_spell_list_file(
    conn: sqlite3.Connection,
    *,
    list_id: int,
    project_root: Path,
) -> Path:
    """Re-serialise a spell list's .txt file from current DB state.

    Looks up the list's realm/name/category/number and (for Base lists) the
    owning class, then rewrites data/spell_lists/<realm>/<slug>.txt with the
    canonical Phase-1+Phase-2 format. Atomic via tempfile + os.replace so a
    crashed write can't leave a half-written file.

    Returns the path written. Raises ValueError if the list doesn't exist.
    """
    meta_row = conn.execute(
        """SELECT sl.list_id, sl.name, sl.list_number, sl.category,
                  sr.name AS realm_name
             FROM spell_list sl
             JOIN spell_realm sr ON sl.realm_id = sr.realm_id
            WHERE sl.list_id = ?""",
        (list_id,),
    ).fetchone()
    if meta_row is None:
        raise ValueError(f"spell_list {list_id} not found")
    meta = dict(meta_row)

    # For Base lists, look up which class owns it. Open/Closed list files
    # have no @class line. (Loader auto-grants Open+Closed access to every
    # declared class, so multiple class_spell_list rows exist for those —
    # the canonical file format omits @class in that case.)
    class_line = ""
    if meta["category"] == "Base":
        owning = conn.execute(
            """SELECT sc.name FROM spell_class sc
                JOIN class_spell_list csl ON sc.class_id = csl.class_id
               WHERE csl.list_id = ?
               ORDER BY sc.name LIMIT 1""",
            (list_id,),
        ).fetchone()
        if owning:
            class_line = f"@class:    {owning['name']}\n"

    spells = spells_on_list(conn, list_id)

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    header = _LIST_FILE_HEADER_TMPL.format(
        number=meta["list_number"],
        name=meta["name"],
        category=meta["category"],
        realm=meta["realm_name"],
        class_line=class_line,
        timestamp=timestamp,
    )

    chart_lines: list[str] = []
    desc_blocks: list[str] = []
    for s in spells:
        star = " *" if s.get("starred") else ""
        chart_lines.append(
            f"{s['level']:>2} | {s['name']}{star} | "
            f"{s.get('area_effect') or ''} | {s.get('duration') or ''} | "
            f"{s.get('range_str') or ''} | {s.get('spell_type') or ''}\n"
        )
        desc = s.get("description")
        if desc:
            desc_blocks.append(f"@@ {s['level']}\n{desc.rstrip()}\n\n")

    body = header + "".join(chart_lines)
    if desc_blocks:
        body += _DESC_BLOCK_HEADER + "".join(desc_blocks).rstrip() + "\n"

    target = _list_file_path(project_root, meta["realm_name"], meta["name"])
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8", newline="\n")
    import os
    os.replace(tmp, target)
    return target
