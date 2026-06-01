r"""Extract critical-strike tables from ERA archives → data/crit_tables/<slug>.txt.

Same `.era` format as professions / attack tables (reversed base64 ZIP).
Each archive holds N <Name>.crit.XML entries shaped like:

  <criticalTable name="Slash" abbreviation="S">
    <columns>
      <column severity="A">
        <rows>
          <row low="1"  high="5"   damage="Weak strike. +0H" />
          <row low="6"  high="10"  damage="..." />
          ...
        </rows>
      </column>
      <column severity="B">...</column>
      ...
    </columns>
  </criticalTable>

`damage` is free-form text that combines a narrative sentence with the
structured effect code at the end (e.g. "Foe stumbles. +5H, [Stun], (-10)").
We split on the boundary between the last sentence-ending period and the
start of an effect-code token (`+\d`, `(`, `[`, or `\d[`).

Inventory of ERA entries vs the 18 crit tables already loaded in
data/crit_tables/ + the DB:

  Already covered (skip):
    Brawling, Cold, Electricity, Grapple, Heat, Impact, Krush, Puncture,
    Slash, Subdual, Tiny, Unbalance (= "Unbalancing" in DB),
    Martial Arts Strikes, Martial Arts Sweeps
  New (this script extracts):
    Large (Normal Weapon), Large (Magic Weapon), Large (Mithril Weapon),
    Large (Holy Weapon), Large (Slaying Weapon),
    Super Large (Normal Weapon), Super Large (Magic Weapon),
    Super Large (Mithril Weapon), Super Large (Holy Weapon),
    Super Large (Slaying Weapon),
    Large (Normal Spell), Large (Slaying Spell),
    Super Large (Normal Spell), Super Large (Slaying Spell)

The DB does have "Large Creature" + "Super Large Creature" + their Spell
variants already, but those four tables are the older PDF transcription
that collapsed attack-type into the severity axis. The ERA preserves
the full 5-severity × 5-attack-type matrix as separate tables, which
is richer source data; we load them as new tables alongside the
existing collapsed ones (which the bot's `/crit` resolver already
references — leaving them in place avoids breaking that path).

Idempotent: skips tables whose canonical name already matches an
existing crit-table .txt or DB row.

Usage:
    python .scratch/build_crit_tables.py [--dry-run] [--force]
"""

from __future__ import annotations

import argparse
import base64
import io
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ERA_DIR = REPO / "ERA"
OUT_DIR = REPO / "data" / "crit_tables"
DB_PATH = REPO / "rmfrp.db"

# Map source tag → (era_file, source-book comment, base table-number prefix).
SOURCES = (
    ("arms_law",  "rmfrpArmsLaw.criticals.era",
     "Rolemaster Fantasy Roleplaying — Arms Law",  "4.4"),
    ("spell_law", "rmfrpSpellLaw.criticals.era",
     "Rolemaster Fantasy Roleplaying — Spell Law", "6.5"),
    ("armory",    "rmfrpTheArmory.criticals.era",
     "Rolemaster Fantasy Roleplaying — The Armory","T"),
)

# ERA criticalTable @name → existing DB name. When the canonical name
# matches the DB, we skip — these aliases catch the spellings that
# differ between source and store.
ERA_TO_DB_ALIASES: dict[str, str] = {
    "Unbalance": "Unbalancing",   # ERA omits the "-ing"
}

# Effect-code token prefixes — used to find the split point between the
# narrative and the structured effect code in the ERA's `damage` text.
# Each token starts with one of: +, -, (, [, or a digit followed by '['
# (e.g. "3[Stun]"). The split happens at the boundary "<end-sentence>.
# <effect-token>" where the period is preceded by alphanumeric content.
_EFFECT_PREFIX = re.compile(r"\s+(?=[+\-(\[]|\d\[)")


def decode_era(path: Path) -> dict[str, bytes]:
    raw = path.read_bytes().strip()
    decoded = base64.b64decode(raw[::-1] + b"==", validate=False)
    with zipfile.ZipFile(io.BytesIO(decoded)) as z:
        return {info.filename: z.read(info.filename) for info in z.infolist()}


