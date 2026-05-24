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
RACES_DIR = ROOT / "data" / "chargen" / "races"
SKILLS_DIR = ROOT / "data" / "skills"
CULTURES_DIR = ROOT / "data" / "chargen" / "cultures"
PROFESSIONS_DIR = ROOT / "data" / "chargen" / "professions"
TRAINING_PACKAGES_DIR = ROOT / "data" / "chargen" / "training_packages"
ADOLESCENCE_FILE = ROOT / "data" / "chargen" / "adolescence_ranks.txt"

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

# ---------------------------------------------------------------------------
# race loader (chargen reference data)
# ---------------------------------------------------------------------------

# Field aliases — race .txt files use @stat_mods / @rr_mods / @bg_opts /
# @body_dev_prog etc. Stat / RR mods are space-separated "Code=Value" pairs.
_RACE_STAT_KEYS: tuple[str, ...] = (
    "Ag", "Co", "Me", "Re", "SD", "Em", "In", "Pr", "Qu", "St",
)
_RACE_RR_KEYS: tuple[str, ...] = ("Ess", "Chan", "Ment", "Pois", "Dis")


def parse_race_file(path: Path) -> dict:
    """Parse a data/chargen/races/<slug>.txt file.

    Returns a dict ready to feed insert_race(). Validates that every
    expected @key appears and that stat/RR mod tokens cover the full set.
    """
    meta: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        kv = parse_meta_line(line)
        if kv is None:
            continue
        meta[kv[0]] = kv[1]

    for key in ("name", "slug", "stat_mods", "rr_mods", "bg_opts",
                "body_dev_prog", "chan_pp_prog", "ess_pp_prog", "ment_pp_prog"):
        if key not in meta:
            raise ValueError(f"{path.name}: missing @{key}")

    # Parse "Ag=-2 Co=+4 Me=0 ..." into a dict of code -> int.
    def _parse_mods(s: str, allowed: tuple[str, ...]) -> dict[str, int]:
        out: dict[str, int] = {}
        for tok in s.split():
            if "=" not in tok:
                raise ValueError(f"{path.name}: bad mod token {tok!r}")
            k, _, v = tok.partition("=")
            if k not in allowed:
                raise ValueError(f"{path.name}: unexpected mod key {k!r}")
            out[k] = int(v)
        missing = [k for k in allowed if k not in out]
        if missing:
            raise ValueError(f"{path.name}: missing mod keys {missing}")
        return out

    stat_mods = _parse_mods(meta["stat_mods"], _RACE_STAT_KEYS)
    rr_mods   = _parse_mods(meta["rr_mods"],   _RACE_RR_KEYS)

    return {
        "slug":          meta["slug"],
        "name":          meta["name"],
        "stat_mods":     stat_mods,
        "rr_mods":       rr_mods,
        "bg_opts":       int(meta["bg_opts"]),
        "body_dev_prog": meta["body_dev_prog"],
        "chan_pp_prog":  meta["chan_pp_prog"],
        "ess_pp_prog":   meta["ess_pp_prog"],
        "ment_pp_prog":  meta["ment_pp_prog"],
    }


def insert_race(conn: sqlite3.Connection, data: dict) -> int:
    """Upsert a race row by slug. Returns the (stable) race_id.

    Using ON CONFLICT(slug) DO UPDATE keeps race_id stable across reloads,
    which matters because characters reference race_id. (If we used DELETE
    + INSERT, the FK SET NULL on character.race_id would clear every
    character's race on every --reload-ref.)
    """
    sm = data["stat_mods"]
    rr = data["rr_mods"]
    conn.execute(
        """
        INSERT INTO race (
            slug, name,
            stat_ag, stat_co, stat_me, stat_re, stat_sd,
            stat_em, stat_in, stat_pr, stat_qu, stat_st,
            rr_ess, rr_chan, rr_ment, rr_pois, rr_dis,
            bg_opts, body_dev_prog, chan_pp_prog, ess_pp_prog, ment_pp_prog
        ) VALUES (?, ?,  ?, ?, ?, ?, ?,  ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?,  ?, ?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET
            name           = excluded.name,
            stat_ag        = excluded.stat_ag, stat_co = excluded.stat_co,
            stat_me        = excluded.stat_me, stat_re = excluded.stat_re,
            stat_sd        = excluded.stat_sd, stat_em = excluded.stat_em,
            stat_in        = excluded.stat_in, stat_pr = excluded.stat_pr,
            stat_qu        = excluded.stat_qu, stat_st = excluded.stat_st,
            rr_ess         = excluded.rr_ess,  rr_chan = excluded.rr_chan,
            rr_ment        = excluded.rr_ment, rr_pois = excluded.rr_pois,
            rr_dis         = excluded.rr_dis,
            bg_opts        = excluded.bg_opts,
            body_dev_prog  = excluded.body_dev_prog,
            chan_pp_prog   = excluded.chan_pp_prog,
            ess_pp_prog    = excluded.ess_pp_prog,
            ment_pp_prog   = excluded.ment_pp_prog
        """,
        (
            data["slug"], data["name"],
            sm["Ag"], sm["Co"], sm["Me"], sm["Re"], sm["SD"],
            sm["Em"], sm["In"], sm["Pr"], sm["Qu"], sm["St"],
            rr["Ess"], rr["Chan"], rr["Ment"], rr["Pois"], rr["Dis"],
            data["bg_opts"],
            data["body_dev_prog"], data["chan_pp_prog"],
            data["ess_pp_prog"], data["ment_pp_prog"],
        ),
    )
    row = conn.execute(
        "SELECT race_id FROM race WHERE slug = ?", (data["slug"],)
    ).fetchone()
    return row[0]


def insert_races(conn: sqlite3.Connection) -> int:
    """Load every data/chargen/races/<slug>.txt into the race table."""
    if not RACES_DIR.exists():
        return 0
    n = 0
    for f in sorted(RACES_DIR.glob("*.txt")):
        data = parse_race_file(f)
        insert_race(conn, data)
        n += 1
    return n


# ---------------------------------------------------------------------------
# skills loader (RMSS Appendix A-1)
# ---------------------------------------------------------------------------

