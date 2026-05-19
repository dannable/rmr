"""Populate rmfrp.db from data files in data/."""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent
SCHEMA = ROOT / "schema.sql"
DB_PATH = Path(os.environ.get("DB_PATH", ROOT / "rmfrp.db"))
WEAPONS_DIR = ROOT / "data" / "weapons"
CRIT_TABLES_DIR = ROOT / "data" / "crit_tables"
FUMBLE_TABLES_DIR = ROOT / "data" / "fumble_tables"
SPELL_LISTS_DIR = ROOT / "data" / "spell_lists"

CELL_RE = re.compile(r"^(\d{1,3})([A-F])([GKPSTU])?$")  # severity-only crit_type optional; F is the special dual-crit code on table 3.10


# ---------------------------------------------------------------------------
# generic helpers
# ---------------------------------------------------------------------------

def parse_meta_line(line: str) -> tuple[str, str] | None:
    if not line.startswith("@"):
        return None
    key, _, value = line[1:].partition(":")
    return key.strip(), value.strip()


def parse_roll(label: str) -> tuple[int, int]:
    if "-" in label:
        lo, hi = label.split("-", 1)
        return int(lo), int(hi)
    n = int(label)
    return n, n


def parse_int_range(text: str) -> tuple[int | None, int | None]:
    """Parse '01 - 05' (range) or '01' (single value, treated as one-roll range)."""
    m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"^\s*(\d+)\s*$", text)
    if m:
        n = int(m.group(1))
        return n, n
    return None, None


def parse_float_range(text: str) -> tuple[float | None, float | None]:
    m = re.match(r"^\s*([\d.]+)\s*-\s*([\d.]+)\s*$", text)
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


# ---------------------------------------------------------------------------
# attack-table cell parsing
# ---------------------------------------------------------------------------

def parse_cell(raw: str) -> tuple[int, str | None, str | None, int]:
    """Decompose a chart cell.

    Returns (hits, crit_severity, crit_type, is_fumble).
        "-"    -> (0,  None, None, 0)
        "F"    -> (0,  None, None, 1)
        "13"   -> (13, None, None, 0)
        "1A"   -> (1,  'A',  None, 0)   # severity-only (Sweeps style)
        "19EK" -> (19, 'E',  'K',  0)
    """
    if raw == "-":
        return 0, None, None, 0
    if raw == "F":
        return 0, None, None, 1
    if raw.isdigit():
        return int(raw), None, None, 0
    m = CELL_RE.match(raw)
    if not m:
        raise ValueError(f"Cannot parse attack cell {raw!r}")
    hits, sev, ctype = m.groups()
    return int(hits), sev, ctype, 0


# ---------------------------------------------------------------------------
# weapon (attack-table) loader
# ---------------------------------------------------------------------------