def slugify(name: str) -> str:
    s = re.sub(r"[^\w]+", "_", name.strip().lower())
    return re.sub(r"_+", "_", s).strip("_")


def split_damage(damage: str) -> tuple[str, str]:
    """Split `damage` into (narrative, effect_code).

    Strategy: find the LAST sentence-ending period followed by whitespace
    and an effect-code token. Everything up to and including the period
    is the narrative; everything after the whitespace is the effect.

    Examples:
        "Weak strike. +0H"                       -> ("Weak strike.", "+0H")
        "Foe stumbles. +5H, [Stun], (-10)"       -> ("Foe stumbles.", "+5H, [Stun], (-10)")
        "Blow 1. Blow 2. +3H"                    -> ("Blow 1. Blow 2.", "+3H")
        "No damage."                             -> ("No damage.", "")
    """
    text = damage.strip()
    # Walk through periods from left to right; for each ". ", check if
    # what follows starts with an effect-code token. Keep the rightmost
    # match — that's the boundary where narrative ends and effects begin.
    best_idx = -1
    for m in re.finditer(r"\.\s+", text):
        tail = text[m.end():]
        if re.match(r"[+\-(\[]|\d\[", tail):
            best_idx = m.end()
    if best_idx < 0:
        return text, ""
    return text[:best_idx].rstrip(), text[best_idx:].strip()


def parse_crit_xml(xml_bytes: bytes) -> dict:
    """Parse one <criticalTable> XML.

    Returns:
        {
          "name":         "Slash",
          "abbreviation": "S",
          "cells":        [
              {"roll": "01-05", "severity": "A", "narrative": "...", "effect_code": "..."},
              ...
          ],
        }
    """
    root = ET.fromstring(xml_bytes)
    name = root.get("name") or ""
    abbreviation = root.get("abbreviation") or ""

    cells: list[dict] = []
    for col in root.iter("column"):
        sev = col.get("severity") or col.get("attackType") or ""
        rows_el = col.find("rows")
        if rows_el is None:
            continue
        for row in rows_el.findall("row"):
            try:
                lo = int(row.get("low") or "0")
                hi = int(row.get("high") or "0")
            except ValueError:
                continue
            damage = row.get("damage") or ""
            narr, eff = split_damage(damage)
            roll = str(hi) if lo == hi else f"{lo:02d}-{hi:02d}"
            cells.append({
                "roll": roll, "severity": sev,
                "narrative": narr, "effect_code": eff,
                "low": lo, "high": hi,
            })

    return {"name": name, "abbreviation": abbreviation, "cells": cells}


def write_crit_file(
    out_path: Path,
    source_tag: str,
    source_book: str,
    name: str,
    table_number: str,
    crit_type_code: str | None,
    notes: str,
    cells: list[dict],
) -> None:
    """Serialize one crit table to data/crit_tables/<slug>.txt — format
    matches what load.py's parse_crit_table_file() reads."""
    lines: list[str] = []
    lines.append(f"# Critical Strike Table {table_number} — {name}")
    lines.append(f"# Source: {source_book} (ERA: {source_tag})")
    lines.append("# Auto-generated by .scratch/build_crit_tables.py from the .era archive.")
    lines.append("#")
    lines.append(f"@name:           {name}")
    lines.append(f"@table_number:   {table_number}")
    lines.append(f"@crit_type_code: {crit_type_code or ''}")
    if notes:
        lines.append(f"@notes:          {notes}")
    else:
        lines.append("@notes:")
    lines.append("@column_axis:    severity")
    lines.append("#")
    # Sort cells by (low, severity) so file lines come out in a stable
    # roll-then-column order matching the existing curated files.
    sev_order = {s: i for i, s in enumerate("ABCDEFGHIJ")}
    for cell in sorted(cells, key=lambda c: (c["low"], sev_order.get(c["severity"], 99))):
        narr = (cell["narrative"] or "").replace("|", "/")  # | is the field separator
        eff = (cell["effect_code"] or "").replace("|", "/")
        lines.append(f"{cell['roll']} | {cell['severity']} | {narr} | {eff}")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_existing_db_crit_names() -> set[str]:
    """Lowercased crit-table names already in the DB."""
    if not DB_PATH.exists():
        return set()
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("SELECT name FROM critical_strike_table").fetchall()
        return {r[0].strip().lower() for r in rows}
    except sqlite3.OperationalError:
        return set()
    finally:
        try:
            conn.close()
        except Exception:
            pass