# Field labels at category-block level.
_SKILL_CATEGORY_FIELDS: tuple[str, ...] = (
    "skills", "restricted", "stat_bonuses", "rank_progression",
    "category_progression", "group", "classification", "description",
)
# Field labels at the file-header level.
_SKILL_HEADER_FIELDS: tuple[str, ...] = (
    "section", "group_name", "page_div", "page_content",
)


def parse_skill_file(path: Path) -> dict:
    """Parse a data/skills/<slug>.txt into structured form.

    A sidecar file `<slug>.sohk.json` is loaded alongside when present;
    its `skills` dict (keyed by skill name) populates each skill's
    `sohk_data` field, and its `categories` dict populates each
    category's `sohk_notes`. Sidecar absence is fine — both fields
    default to empty.

    Returns:
        {
          "slug": "...", "section": "A-1.X", "name": "...",
          "page_div": int, "page_content": int,
          "categories": [{name, sohk_notes, fields...}, ...],
          "skills":     [{name, stat, description, sohk_data}, ...],
          "tables":     [{name, columns, general_mods: [...], rows: [...]}],
        }
    """
    slug = path.stem
    header: dict[str, str] = {}
    categories: list[dict] = []
    skills: list[dict] = []
    tables: list[dict] = []
    # States: header | category | skill | table | general_mods. The
    # general_mods state captures the flat list of "Label: value" lines
    # following a `@general_mods:` marker, and attaches them to the most
    # recently opened table.
    state: str = "header"
    current: dict | None = None
    multiline_field: str | None = None
    gm_target: dict | None = None   # the table dict that owns the active general_mods block

    def finalize():
        nonlocal current, multiline_field
        if current is None:
            return
        if state == "category":
            categories.append(current)
        elif state == "skill":
            skills.append(current)
        elif state == "table":
            tables.append(current)
        current = None
        multiline_field = None

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            multiline_field = None
            # Blank line inside a general_mods block ends it.
            if state == "general_mods":
                state = "header"
                gm_target = None
            continue

        # General-mod list entries: flush-left "Label: value" lines that
        # follow a `@general_mods:` marker. Stop when we hit another @-line.
        if state == "general_mods" and not line.startswith("@") and gm_target is not None:
            gm_target.setdefault("general_mods", []).append(line.strip())
            continue

        # Multi-line continuation: any leading-whitespace line that isn't
        # a known @-marker extends the most recently opened @description /
        # @columns value. (Originally required 2+ spaces — relaxed to 1+
        # to tolerate post-cleanup files where multi-space indentation
        # was collapsed by the whitespace pass.)
        if (line.startswith(" ") and not line.lstrip().startswith("@")
                and multiline_field is not None and current is not None):
            current[multiline_field] = (
                current.get(multiline_field, "") + " " + line.strip()
            ).strip()
            continue

        if line.startswith("@@ "):
            # Start of a skill description block.
            finalize()
            state = "skill"
            current = {"name": line[3:].strip(), "stat": "", "description": ""}
            multiline_field = None
            gm_target = None
            continue

        if line.startswith("@table:"):
            finalize()
            state = "table"
            current = {
                "name": line.split(":", 1)[1].strip(),
                "columns": "",
                "general_mods": [],
                "rows": [],
            }
            multiline_field = None
            gm_target = None
            continue

        if line.startswith("@columns:") and state == "table" and current is not None:
            current["columns"] = line.split(":", 1)[1].strip()
            continue

        if line.startswith("@general_mods:"):
            # The block that follows belongs to the most recently *seen*
            # table. If state is currently "table", that's `current` —
            # finalize it into the tables list first so subsequent rows
            # can't accidentally land on it, and remember the table dict
            # so we can append into its general_mods list.
            if state == "table" and current is not None:
                tables.append(current)
                gm_target = current
                current = None
            elif tables:
                gm_target = tables[-1]
            else:
                gm_target = None
            state = "general_mods"
            multiline_field = None
            # Any inline value on the marker line itself (rare) becomes an entry.
            inline = line.split(":", 1)[1].strip()
            if inline and gm_target is not None:
                gm_target.setdefault("general_mods", []).append(inline)
            continue

        # A table-row line is anything inside a @table block that has " | "
        # — we split on pipe.
        if state == "table" and " | " in line and current is not None:
            cells = [c.strip() for c in line.split("|")]
            # Header columns are "roll | result | percent | time | mod | description"
            cols = [c.strip() for c in (current["columns"] or "").split("|")]
            row = {c: cells[i] if i < len(cells) else ""
                   for i, c in enumerate(cols)}
            current["rows"].append(row)
            continue

        if line.startswith("@category:"):
            finalize()
            state = "category"
            current = {
                "name": line.split(":", 1)[1].strip(),
                "skills": "", "restricted": "", "stat_bonuses": "",
                "rank_progression": "", "category_progression": "",
                "group": "", "classification": "", "description": "",
            }
            multiline_field = None
            gm_target = None
            continue

        if line.startswith("@"):
            key, _, value = line[1:].partition(":")
            key = key.strip()
            value = value.strip()
            if state in ("header", "category", "skill") and current is not None:
                # Field assignment within the active block.
                if key in current:
                    current[key] = value
                    # Allow multi-line continuation for description-style fields.
                    if value == "" and key in ("description",):
                        multiline_field = key
            elif state == "header":
                # File-level header field.
                if key in _SKILL_HEADER_FIELDS:
                    header[key] = value
            else:
                # Unknown — ignore.
                pass
            continue
        # else: ignore stray line

    finalize()

    # Sidecar: <slug>.sohk.json. When present, weave its per-skill /
    # per-category / group-level data into the structures we just
    # parsed. Failures are loud — a missing key or malformed JSON
    # should surface, not silently lose data.
    sohk_sidecar = path.with_suffix(".sohk.json")
    group_sohk_notes = ""
    if sohk_sidecar.exists():
        import json
        sohk = json.loads(sohk_sidecar.read_text(encoding="utf-8"))
        for sk in skills:
            payload = sohk.get("skills", {}).get(sk["name"])
            if payload:
                sk["sohk_data"] = payload
        for cat in categories:
            note = sohk.get("categories", {}).get(cat["name"])
            if note:
                cat["sohk_notes"] = note
        # Group-level prose from SOHK Section 5.
        group_sohk_notes = sohk.get("group_notes", "") or ""

    return {
        "slug": slug,
        "section": header.get("section", ""),
        "name": header.get("group_name", slug),
        "page_div": int(header.get("page_div") or 0),
        "page_content": int(header.get("page_content") or 0),
        "sohk_notes": group_sohk_notes,
        "categories": categories,
        "skills": skills,
        "tables": tables,
    }