def parse_weapon_file(path: Path) -> dict:
    meta: dict[str, str] = {}
    rows: list[tuple[str, list[str]]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        kv = parse_meta_line(s)
        if kv:
            meta[kv[0]] = kv[1]
            continue
        if "|" in s:
            label, _, cells_text = s.partition("|")
            cells = cells_text.split()
            if len(cells) != 20:
                raise ValueError(
                    f"{path.name}: row {label.strip()!r} has {len(cells)} cells, expected 20"
                )
            rows.append((label.strip(), cells))
    return {"meta": meta, "rows": rows}


def lookup_crit_table_id(conn: sqlite3.Connection, name: str | None) -> int | None:
    if not name:
        return None
    row = conn.execute(
        "SELECT crit_table_id FROM critical_strike_table WHERE name = ?", (name,)
    ).fetchone()
    if row is None:
        raise ValueError(f"Referenced crit table not found: {name!r} (load crit tables first)")
    return row[0]


def insert_weapon(conn: sqlite3.Connection, data: dict) -> int:
    meta = data["meta"]
    length_min, length_max = parse_float_range(meta.get("length_ft", ""))
    weight_min, weight_max = parse_float_range(meta.get("weight_lb", ""))

    fumble_text = meta.get("fumble_range", "")
    fumble_unmodified = 0
    if fumble_text.upper().endswith("UM"):
        fumble_unmodified = 1
        fumble_text = fumble_text[:-2].strip()
    fumble_min, fumble_max = parse_int_range(fumble_text)

    strength_text = meta.get("strength", "")
    m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*([a-zA-Z]+)?\s*$", strength_text)
    strength_min = int(m.group(1)) if m else None
    strength_max = int(m.group(2)) if m else None
    strength_flag = m.group(3) if m else None

    range_modifiers = meta.get("range_modifiers", "").strip()
    if range_modifiers in ("", "-", "—"):
        range_modifiers = None

    two_handed = 1 if meta.get("two_handed", "no").lower() in ("yes", "true", "1") else 0
    default_crit_table_id = lookup_crit_table_id(conn, meta.get("default_crit_table"))

    fumble_table_name = (meta.get("fumble_table") or "").strip() or None
    fumble_column_index = None
    if meta.get("fumble_column"):
        try:
            fumble_column_index = int(meta["fumble_column"])
        except ValueError:
            raise ValueError(f"weapon {meta['name']!r}: fumble_column must be an integer")

    if fumble_table_name:
        ok = conn.execute(
            "SELECT 1 FROM fumble_table WHERE name = ?", (fumble_table_name,)
        ).fetchone()
        if not ok:
            raise ValueError(
                f"weapon {meta['name']!r}: fumble_table {fumble_table_name!r} "
                "not loaded (load fumble tables before weapons)"
            )
        if fumble_column_index is not None:
            okc = conn.execute(
                "SELECT 1 FROM fumble_table_column WHERE fumble_table_id = "
                "(SELECT fumble_table_id FROM fumble_table WHERE name = ?) "
                "AND col_index = ?",
                (fumble_table_name, fumble_column_index),
            ).fetchone()
            if not okc:
                raise ValueError(
                    f"weapon {meta['name']!r}: fumble_column {fumble_column_index} "
                    f"not defined on {fumble_table_name!r}"
                )

    degree_term = (meta.get("degree_term") or "").strip() or None

    cur = conn.execute(
        """
        INSERT INTO weapon
            (name, attack_table, is_two_handed, length_min_ft, length_max_ft,
             weight_min_lb, weight_max_lb, fumble_min, fumble_max, fumble_unmodified,
             strength_min, strength_max, strength_flag, range_modifiers,
             default_crit_table_id, fumble_table_name, fumble_column_index,
             degree_term)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (meta["name"], meta["attack_table"], two_handed,
         length_min, length_max, weight_min, weight_max,
         fumble_min, fumble_max, fumble_unmodified,
         strength_min, strength_max, strength_flag, range_modifiers,
         default_crit_table_id, fumble_table_name, fumble_column_index,
         degree_term),
    )
    weapon_id = cur.lastrowid

    for tok in re.split(r"[,\s]+", meta.get("breakage_nums", "")):
        tok = tok.strip()
        if not tok or tok in ("-", "—"):
            continue
        if not tok.isdigit():
            # Non-numeric breakage spec (e.g. "Auto" for the Composite Bow).
            # Skip the per-number table; the literal text is preserved on the
            # data file as @breakage_nums metadata for reference.
            continue
        conn.execute(
            "INSERT INTO weapon_breakage_number (weapon_id, breakage_number) VALUES (?, ?)",
            (weapon_id, int(tok)),
        )

    for degree in (1, 2, 3, 4):
        v = meta.get(f"max_degree_{degree}")
        if v:
            conn.execute(
                "INSERT INTO attack_table_size_cap (weapon_id, degree, max_roll) VALUES (?, ?, ?)",
                (weapon_id, degree, int(v)),
            )
    return weapon_id


def insert_chart(conn: sqlite3.Connection, weapon_id: int, rows: list) -> int:
    inserted = 0
    for label, cells in rows:
        roll_min, roll_max = parse_roll(label)
        for idx, raw in enumerate(cells):
            armor_type = 20 - idx
            hits, sev, ctype, is_fumble = parse_cell(raw)
            conn.execute(
                """
                INSERT INTO attack_result
                    (weapon_id, roll_min, roll_max, armor_type, raw,
                     hits, crit_severity, crit_type, is_fumble)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (weapon_id, roll_min, roll_max, armor_type, raw,
                 hits, sev, ctype, is_fumble),
            )
            inserted += 1
    return inserted


# ---------------------------------------------------------------------------
# crit-table loader
# ---------------------------------------------------------------------------

# Effect-code parsing. The codes use these symbols:
#   π  must parry  (Nπ = must parry N rounds; "π" alone = 1)
#   ∏  no parry    (N∏ = no parry for N rounds)
#   ∑  stun        (N∑ = stunned N rounds)
#   ∫  bleed       (N∫ = bleed N hits/round)
# Also: +NH (extra hits), (-N) foe penalty, (+N) attacker bonus, "—" no effect.
SYMBOLS = {
    "parry":     "π",
    "no_parry":  "∏",
    "stun":      "∑",
    "bleed":     "∫",
}


def _opt_count(token: str, symbol: str) -> int | None:
    """If `symbol` appears in `token`, return the leading integer (default 1).
    Returns None if symbol not present.
    """
    pat = re.compile(r"(\d+)?" + re.escape(symbol))
    m = pat.search(token)
    if not m:
        return None
    return int(m.group(1)) if m.group(1) else 1


def parse_effect_code(raw: str) -> dict:
    """Best-effort decomposition of an effect-code string.

    Recognised tokens (separated by ' – ', em/en dashes, or commas):
        +NH         -> extra_hits = N
        Nπ / π      -> parry_rounds
        N∏ / ∏      -> no_parry_rounds
        N∑ / ∑      -> stun_rounds
        N∫ / ∫      -> bleed_per_round
        (-N)        -> foe_penalty = N
        (+N)        -> attacker_bonus = N
        —, "" or unknown -> left in special_text
    """
    out: dict = {
        "extra_hits": None, "parry_rounds": None, "no_parry_rounds": None,
        "stun_rounds": None, "bleed_per_round": None,
        "foe_penalty": None, "attacker_bonus": None, "special_text": None,
    }
    if not raw or raw.strip() in ("—", "-"):
        return out

    s = raw.replace("–", "-").replace("—", "-")
    # split on " - " separators (preserving (-N)/(+N) parenthesised groups)
    parts: list[str] = []
    depth = 0
    cur = ""
    for ch in s:
        if ch == "(":
            depth += 1
            cur += ch
        elif ch == ")":
            depth -= 1
            cur += ch
        elif ch == "-" and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    parts.append(cur.strip())
    parts = [p for p in parts if p]

    leftover: list[str] = []
    for p in parts:
        m = re.match(r"^\+(\d+)H$", p)
        if m:
            out["extra_hits"] = (out["extra_hits"] or 0) + int(m.group(1))
            continue
        m = re.match(r"^\(\+(\d+)\)$", p)
        if m:
            out["attacker_bonus"] = int(m.group(1))
            continue
        m = re.match(r"^\(-(\d+)\)$", p)
        if m:
            out["foe_penalty"] = int(m.group(1))
            continue

        matched_any = False
        for key, sym in SYMBOLS.items():
            if sym in p:
                v = _opt_count(p, sym)
                if v is not None:
                    out_key = {
                        "parry": "parry_rounds", "no_parry": "no_parry_rounds",
                        "stun": "stun_rounds",   "bleed": "bleed_per_round",
                    }[key]
                    out[out_key] = (out[out_key] or 0) + v
                    matched_any = True
        if matched_any:
            # also keep tokens like "(π-25)" in special_text since the -25 is a penalty
            extras = re.findall(r"\(?[+-]?\d+\)?", p)
            extras = [e for e in extras
                      if not re.fullmatch(r"\d+", e)  # drop bare counts (handled above)
                      and not (e.startswith("(") and re.fullmatch(r"\(\+?\d+\)|\(\-\d+\)", e))]
            if extras:
                out["special_text"] = (out["special_text"] + "; " if out["special_text"] else "") + p
            continue

        leftover.append(p)

    if leftover:
        prev = out["special_text"]
        out["special_text"] = (prev + "; " if prev else "") + " – ".join(leftover)
    return out


def parse_crit_table_file(path: Path) -> dict:
    meta: dict[str, str] = {}
    cells: list[dict] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        kv = parse_meta_line(line.strip())
        if kv:
            meta[kv[0]] = kv[1]
            continue
        # Cell line: roll | severity | narrative | effect_code [| condition]
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            raise ValueError(f"{path.name}: bad cell line {line!r}")
        roll, sev, narrative, effect_code = parts[0], parts[1], parts[2], parts[3]
        condition = parts[4] if len(parts) >= 5 and parts[4] else None
        cells.append({
            "roll": roll, "severity": sev,
            "narrative": narrative, "effect_code": effect_code,
            "condition": condition,
        })
    return {"meta": meta, "cells": cells}


def insert_crit_table(conn: sqlite3.Connection, data: dict) -> tuple[int, int]:
    meta = data["meta"]
    column_axis = meta.get("column_axis", "severity").strip() or "severity"
    cur = conn.execute(
        """INSERT INTO critical_strike_table
               (name, table_number, crit_type_code, column_axis, notes)
           VALUES (?, ?, ?, ?, ?)""",
        (meta["name"], meta["table_number"],
         meta.get("crit_type_code") or None,
         column_axis,
         meta.get("notes") or None),
    )
    crit_table_id = cur.lastrowid

    seen_results: set[tuple[int, str]] = set()
    n_results = 0
    n_effects = 0
    for cell in data["cells"]:
        roll_min, roll_max = parse_roll(cell["roll"])
        sev = cell["severity"]
        key = (roll_min, sev)
        if key not in seen_results:
            narrative = cell["narrative"]
            if narrative and narrative.strip().upper().startswith("TODO"):
                narrative = None
            conn.execute(
                """INSERT INTO critical_result
                       (crit_table_id, roll_min, roll_max, severity, narrative)
                   VALUES (?, ?, ?, ?, ?)""",
                (crit_table_id, roll_min, roll_max, sev, narrative),
            )
            seen_results.add(key)
            n_results += 1
        eff = parse_effect_code(cell["effect_code"])
        conn.execute(
            """INSERT INTO critical_result_effect
                   (crit_table_id, roll_min, severity, condition, raw_code,
                    extra_hits, parry_rounds, no_parry_rounds, stun_rounds,
                    bleed_per_round, foe_penalty, attacker_bonus, special_text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (crit_table_id, roll_min, sev, cell["condition"], cell["effect_code"],
             eff["extra_hits"], eff["parry_rounds"], eff["no_parry_rounds"],
             eff["stun_rounds"], eff["bleed_per_round"],
             eff["foe_penalty"], eff["attacker_bonus"], eff["special_text"]),
        )
        n_effects += 1
    return n_results, n_effects


# ---------------------------------------------------------------------------
# fumble-table loader
# ---------------------------------------------------------------------------

def parse_fumble_table_file(path: Path) -> dict:
    meta: dict[str, str] = {}
    columns: dict[int, str] = {}
    cells: list[dict] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        kv = parse_meta_line(line.strip())
        if kv:
            k, v = kv
            m = re.match(r"^column_(\d+)$", k)
            if m:
                columns[int(m.group(1))] = v
            else:
                meta[k] = v
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            raise ValueError(f"{path.name}: bad fumble cell line {line!r}")
        cells.append({
            "roll": parts[0], "col_index": int(parts[1]),
            "narrative": parts[2] if parts[2] else None,
        })
    return {"meta": meta, "columns": columns, "cells": cells}


def insert_fumble_table(conn: sqlite3.Connection, data: dict) -> tuple[int, int, int]:
    meta = data["meta"]
    cur = conn.execute(
        "INSERT INTO fumble_table (name, table_number, notes) VALUES (?, ?, ?)",
        (meta["name"], meta["table_number"], meta.get("notes") or None),
    )
    fumble_table_id = cur.lastrowid

    n_cols = 0
    for col_index in sorted(data["columns"]):
        conn.execute(
            "INSERT INTO fumble_table_column (fumble_table_id, col_index, col_name) VALUES (?, ?, ?)",
            (fumble_table_id, col_index, data["columns"][col_index]),
        )
        n_cols += 1

    n_cells = 0
    for cell in data["cells"]:
        roll_min, roll_max = parse_roll(cell["roll"])
        narrative = cell["narrative"]
        if narrative and narrative.strip().upper().startswith("TODO"):
            narrative = None
        conn.execute(
            """INSERT INTO fumble_result
                   (fumble_table_id, roll_min, roll_max, col_index, narrative)
               VALUES (?, ?, ?, ?, ?)""",
            (fumble_table_id, roll_min, roll_max, cell["col_index"], narrative),
        )
        n_cells += 1
    return n_cols, n_cells, len({(c["roll"]) for c in data["cells"]})


# ---------------------------------------------------------------------------
# spell-list loader (Phase 1: summary chart + class index)
# ---------------------------------------------------------------------------

def parse_spell_list_file(path: Path) -> dict:
    """Parse a data/spell_lists/<realm>/<slug>.txt file.

    Two sections:
      - Top: @meta lines + pipe-separated chart rows (Phase 1 format).
      - Optional `# Descriptions` block with `@@ <level>` markers
        followed by free-form narrative text (Phase 2 format).

    Returns {"meta", "spells": [(level,name,area,dur,range,type,starred)],
             "descriptions": {level: text}}.
    """
    meta: dict[str, str] = {}
    spells: list[tuple[int, str, str, str, str, str, int]] = []
    descs: dict[int, list[str]] = {}
    current_desc_level: int | None = None

    for raw in path.read_text(encoding="utf-8").splitlines():
        s_raw = raw  # preserve for description body
        s = raw.strip()
        # Inside a description block, preserve raw lines (incl. blank lines)
        # until the next `@@` marker or another structural break.
        if current_desc_level is not None:
            if s.startswith("@@ "):
                try:
                    current_desc_level = int(s[3:].strip())
                    descs.setdefault(current_desc_level, [])
                    continue
                except ValueError:
                    current_desc_level = None  # malformed marker → exit block
            elif not s or s.startswith("#"):
                # Blank line within a description block separates paragraphs.
                # Two consecutive blanks end the block (treat as section break).
                if not s:
                    descs[current_desc_level].append("")
                continue
            else:
                descs[current_desc_level].append(s_raw.rstrip())
                continue

        if not s or s.startswith("#"):
            continue
        # Description-block opener must be checked BEFORE parse_meta_line,
        # since "@@ N" also satisfies parse_meta_line's "starts with @" rule
        # and would otherwise be misread as a meta entry with key "@ N".
        if s.startswith("@@ "):
            try:
                current_desc_level = int(s[3:].strip())
                descs.setdefault(current_desc_level, [])
            except ValueError:
                pass
            continue
        kv = parse_meta_line(s)
        if kv:
            meta[kv[0]] = kv[1]
            continue
        if "|" not in s:
            continue
        parts = [p.strip() for p in s.split("|")]
        if len(parts) < 6:
            raise ValueError(f"{path.name}: bad spell row {s!r}")
        try:
            level = int(parts[0])
        except ValueError:
            continue
        raw_name = parts[1]
        starred = 1 if raw_name.endswith("*") else 0
        name = raw_name.rstrip("* ").rstrip() if starred else raw_name
        spells.append((
            level, name,
            parts[2] or None,
            parts[3] or None,
            parts[4] or None,
            parts[5] or None,
            starred,
        ))

    # Collapse description chunks into a single string per level (trim trailing
    # blank lines).
    descriptions: dict[int, str] = {}
    for lvl, chunks in descs.items():
        # Join with newline, collapse runs of blank lines, strip ends.
        text = "\n".join(chunks).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        if text:
            descriptions[lvl] = text

    return {"meta": meta, "spells": spells, "descriptions": descriptions}


def parse_class_index_file(path: Path) -> dict:
    """Parse a data/spell_lists/<realm>_classes.txt file."""
    meta: dict[str, str] = {}
    pairs: list[tuple[str, str]] = []  # (class_name, list_name)
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        kv = parse_meta_line(s)
        if kv:
            meta[kv[0]] = kv[1]
            continue
        if "|" in s:
            cls, lst = [p.strip() for p in s.split("|", 1)]
            if cls and lst:
                pairs.append((cls, lst))
    return {"meta": meta, "pairs": pairs}


def insert_spell_lists(conn: sqlite3.Connection) -> tuple[int, int, int, int]:
    """Walk data/spell_lists/<realm>/, load all spell lists + class index files.

    Auto-grants every Channeling class access to every Open and Closed list
    declared in that realm (the source PDF's convention).
    Returns (realms_loaded, lists_loaded, spells_loaded, memberships).
    """
    if not SPELL_LISTS_DIR.exists():
        return (0, 0, 0, 0)

    n_realms = n_lists = n_spells = n_memberships = 0

    # A directory under spell_lists/ is one realm. The sibling file
    # <realm>_classes.txt is its class-to-list index.
    for realm_dir in sorted(SPELL_LISTS_DIR.iterdir()):
        if not realm_dir.is_dir():
            continue
        realm_name = realm_dir.name.replace("_", " ").title()
        # Insert (or reuse) realm row.
        cur = conn.execute(
            "INSERT OR IGNORE INTO spell_realm (name) VALUES (?)", (realm_name,)
        )
        realm_id = conn.execute(
            "SELECT realm_id FROM spell_realm WHERE name = ?", (realm_name,)
        ).fetchone()[0]
        n_realms += 1

        # Pass 1: insert all spell lists (so the class index can reference them).
        list_id_by_name: dict[str, int] = {}
        open_ids: list[int] = []
        closed_ids: list[int] = []
        for f in sorted(realm_dir.glob("*.txt")):
            data = parse_spell_list_file(f)
            m = data["meta"]
            cur = conn.execute(
                "INSERT INTO spell_list (realm_id, name, list_number, category) "
                "VALUES (?, ?, ?, ?)",
                (realm_id, m["name"], m.get("number"), m["category"]),
            )
            list_id = cur.lastrowid
            list_id_by_name[m["name"]] = list_id
            n_lists += 1
            if m["category"] == "Open":
                open_ids.append(list_id)
            elif m["category"] == "Closed":
                closed_ids.append(list_id)

            for level, name, area, dur, rng, typ, starred in data["spells"]:
                desc = data["descriptions"].get(level)
                conn.execute(
                    "INSERT INTO spell "
                    "(list_id, level, name, area_effect, duration, range_str, "
                    " spell_type, starred, description) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (list_id, level, name, area, dur, rng, typ, starred, desc),
                )
                n_spells += 1

        # Pass 2: class index — populates spell_class + class_spell_list. Every
        # declared class also gets Open + Closed list memberships.
        class_index = SPELL_LISTS_DIR / f"{realm_dir.name}_classes.txt"
        declared_classes: set[str] = set()
        if class_index.is_file():
            idx = parse_class_index_file(class_index)
            for class_name, list_name in idx["pairs"]:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO spell_class (name, realm_id) "
                    "VALUES (?, ?)",
                    (class_name, realm_id),
                )
                class_id = conn.execute(
                    "SELECT class_id FROM spell_class WHERE name = ?",
                    (class_name,),
                ).fetchone()[0]
                declared_classes.add(class_name)
                if list_name not in list_id_by_name:
                    raise ValueError(
                        f"{class_index.name}: class {class_name!r} references "
                        f"unknown list {list_name!r}"
                    )
                conn.execute(
                    "INSERT OR IGNORE INTO class_spell_list (class_id, list_id) "
                    "VALUES (?, ?)",
                    (class_id, list_id_by_name[list_name]),
                )
                n_memberships += 1

            # Auto-grant Open + Closed to every declared class in this realm.
            for class_name in declared_classes:
                class_id = conn.execute(
                    "SELECT class_id FROM spell_class WHERE name = ?",
                    (class_name,),
                ).fetchone()[0]
                for lid in open_ids + closed_ids:
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO class_spell_list (class_id, list_id) "
                        "VALUES (?, ?)",
                        (class_id, lid),
                    )
                    if cur.rowcount:
                        n_memberships += 1

    return (n_realms, n_lists, n_spells, n_memberships)


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def init_db(reset: bool) -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true", help="delete existing DB before loading")
    args = p.parse_args()

    conn = init_db(reset=args.reset)

    crit_loaded: list[tuple[str, int, int]] = []
    if CRIT_TABLES_DIR.exists():
        for f in sorted(CRIT_TABLES_DIR.glob("*.txt")):
            data = parse_crit_table_file(f)
            n_res, n_eff = insert_crit_table(conn, data)
            crit_loaded.append((data["meta"]["name"], n_res, n_eff))

    fumble_loaded: list[tuple[str, int, int, int]] = []
    if FUMBLE_TABLES_DIR.exists():
        for f in sorted(FUMBLE_TABLES_DIR.glob("*.txt")):
            data = parse_fumble_table_file(f)
            n_cols, n_cells, n_rows = insert_fumble_table(conn, data)
            fumble_loaded.append((data["meta"]["name"], n_rows, n_cols, n_cells))

    weapons_loaded: list[tuple[str, int, int]] = []
    if WEAPONS_DIR.exists():
        for f in sorted(WEAPONS_DIR.glob("*.txt")):
            data = parse_weapon_file(f)
            weapon_id = insert_weapon(conn, data)
            n = insert_chart(conn, weapon_id, data["rows"])
            weapons_loaded.append((data["meta"]["name"], len(data["rows"]), n))

    spell_stats = insert_spell_lists(conn)

    conn.commit()
    conn.close()

    print(f"DB written: {DB_PATH}")
    if crit_loaded:
        print("Critical strike tables:")
        for name, nr, ne in crit_loaded:
            print(f"  {name}: {nr} cells, {ne} effect rows")
    if fumble_loaded:
        print("Fumble tables:")
        for name, nr, nc, ncells in fumble_loaded:
            print(f"  {name}: {nr} rows × {nc} cols = {ncells} cells")
    if weapons_loaded:
        print("Weapons:")
        for name, rows, cells in weapons_loaded:
            print(f"  {name}: {rows} chart rows, {cells} cells")
    if spell_stats[1]:
        nr, nl, nsp, nm = spell_stats
        print(f"Spell lists: {nl} lists across {nr} realm(s), "
              f"{nsp} spells, {nm} class memberships")


if __name__ == "__main__":
    main()