def load_existing_txt_slugs() -> set[str]:
    if not OUT_DIR.exists():
        return set()
    return {p.stem for p in OUT_DIR.glob("*.txt")}


def canonicalise(name: str) -> str:
    return ERA_TO_DB_ALIASES.get(name, name).strip().lower()


# Map abbreviations of the new Large / SuperLarge variants to a stable
# table_number suffix. The existing DB uses 4.4 / 4.10 / 6.5 for the
# collapsed Large / Super Large / Spell variants; we suffix with the
# attack-type initial so the new tables are visibly distinct.
_TABLE_NUMBER_BY_ABBR: dict[str, str] = {
    # Arms Law Large variants
    "LPN": "4.4-N",   # Normal weapon
    "LPM": "4.4-M",   # Magic weapon
    "LPO": "4.4-O",   # Mithril (O for Orcrist? PDF uses O)
    "LPH": "4.4-H",   # Holy weapon
    "LPS": "4.4-S",   # Slaying weapon
    # Arms Law Super Large variants
    "SPN": "4.10-N",
    "SPM": "4.10-M",
    "SPO": "4.10-O",
    "SPH": "4.10-H",
    "SPS": "4.10-S",
    # Spell Law Large + Super Large variants
    "LMN": "6.5-LN",  # Large, Normal Spell
    "LMS": "6.5-LS",
    "SMN": "6.5-SLN",
    "SMS": "6.5-SLS",
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Print actions, write nothing.")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing data/crit_tables/*.txt files.")
    args = ap.parse_args()

    existing_db = load_existing_db_crit_names()
    existing_txt = load_existing_txt_slugs()

    written = 0
    skipped = 0
    seen_canonical: set[str] = set()   # dedupe within this run (Armory repeats Arms Law)

    for source_tag, era_filename, source_book, _tnum_prefix in SOURCES:
        era_path = ERA_DIR / era_filename
        if not era_path.exists():
            print(f"skip {source_tag}: {era_path} not found", file=sys.stderr)
            continue
        print(f"\n[{source_tag}] decoding {era_path.name}")
        entries = decode_era(era_path)

        for filename in sorted(entries):
            if not filename.endswith(".crit.XML"):
                continue
            parsed = parse_crit_xml(entries[filename])
            name = parsed["name"]
            canon = canonicalise(name)

            if canon in existing_db:
                skipped += 1
                continue
            if canon in seen_canonical:
                # Same table appears in multiple ERAs (e.g. Armory repeats
                # the Arms Law Slash). We've already processed it.
                skipped += 1
                continue

            slug = slugify(name)
            out_path = OUT_DIR / f"{slug}.txt"
            if slug in existing_txt and not args.force:
                skipped += 1
                continue

            # Pick a stable table_number. Large / Super Large variants
            # use the 4.4-X / 4.10-X / 6.5-X scheme; anything else falls
            # back to source_tag + slug so it sorts in the SPA.
            table_number = _TABLE_NUMBER_BY_ABBR.get(
                parsed["abbreviation"],
                f"{source_tag}.{slug}",
            )

            print(f"  + {slug}  ({len(parsed['cells'])} cells, table={table_number}, abbr={parsed['abbreviation']})")
            if not args.dry_run:
                write_crit_file(
                    out_path,
                    source_tag, source_book,
                    name, table_number,
                    crit_type_code=None,        # multi-letter abbreviations don't fit
                    notes=(f"Source ERA: {era_filename}; "
                           f"variant abbreviation '{parsed['abbreviation']}'."),
                    cells=parsed["cells"],
                )
                written += 1
            seen_canonical.add(canon)

    print(f"\nDone: {written} files written, {skipped} skipped "
          "(already in DB / already in data/ / duplicate within ERAs).")


if __name__ == "__main__":
    main()