def insert_skill_group(conn: sqlite3.Connection, data: dict) -> int:
    """Insert one skill_category_group + its categories/skills/tables.

    Returns the group_id. Designed to be called repeatedly with the
    reference-data wipe handled by the caller (REF_TABLES_DELETE_ORDER).
    """
    cur = conn.execute(
        "INSERT INTO skill_category_group "
        "(slug, section, name, page_div, page_content, sohk_notes) "
        "VALUES (?, ?, ?, ?, ?, ?) RETURNING group_id",
        (data["slug"], data["section"], data["name"],
         data["page_div"], data["page_content"],
         data.get("sohk_notes", "")),
    )
    group_id = cur.fetchone()[0]
    import json as _json
    for cat in data["categories"]:
        conn.execute(
            """INSERT INTO skill_category (
                group_id, name, skills_list, restricted, stat_bonuses,
                rank_progression, category_progression, parent_group,
                classification, description, sohk_notes
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (group_id, cat["name"], cat.get("skills", ""), cat.get("restricted", ""),
             cat.get("stat_bonuses", ""), cat.get("rank_progression", ""),
             cat.get("category_progression", ""), cat.get("group", ""),
             cat.get("classification", ""), cat.get("description", ""),
             cat.get("sohk_notes", "")),
        )
    for sk in data["skills"]:
        # sohk_data comes through as a dict (from the sidecar) or
        # missing (no SOHK entry). Serialise to JSON either way.
        sohk_payload = sk.get("sohk_data") or {}
        sohk_json = _json.dumps(sohk_payload, ensure_ascii=False) if sohk_payload else "{}"
        conn.execute(
            "INSERT OR IGNORE INTO skill (group_id, name, stat, description, sohk_data) "
            "VALUES (?, ?, ?, ?, ?)",
            (group_id, sk["name"], sk.get("stat", ""), sk.get("description", ""),
             sohk_json),
        )
    for t in data["tables"]:
        # general_mods is stored as newline-separated "Label: value" entries
        # (one per line, no surrounding whitespace). Empty list -> empty
        # string, which trips the NOT NULL DEFAULT '' on the column.
        gm_text = "\n".join(t.get("general_mods") or [])
        cur = conn.execute(
            "INSERT INTO skill_table (group_id, name, columns, general_mods) "
            "VALUES (?, ?, ?, ?) RETURNING table_id",
            (group_id, t["name"], t.get("columns", ""), gm_text),
        )
        table_id = cur.fetchone()[0]
        for i, row in enumerate(t["rows"]):
            conn.execute(
                """INSERT INTO skill_table_row (
                    table_id, sort_order, roll, result, percent, time, mod, description
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (table_id, i, row.get("roll", ""), row.get("result", ""),
                 row.get("percent", ""), row.get("time", ""), row.get("mod", ""),
                 row.get("description", "")),
            )
    return group_id


def insert_skills(conn: sqlite3.Connection) -> tuple[int, int, int, int]:
    """Load every data/skills/<slug>.txt. Returns (groups, categories, skills, tables)."""
    if not SKILLS_DIR.exists():
        return (0, 0, 0, 0)
    n_g = n_c = n_s = n_t = 0
    for f in sorted(SKILLS_DIR.glob("*.txt")):
        data = parse_skill_file(f)
        insert_skill_group(conn, data)
        n_g += 1
        n_c += len(data["categories"])
        n_s += len(data["skills"])
        n_t += len(data["tables"])
    return (n_g, n_c, n_s, n_t)


# ---------------------------------------------------------------------------
# culture-data loader (rich per-race fields from Cultures and Races appendix)
# ---------------------------------------------------------------------------

# Known structured field labels carried in cultures/*.txt as @<slug>: <value>.
# These map 1:1 to keys in the race.culture_data JSON object.
_CULTURE_FIELDS: tuple[str, ...] = (
    "starting_languages", "allowed_adolescence_development", "extra_languages",
    "standard_hobby_skills", "everyman", "restricted",
    "weapons", "armor", "money",
    "extra_money", "special_items", "talents",
    "prejudices", "professions", "demeanor",
    "build", "coloring", "endurance", "height", "lifespan",
    "resistance", "special_abilities",
    "clothing_decoration", "fears_inabilities", "lifestyle",
    "marriage_pattern", "religion",
)


def parse_culture_file(path: Path) -> dict:
    """Parse a data/chargen/cultures/<slug>.txt file.

    Returns {"slug": ..., "fields": {field_key: text, ...}} for the @-fields
    we know about. Unknown @-keys are ignored. @@-blocks (raw section text)
    are NOT carried into culture_data — the JSON stays focused on the
    parsed structured fields. (If the SPA later wants raw narrative, we
    can revisit.)
    """
    fields: dict[str, str] = {}
    slug = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("@") or line.startswith("@@"):
            continue
        # @key: value form. Allow extra leading spaces in value (the file
        # uses a 25-char fixed key width like "@build                    Heavy...").
        body = line[1:]
        # First whitespace separates key from value (no colon required
        # because the file uses fixed-column layout for @-fields).
        if ":" in body.split(None, 1)[0]:
            key, _, value = body.partition(":")
            key = key.strip()
            value = value.strip()
        else:
            parts = body.split(None, 1)
            key = parts[0].strip()
            value = parts[1].strip() if len(parts) > 1 else ""
        if key == "slug":
            slug = value
        elif key in _CULTURE_FIELDS:
            fields[key] = value
    return {"slug": slug, "fields": fields}


def insert_culture_data(conn: sqlite3.Connection) -> int:
    """Walk data/chargen/cultures/*.txt and update race.culture_data with
    the parsed structured fields as JSON. Races without a matching culture
    file keep culture_data = '{}'."""
    if not CULTURES_DIR.exists():
        return 0
    import json
    n = 0
    for f in sorted(CULTURES_DIR.glob("*.txt")):
        data = parse_culture_file(f)
        if not data["slug"]:
            continue
        culture_json = json.dumps(data["fields"], ensure_ascii=False)
        cur = conn.execute(
            "UPDATE race SET culture_data = ? WHERE slug = ?",
            (culture_json, data["slug"]),
        )
        if cur.rowcount:
            n += 1
    return n


# ---------------------------------------------------------------------------
# profession loader (RMSS Character Law professions, decoded from ERA)
# ---------------------------------------------------------------------------

# Sections inside data/chargen/professions/<slug>.txt. Lines under each
# section header until the next @section continue the list.
_PROFESSION_LIST_SECTIONS: tuple[str, ...] = (
    "group_bonuses",
    "category_bonuses",
    "category_costs",
    "skill_cost_modifiers",
    "favorite_skills",
)


def parse_profession_file(file_path: Path) -> dict:
    """Parse data/chargen/professions/<slug>.txt into structured form.

    Header @keys (single-line): @name, @slug, @realms, @prime_stats.
    The @description value spans multiple lines, indented under
    `@description:` like the skills/races files.

    Body sections (each is a @<section>: marker followed by one
    "key: value" line per entry until the next @-marker or EOF):
      - group_bonuses:        "Group Name: <int>"
      - category_bonuses:     "Group/Category: <int>"
      - category_costs:       "Group/Category: <cost string>"
      - skill_cost_modifiers: "Group/Category/Skill (Classification): <float>"
      - favorite_skills:      "Group/Category/Skill (Classification)"  (no value)

    The "Group/Category(/Skill)" path uses '/' as a separator everywhere
    EXCEPT for ERA-source group names that intrinsically contain a slash
    ("Science/Analytic", "Technical/Trade"). To avoid ambiguity we
    rsplit on the LAST '/' when the line has a clear "(value): N"
    trailing chunk; for category-style entries we keep ERA's verbatim
    string and rely on the build script having produced clean output.
    """
    meta: dict[str, str] = {}
    sections: dict[str, list[str]] = {s: [] for s in _PROFESSION_LIST_SECTIONS}

    current_section: str | None = None
    in_description = False
    description_lines: list[str] = []

    for raw in file_path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue

        # Multi-line continuation under @description: any leading-space line
        # that isn't itself a @-marker.
        if (in_description and line.startswith(" ")
                and not line.lstrip().startswith("@")):
            description_lines.append(line.strip())
            continue

        if line.startswith("@"):
            # Hitting a new @-marker closes the description block.
            in_description = False
            key, _, value = line[1:].partition(":")
            key = key.strip()
            value = value.strip()
            if key == "description":
                in_description = True
                current_section = None
                if value:
                    description_lines.append(value)
                continue
            if key in _PROFESSION_LIST_SECTIONS:
                current_section = key
                continue
            # Single-line header field.
            current_section = None
            meta[key] = value
            continue

        # Body line inside a list section.
        if current_section is not None:
            sections[current_section].append(line)

    description = " ".join(description_lines).strip()

    def _split_bonus_line(s: str) -> tuple[str, str]:
        """Split a 'Group/.../...: value' line on the LAST colon so the
        path keeps any colons that may appear in section labels."""
        idx = s.rfind(":")
        if idx < 0:
            return s, ""
        return s[:idx].strip(), s[idx + 1:].strip()

    def _split_path(path_str: str, parts: int) -> list[str]:
        """Split a 'Group/Category(/Skill)' string into `parts` pieces.

        ERA's group names include "Science/Analytic" and "Technical/Trade"
        which collide with our '/' separator. We split from the RIGHT so
        the rightmost N-1 '/' characters are treated as separators,
        leaving the group name (with any internal slashes) on the left.
        """
        bits = path_str.rsplit("/", parts - 1)
        # Pad with empty strings if the input was malformed.
        while len(bits) < parts:
            bits.append("")
        return [b.strip() for b in bits]

    def _split_skill_path(path_with_class: str) -> tuple[str, str, str, str]:
        """Pull "(Classification)" off the tail, then split the path into 3."""
        m = re.match(r"^(.+?)\s*\(([^)]+)\)\s*$", path_with_class)
        if not m:
            # No classification — keep classification empty.
            g, c, s = _split_path(path_with_class, 3)
            return g, c, s, ""
        path_only = m.group(1).strip()
        classification = m.group(2).strip()
        g, c, s = _split_path(path_only, 3)
        return g, c, s, classification

    group_bonuses: list[tuple[str, int]] = []
    for line in sections["group_bonuses"]:
        path, val = _split_bonus_line(line)
        try:
            group_bonuses.append((path, int(val)))
        except ValueError:
            raise ValueError(f"{path}: bad group_bonus int {val!r} on {line!r}")

    category_bonuses: list[tuple[str, str, int]] = []
    for line in sections["category_bonuses"]:
        path, val = _split_bonus_line(line)
        g, c = _split_path(path, 2)
        try:
            category_bonuses.append((g, c, int(val)))
        except ValueError:
            raise ValueError(f"bad category_bonus int {val!r} on {line!r}")

    category_costs: list[tuple[str, str, str]] = []
    for line in sections["category_costs"]:
        path, val = _split_bonus_line(line)
        g, c = _split_path(path, 2)
        category_costs.append((g, c, val))

    skill_cost_mods: list[tuple[str, str, str, str, float]] = []
    for line in sections["skill_cost_modifiers"]:
        path, val = _split_bonus_line(line)
        g, c, s, klass = _split_skill_path(path)
        try:
            mod = float(val)
        except ValueError:
            raise ValueError(f"bad skill modifier {val!r} on {line!r}")
        skill_cost_mods.append((g, c, s, klass, mod))

    favorites: list[tuple[str, str, str, str]] = []
    for line in sections["favorite_skills"]:
        # No "key: value" split; the whole line is "Group/.../Skill (Class)"
        g, c, s, klass = _split_skill_path(line)
        favorites.append((g, c, s, klass))

    def _split_csv(s: str) -> list[str]:
        return [x.strip() for x in s.split(",") if x.strip() and x.strip() != "-"]

    return {
        "name": meta.get("name", ""),
        "slug": meta.get("slug") or file_path.stem,
        # Source book tag: 'character_law' by default for legacy files
        # that pre-date the @source field. Companion-supplement files
        # (Essence Companion, SOHK, ...) carry the tag explicitly.
        "source": meta.get("source", "character_law"),
        "description": description,
        "realms":      _split_csv(meta.get("realms", "")),
        "prime_stats": _split_csv(meta.get("prime_stats", "")),
        "group_bonuses": group_bonuses,
        "category_bonuses": category_bonuses,
        "category_costs": category_costs,
        "skill_cost_modifiers": skill_cost_mods,
        "favorite_skills": favorites,
    }


def insert_profession(conn: sqlite3.Connection, data: dict) -> int:
    """Upsert one profession by slug. Returns its (stable) profession_id.

    The pattern mirrors insert_race: ON CONFLICT(slug) DO UPDATE keeps
    profession_id stable across `--reload-ref`, so character.profession_id
    survives a reload. Child rows (realms, prime stats, bonuses, costs,
    favorites) are wiped + re-inserted from the file each time."""
    slug = data["slug"]
    if not slug:
        raise ValueError(f"profession data has no slug: {data.get('name')!r}")

    img_path = PROFESSIONS_DIR / "img" / f"{slug}.png"
    portrait = f"data/chargen/professions/img/{slug}.png" if img_path.exists() else None

    conn.execute(
        """INSERT INTO profession (slug, name, description, source, portrait_path)
                VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(slug) DO UPDATE SET
                name          = excluded.name,
                description   = excluded.description,
                source        = excluded.source,
                portrait_path = excluded.portrait_path""",
        (slug, data["name"], data["description"],
         data.get("source", "character_law"), portrait),
    )
    profession_id = conn.execute(
        "SELECT profession_id FROM profession WHERE slug = ?", (slug,)
    ).fetchone()[0]

    # Wipe child tables and re-insert.
    for tbl in (
        "profession_realm",
        "profession_prime_stat",
        "profession_group_bonus",
        "profession_category_bonus",
        "profession_category_cost",
        "profession_skill_cost_modifier",
        "profession_favorite_skill",
    ):
        conn.execute(f"DELETE FROM {tbl} WHERE profession_id = ?", (profession_id,))

    for realm in data["realms"]:
        conn.execute(
            "INSERT INTO profession_realm (profession_id, realm_name) VALUES (?, ?)",
            (profession_id, realm),
        )
    for stat in data["prime_stats"]:
        conn.execute(
            "INSERT INTO profession_prime_stat (profession_id, stat_code) VALUES (?, ?)",
            (profession_id, stat),
        )
    for group_name, bonus in data["group_bonuses"]:
        conn.execute(
            "INSERT INTO profession_group_bonus (profession_id, group_name, bonus) "
            "VALUES (?, ?, ?)",
            (profession_id, group_name, bonus),
        )
    for g, c, b in data["category_bonuses"]:
        conn.execute(
            "INSERT INTO profession_category_bonus "
            "(profession_id, group_name, category_name, bonus) "
            "VALUES (?, ?, ?, ?)",
            (profession_id, g, c, b),
        )
    for g, c, cost in data["category_costs"]:
        conn.execute(
            "INSERT INTO profession_category_cost "
            "(profession_id, group_name, category_name, cost) "
            "VALUES (?, ?, ?, ?)",
            (profession_id, g, c, cost),
        )
    for g, c, s, klass, mod in data["skill_cost_modifiers"]:
        conn.execute(
            "INSERT INTO profession_skill_cost_modifier "
            "(profession_id, group_name, category_name, skill_name, "
            " classification, modifier) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (profession_id, g, c, s, klass, mod),
        )
    for i, (g, c, s, klass) in enumerate(data["favorite_skills"]):
        conn.execute(
            "INSERT INTO profession_favorite_skill "
            "(profession_id, group_name, category_name, skill_name, "
            " classification, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (profession_id, g, c, s, klass, i),
        )

    return profession_id


def insert_professions(conn: sqlite3.Connection) -> int:
    """Load every data/chargen/professions/<slug>.txt into the profession
    table + its child tables. Returns the count loaded."""
    if not PROFESSIONS_DIR.exists():
        return 0
    n = 0
    for f in sorted(PROFESSIONS_DIR.glob("*.txt")):
        data = parse_profession_file(f)
        # The file's own @slug is canonical; fall back to the stem if absent.
        if not data["slug"]:
            data["slug"] = f.stem
        insert_profession(conn, data)
        n += 1
    return n


# ---------------------------------------------------------------------------
# training-package loader (RMSS Character Law, decoded from ERA)
# ---------------------------------------------------------------------------

# Top-level @-marker sections inside a TP .txt. Anything else triggers
# parser warnings on debug runs.
_TP_LIST_SECTIONS: tuple[str, ...] = (
    "specials",
    "stat_gains",
    "profession_costs",
)


def parse_training_package_file(file_path: Path) -> dict:
    """Parse one data/chargen/training_packages/<slug>.txt.

    Output shape:
        {
          "name", "slug", "category", "default_cost", "description",
          "specials":       [{"chance": int, "description": str}, ...],
          "stat_gains":     [{"stat_code": str|None,
                              "choices":   list[str]}, ...],
          "rank_assignments": [
              {"reference_label": str|None,
               "group_name":      str|None,
               "category_name":   str|None,
               "cat_ranks":       int,
               "skill_ranks":     int,
               "cat_spread_max":  int|None,
               "skill_spread_max": int|None,
               "ranks_assigned_max": int|None,
               "category_options": [(group, category), ...],
               "skill_options":    [(skill_name, classification), ...]},
              ...
          ],
          "profession_costs": [(profession_name, cost_int), ...]
        }

    Multi-line continuation on @description: any leading-space line that
    isn't itself a @-marker extends the description.
    """
    meta: dict[str, str] = {}
    description_lines: list[str] = []
    specials: list[dict] = []
    stat_gains: list[dict] = []
    profession_costs: list[tuple[str, int]] = []
    rank_assignments: list[dict] = []

    state: str = "header"   # header | description | specials | stat_gains
                            # | profession_costs | rank_assignment

    current_ra: dict | None = None

    def open_rank_assignment(header_value: str) -> dict:
        """Header looks like:
              "<slot> | ref:Melee Weapon"
              "<slot> | Weapon/1-H Concussion"
              "<slot> | Group/With • Slash/Inside"   (slashed group names ok)
              "<slot> | (unspecified)"
        We split off the leading "<slot> | " and then decide the rest.
        """
        slot_and_rest = header_value.split("|", 1)
        kind = slot_and_rest[1].strip() if len(slot_and_rest) > 1 else ""
        ra: dict = {
            "reference_label": None,
            "group_name": None,
            "category_name": None,
            "cat_ranks": 0,
            "skill_ranks": 0,
            "cat_spread_max": None,
            "skill_spread_max": None,
            "ranks_assigned_max": None,
            "category_options": [],
            "skill_options": [],
        }
        if kind.startswith("ref:"):
            ra["reference_label"] = kind[len("ref:"):].strip()
        elif kind == "(unspecified)" or kind == "":
            pass
        else:
            # Same group/category split rule as professions: rsplit so a
            # slashed group name like "Science/Analytic" stays intact and
            # only the LAST '/' is taken as the group/category boundary.
            bits = kind.rsplit("/", 1)
            if len(bits) == 2:
                ra["group_name"], ra["category_name"] = bits[0].strip(), bits[1].strip()
            else:
                ra["group_name"] = kind.strip()
        return ra

    def parse_skill_option(value: str) -> tuple[str, str]:
        """A skill_option line is "Name (Classification)". Classification
        is empty when missing.
        """
        m = re.match(r"^(.+?)\s*\(([^)]+)\)\s*$", value)
        if m:
            return m.group(1).strip(), m.group(2).strip()
        return value.strip(), ""

    for raw in file_path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            # Blank line inside the description block ends it. Blank line
            # inside list sections is just noise.
            if state == "description":
                state = "header"
            continue

        # Description continuation lines.
        if state == "description" and line.startswith(" ") and not line.lstrip().startswith("@"):
            description_lines.append(line.strip())
            continue

        if line.startswith("@@ "):
            # Open a new rank-assignment block.
            if current_ra is not None:
                rank_assignments.append(current_ra)
            current_ra = open_rank_assignment(line[3:].strip())
            state = "rank_assignment"
            continue

        if line.startswith("@"):
            key, _, value = line[1:].partition(":")
            key = key.strip()
            value = value.strip()

            # Inside a rank assignment, every @-key extends the open RA
            # except for @description / @<list-section> / @@ which break
            # the block first.
            if state == "rank_assignment" and key not in (
                "description",
                *_TP_LIST_SECTIONS,
            ):
                if key == "cat_ranks":
                    current_ra["cat_ranks"] = int(value or "0")
                elif key == "skill_ranks":
                    current_ra["skill_ranks"] = int(value or "0")
                elif key == "cat_option":
                    bits = value.rsplit("/", 1)
                    if len(bits) == 2:
                        current_ra["category_options"].append(
                            (bits[0].strip(), bits[1].strip())
                        )
                elif key == "skill_option":
                    current_ra["skill_options"].append(parse_skill_option(value))
                elif key == "cat_spread_max":
                    current_ra["cat_spread_max"] = int(value)
                elif key == "skill_spread_max":
                    current_ra["skill_spread_max"] = int(value)
                elif key == "ranks_assigned_max":
                    current_ra["ranks_assigned_max"] = int(value)
                else:
                    # Unknown — skip silently.
                    pass
                continue

            # Otherwise we're leaving the RA block (if any) — flush it.
            if current_ra is not None:
                rank_assignments.append(current_ra)
                current_ra = None

            if key == "description":
                state = "description"
                if value:
                    description_lines.append(value)
                continue
            if key in _TP_LIST_SECTIONS:
                state = key
                continue
            # Single-line header field.
            state = "header"
            meta[key] = value
            continue

        # Body line in a list section.
        if state == "specials":
            chance_str, _, desc = line.partition("|")
            try:
                chance = int(chance_str.strip())
            except ValueError:
                continue
            specials.append({"chance": chance, "description": desc.strip()})
        elif state == "stat_gains":
            if "|" in line:
                choices = [p.strip() for p in line.split("|") if p.strip()]
                stat_gains.append({"stat_code": None, "choices": choices})
            else:
                stat_gains.append({"stat_code": line.strip(), "choices": []})
        elif state == "profession_costs":
            prof, _, cost = line.rpartition(":")
            prof = prof.strip()
            try:
                cost_int = int(cost.strip())
            except ValueError:
                continue
            if prof:
                profession_costs.append((prof, cost_int))

    # Flush a final RA if the file ended mid-block.
    if current_ra is not None:
        rank_assignments.append(current_ra)

    description = " ".join(description_lines).strip()
    try:
        default_cost = int(meta.get("default_cost", "0") or "0")
    except ValueError:
        default_cost = 0

    return {
        "name": meta.get("name", ""),
        "slug": meta.get("slug") or file_path.stem,
        "category": meta.get("category", ""),
        "description": description,
        "default_cost": default_cost,
        "specials": specials,
        "stat_gains": stat_gains,
        "rank_assignments": rank_assignments,
        "profession_costs": profession_costs,
    }


def insert_training_package(conn: sqlite3.Connection, data: dict) -> int:
    """Upsert one training package + replace its child rows. Returns
    training_package_id (stable across reloads)."""
    slug = data["slug"]
    if not slug:
        raise ValueError(f"training-package data has no slug: {data.get('name')!r}")

    conn.execute(
        """INSERT INTO training_package (slug, name, category, description, default_cost)
                VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(slug) DO UPDATE SET
                name         = excluded.name,
                category     = excluded.category,
                description  = excluded.description,
                default_cost = excluded.default_cost""",
        (slug, data["name"], data["category"], data["description"],
         data["default_cost"]),
    )
    tpid = conn.execute(
        "SELECT training_package_id FROM training_package WHERE slug = ?", (slug,)
    ).fetchone()[0]

    # Wipe + re-insert children.
    for tbl in (
        "training_package_special",
        "training_package_stat_gain_choice",
        "training_package_stat_gain",
        "training_package_ra_skill_option",
        "training_package_ra_category_option",
        "training_package_rank_assignment",
        "training_package_profession_cost",
    ):
        conn.execute(f"DELETE FROM {tbl} WHERE training_package_id = ?", (tpid,))

    for i, sp in enumerate(data["specials"]):
        conn.execute(
            "INSERT INTO training_package_special "
            "(training_package_id, sort_order, chance, description) "
            "VALUES (?, ?, ?, ?)",
            (tpid, i, sp["chance"], sp["description"]),
        )

    for i, sg in enumerate(data["stat_gains"]):
        has_choice = 1 if sg["choices"] else 0
        conn.execute(
            "INSERT INTO training_package_stat_gain "
            "(training_package_id, sort_order, stat_code, has_choice) "
            "VALUES (?, ?, ?, ?)",
            (tpid, i, sg["stat_code"], has_choice),
        )
        for choice in sg["choices"]:
            conn.execute(
                "INSERT INTO training_package_stat_gain_choice "
                "(training_package_id, sort_order, stat_code) "
                "VALUES (?, ?, ?)",
                (tpid, i, choice),
            )

    for i, ra in enumerate(data["rank_assignments"]):
        conn.execute(
            """INSERT INTO training_package_rank_assignment (
                training_package_id, sort_order,
                reference_label, group_name, category_name,
                cat_ranks, skill_ranks,
                cat_spread_max, skill_spread_max, ranks_assigned_max
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tpid, i,
             ra["reference_label"], ra["group_name"], ra["category_name"],
             ra["cat_ranks"], ra["skill_ranks"],
             ra["cat_spread_max"], ra["skill_spread_max"],
             ra["ranks_assigned_max"]),
        )
        for j, (g, c) in enumerate(ra["category_options"]):
            conn.execute(
                "INSERT INTO training_package_ra_category_option "
                "(training_package_id, sort_order, option_index, group_name, category_name) "
                "VALUES (?, ?, ?, ?, ?)",
                (tpid, i, j, g, c),
            )
        for j, (s, klass) in enumerate(ra["skill_options"]):
            conn.execute(
                "INSERT INTO training_package_ra_skill_option "
                "(training_package_id, sort_order, option_index, skill_name, classification) "
                "VALUES (?, ?, ?, ?, ?)",
                (tpid, i, j, s, klass),
            )

    for prof, cost in data["profession_costs"]:
        conn.execute(
            "INSERT INTO training_package_profession_cost "
            "(training_package_id, profession_name, cost) VALUES (?, ?, ?)",
            (tpid, prof, cost),
        )

    return tpid


def insert_training_packages(conn: sqlite3.Connection) -> int:
    """Load every data/chargen/training_packages/<slug>.txt. Returns count."""
    if not TRAINING_PACKAGES_DIR.exists():
        return 0
    n = 0
    for f in sorted(TRAINING_PACKAGES_DIR.glob("*.txt")):
        data = parse_training_package_file(f)
        insert_training_package(conn, data)
        n += 1
    return n


# ---------------------------------------------------------------------------
# adolescence rank table T-1.6 loader
# ---------------------------------------------------------------------------

def insert_adolescence_ranks(conn: sqlite3.Connection) -> int:
    """Load data/chargen/adolescence_ranks.txt into adolescence_rank.

    The .txt is tab-separated: header row = culture names, body rows =
    skill label + 16 values. The skill-DP allocator joins on (skill,
    culture_slug) to look up a character's starting rank for a given
    skill once race + culture is chosen.

    Some skill labels appear multiple times in the source (e.g.
    "1 Weapon Based on Culture/Race ‡" sits under each Weapon category).
    We prefix each leaf-skill row with its most-recent "category" row so
    the (skill, culture) primary key stays unique while preserving the
    user-meaningful label.
    """
    if not ADOLESCENCE_FILE.exists():
        return 0
    conn.execute("DELETE FROM adolescence_rank")
    lines = [
        ln for ln in ADOLESCENCE_FILE.read_text(encoding="utf-8").splitlines()
        if ln and not ln.startswith("#")
    ]
    if not lines:
        return 0
    header = lines[0].split("\t")
    if header[0] != "skill":
        raise ValueError(f"adolescence_ranks.txt: header must start with 'skill', got {header[0]!r}")
    culture_slugs = [
        re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") for name in header[1:]
    ]
    n = 0
    last_category: str | None = None
    for raw in lines[1:]:
        parts = raw.split("\t")
        if len(parts) != len(header):
            continue
        skill = parts[0].strip()
        is_category = "skill category" in skill
        if is_category:
            last_category = skill
            display = skill
        else:
            # Disambiguate duplicate leaf-skill labels by tagging with the
            # last seen category. The display string keeps both ("[Weapon
            # • Missile] 1 Weapon Based on Culture/Race ‡") so end-users
            # see context; PK uniqueness is preserved.
            if last_category and any(
                skill == "1 Weapon Based on Culture/Race ‡"
                for _ in [1]   # only the known duplicate row needs the prefix
            ):
                display = f"[{last_category}] {skill}"
            else:
                display = skill
        for i, value in enumerate(parts[1:]):
            conn.execute(
                "INSERT INTO adolescence_rank (skill, culture_slug, value) VALUES (?, ?, ?)",
                (display, culture_slugs[i], value.strip()),
            )
            n += 1
    return n


# Tables that hold REFERENCE data (loaded from data/). Safe to wipe-and-reload.
# Order matters: child tables before parents for the DELETE pass.
REF_TABLES_DELETE_ORDER: tuple[str, ...] = (
    "critical_result_effect",
    "critical_result",
    "fumble_result",
    "fumble_table_column",
    "attack_result",
    "attack_table_size_cap",
    "weapon_breakage_number",
    "weapon",
    "fumble_table",
    "critical_strike_table",
    # Skill tables (RMSS Appendix A-1). children first.
    "skill_table_row",
    "skill_table",
    "skill",
    "skill_category",
    "skill_category_group",
    # Spell tables. The web explorer's PUT handler stamps spell.updated_at +
    # updated_by_user_id, but those are derived metadata — the canonical data
    # lives in data/spell_lists/<realm>/*.txt and re-inserting from there
    # restores the truth (audit metadata is regenerated on the next edit).
    "class_spell_list",
    "spell",
    "spell_list",
    "spell_class",
    "spell_realm",
    # Adolescence rank matrix — wipe+reload each pass since it's tabular
    # reference data; the loader inserts fresh rows from the .txt source.
    # NOT including `race` here because race rows carry stable IDs that
    # characters FK to; the race loader uses ON CONFLICT(slug) DO UPDATE.
    "adolescence_rank",
)

# Columns that newer deployments need but pre-existing DBs may lack. Applied
# idempotently by reload_ref_data so an in-place upgrade doesn't require
# --reset. (CREATE TABLE IF NOT EXISTS won't add columns to a pre-existing
# table — that's an ALTER TABLE.)
_REQUIRED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    # (table, column, "ADD COLUMN ..." clause)
    ("spell", "updated_at", "ADD COLUMN updated_at TEXT"),
    (
        "spell",
        "updated_by_user_id",
        "ADD COLUMN updated_by_user_id INTEGER REFERENCES app_user(user_id) "
        "ON DELETE SET NULL",
    ),
    (
        "character",
        "race_id",
        "ADD COLUMN race_id INTEGER REFERENCES race(race_id) ON DELETE SET NULL",
    ),
    (
        "race",
        "culture_data",
        "ADD COLUMN culture_data TEXT NOT NULL DEFAULT '{}'",
    ),
    (
        "skill_table",
        "general_mods",
        "ADD COLUMN general_mods TEXT NOT NULL DEFAULT ''",
    ),
    ("skill_category_group", "updated_at", "ADD COLUMN updated_at TEXT"),
    (
        "skill_category_group",
        "updated_by_user_id",
        "ADD COLUMN updated_by_user_id INTEGER REFERENCES app_user(user_id) "
        "ON DELETE SET NULL",
    ),
    (
        "character",
        "profession_id",
        "ADD COLUMN profession_id INTEGER REFERENCES profession(profession_id) "
        "ON DELETE SET NULL",
    ),
    # SOHK ingestion (book 5808). Skills get a JSON blob of supplemental
    # fields (optional stats / EP cost / notes / specialties / example
    # difficulties); categories get a prose `sohk_notes` paragraph;
    # professions + training packages get a `source` tag so the SPA can
    # filter "Character Law only" vs. "include SOHK additions".
    (
        "skill",
        "sohk_data",
        "ADD COLUMN sohk_data TEXT NOT NULL DEFAULT '{}'",
    ),
    (
        "skill_category",
        "sohk_notes",
        "ADD COLUMN sohk_notes TEXT NOT NULL DEFAULT ''",
    ),
    (
        "skill_category_group",
        "sohk_notes",
        "ADD COLUMN sohk_notes TEXT NOT NULL DEFAULT ''",
    ),
    (
        "profession",
        "source",
        "ADD COLUMN source TEXT NOT NULL DEFAULT 'character_law'",
    ),
    (
        "training_package",
        "source",
        "ADD COLUMN source TEXT NOT NULL DEFAULT 'character_law'",
    ),
)


def init_db(reset: bool) -> sqlite3.Connection:
    """Open DB, apply schema. Deletes the file first when `reset` is True."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _apply_missing_columns(conn: sqlite3.Connection) -> None:
    """Run ALTER TABLE for any column in _REQUIRED_COLUMNS that's missing.

    sqlite3 has no `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, so we check
    PRAGMA table_info first. This lets `load.py --reload-ref` migrate an
    older deployment in place without dropping user data.
    """
    for table, column, clause in _REQUIRED_COLUMNS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} {clause}")
    conn.commit()


def reload_ref_data(conn: sqlite3.Connection) -> None:
    """Wipe reference tables in dependency order, leaving user tables (app_user,
    future character tables) untouched. Caller is expected to re-insert ref data.

    Also applies any in-place column additions for tables whose schema has
    drifted forward since this DB was first built — this is the upgrade
    path for existing deployments after a schema change.

    Each name is whitelisted against sqlite_master so a typo can't accidentally
    target a user table.
    """
    _apply_missing_columns(conn)

    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    existing = {row[0] for row in cur.fetchall()}
    for table in REF_TABLES_DELETE_ORDER:
        if table in existing:
            conn.execute(f"DELETE FROM {table}")
    # Reset AUTOINCREMENT counters so primary keys start fresh.
    if "sqlite_sequence" in existing:
        for table in REF_TABLES_DELETE_ORDER:
            conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
    conn.commit()


def main() -> None:
    p = argparse.ArgumentParser()
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--reset", action="store_true",
        help="delete the entire DB before loading (DESTRUCTIVE: wipes user data too)",
    )
    mode.add_argument(
        "--reload-ref", action="store_true",
        help="wipe and reload reference data only; preserves user tables (app_user, etc.)",
    )
    args = p.parse_args()

    if args.reset:
        conn = init_db(reset=True)
    elif args.reload_ref:
        if not DB_PATH.exists():
            # No DB yet — first run; --reload-ref degrades gracefully to a full init.
            conn = init_db(reset=False)
        else:
            conn = init_db(reset=False)  # ensures schema is up to date (CREATE IF NOT EXISTS)
            reload_ref_data(conn)
    else:
        # Default: same as --reset for backwards compatibility with `python load.py`.
        conn = init_db(reset=True)

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
    races_loaded = insert_races(conn)
    cultures_loaded = insert_culture_data(conn)
    adolescence_cells = insert_adolescence_ranks(conn)
    skill_stats = insert_skills(conn)
    professions_loaded = insert_professions(conn)
    training_packages_loaded = insert_training_packages(conn)

    conn.commit()
    conn.close()

    if races_loaded:
        print(f"Races: {races_loaded} loaded")
    if cultures_loaded:
        print(f"Culture data: {cultures_loaded} races enriched")
    if professions_loaded:
        print(f"Professions: {professions_loaded} loaded")
    if training_packages_loaded:
        print(f"Training packages: {training_packages_loaded} loaded")
    if skill_stats[0]:
        ng, nc, ns, nt = skill_stats
        print(f"Skills: {ng} groups, {nc} categories, {ns} skills, {nt} tables")
    if adolescence_cells:
        print(f"Adolescence ranks: {adolescence_cells} cells")

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
