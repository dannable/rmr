"""Extract attack tables from ERA archives → data/weapons/<slug>.txt files.

The on-disk `.era` is a reversed base64-encoded ZIP archive (same format
as the professions / training-packages ERAs):
    reversed string → base64-decode → ZIP → N <Name>.{table,variant-attackTable}.XML

Two XML shapes inside:

  <attackTable weapon="..." fumble="N">
    <columns>
      <column AT="20">
        <rows>
          <row low="148" high="150" hits="8"
               criticalSeverity="E" criticalType="S" />
          <row low="118" high="120" hits="6" />   <!-- hits-only -->
        </rows>
      </column>
      ... AT=19..1 ...
    </columns>
  </attackTable>

  <VariantAttackTable name="Bash Small" baseAttackTable="Bash Huge"
                      maximumResult="105" />

The base attack table contains the canonical chart; the variant files
specify a size/rank cap that applies to the BASE table when the attacker
is of that size. Per our schema (attack_table_size_cap), we encode these
caps with degree 1=Small, 2=Medium, 3=Large, 4=Huge.

Idempotent: skips weapons whose name (canonicalised) already exists in
the DB or whose .txt file already exists in data/weapons/. The user has
hand-curated some files with prose and rich metadata that the ERA
doesn't carry (length, weight, breakage, strength, range mods), and
overwriting them would lose information.

Usage:
    python .scratch/build_attack_tables.py [--dry-run] [--force]
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
OUT_DIR = REPO / "data" / "weapons"
DB_PATH = REPO / "rmfrp.db"

# Map source tag → (era_file, comment, table_prefix). The prefix is used
# to manufacture an attack_table identifier for weapons whose RMSS book
# table number we don't have in hand.
SOURCES = (
    ("arms_law",  "rmfrpArmsLaw.attackTables.era",
     "Rolemaster Fantasy Roleplaying — Arms Law"),
    ("spell_law", "rmfrpSpellLaw.attackTables.era",
     "Rolemaster Fantasy Roleplaying — Spell Law"),
    ("armory",    "rmfrpTheArmory.attackTables.era",
     "Rolemaster Fantasy Roleplaying — The Armory"),
)

# ERA-name → DB-name aliases. The ERA uses unhyphenated spellings for a
# few weapons that the existing data files store hyphenated; without this
# canonicalisation we'd duplicate-load them under a different name.
ERA_TO_DB_ALIASES: dict[str, str] = {
    "Two Handed Sword":   "Two-Handed Sword",
    "Brawling Huge":      "Brawling",
    "Strikes IV":         "Martial Arts Strikes",
    "Sweeps IV":          "Martial Arts Sweeps",
}

# Single-letter crit-type codes used in the ERA → friendly crit-table
# name (matches critical_strike_table.name). The schema CHECK on
# attack_result.crit_type is being widened to allow B/C/D/E/H/I/Q/W in
# addition to the original G/K/P/S/T/U; this mapping documents what each
# letter means so a follow-up read path can resolve "C" → "Cold" etc.
CRIT_TYPE_NAMES: dict[str, str] = {
    "B": "Brawling",
    "C": "Cold",
    "D": "Subdual",          # only used by the Armory's "Mullet" humour weapon
    "E": "Electricity",
    "G": "Grapple",
    "H": "Heat",
    "I": "Impact",           # ice/water bolt damage uses Impact in RMSS
    "K": "Krush",
    "P": "Puncture",
    "Q": "Martial Arts Strikes",
    "S": "Slash",
    "T": "Tiny",
    "U": "Unbalancing",
    "W": "Martial Arts Sweeps",
}

# Variant suffix → degree code. The variant XMLs name the SIZE the cap
# applies to; existing schema stores them as integers 1..4.
SIZE_TO_DEGREE: dict[str, int] = {
    "Small":  1,
    "Medium": 2,
    "Large":  3,
    "Huge":   4,
}


def decode_era(path: Path) -> dict[str, bytes]:
    """Decode a `.era` file into {filename: raw bytes} per archive entry."""
    raw = path.read_bytes().strip()
    decoded = base64.b64decode(raw[::-1] + b"==", validate=False)
    with zipfile.ZipFile(io.BytesIO(decoded)) as z:
        return {info.filename: z.read(info.filename) for info in z.infolist()}


def slugify(name: str) -> str:
    """Canonical filename for a weapon — snake_case, alnum + underscores."""
    s = re.sub(r"[^\w]+", "_", name.strip().lower())
    return re.sub(r"_+", "_", s).strip("_")


def parse_attack_table(xml_bytes: bytes) -> dict:
    """Parse an <attackTable> XML element.

    Returns a dict shaped for the txt writer:
        {
          "name":      "Long Sword",
          "fumble":    "3",        # the fumble range high (low is implicitly 1)
          "rows":      [
              (label, [cell, cell, ... 20 cells from AT20 down to AT1]),
              ...
          ],
          "crit_types_seen": {"S", "K", ...},
        }

    The chart is a transposition of the ERA's column-major XML: we walk
    AT=20 first to establish the canonical row order, then fill in the
    other 19 columns by (low, high) lookup. Any column missing a row for
    a given range gets "-" (miss).
    """
    root = ET.fromstring(xml_bytes)
    weapon = root.get("weapon", "Unknown")
    fumble = root.get("fumble") or ""

    # Pull rows per AT column. Some XMLs flatten whitespace inside
    # <column>, so iterate children defensively.
    columns: dict[int, list[ET.Element]] = {}
    for col in root.iter("column"):
        try:
            at = int(col.get("AT") or "")
        except ValueError:
            continue
        rows = col.find("rows")
        if rows is None:
            columns[at] = []
        else:
            columns[at] = list(rows.findall("row"))

    # Detect crit types we'll need to whitelist in the schema migration.
    crit_types_seen: set[str] = set()
    crit_sevs_seen: set[str] = set()

    # Build a (low,high) → cell index for each AT column so we can do
    # O(1) lookups when filling out the row.
    col_lookup: dict[int, dict[tuple[int, int], ET.Element]] = {}
    all_ranges: set[tuple[int, int]] = set()
    for at, rows in columns.items():
        d: dict[tuple[int, int], ET.Element] = {}
        for row in rows:
            try:
                lo = int(row.get("low") or "0")
                hi = int(row.get("high") or "0")
            except ValueError:
                continue
            d[(lo, hi)] = row
            all_ranges.add((lo, hi))
        col_lookup[at] = d

    if not all_ranges:
        raise ValueError(f"{weapon!r}: no rows in any AT column")

    # Canonical row order: union of all (low, high) across columns, sorted
    # by `low` descending so high rolls land at the top of the file —
    # matches the existing data/weapons/*.txt convention.
    canonical = sorted(all_ranges, key=lambda lh: (-lh[0], -lh[1]))

    # Emit one (label, [20 cells]) per canonical row.
    rows_out: list[tuple[str, list[str]]] = []
    for lo, hi in canonical:
        label = str(hi) if lo == hi else f"{lo}-{hi}"
        cells: list[str] = []
        for at in range(20, 0, -1):   # AT 20 down to AT 1
            row = col_lookup.get(at, {}).get((lo, hi))
            if row is None:
                cells.append("-")
                continue
            hits = row.get("hits") or "0"
            # Normalise case — one cell in the Lightning Bolt ERA has
            # criticalSeverity="f" (lowercase) which would violate the
            # uppercase-only CHECK constraint downstream.
            sev = (row.get("criticalSeverity") or "").upper()
            ctype = (row.get("criticalType") or "").upper()
            if sev:
                crit_sevs_seen.add(sev)
            if ctype:
                crit_types_seen.add(ctype)
            # Cell shape: "N" hits-only; "NSC" hits + severity + crit-type;
            # "-" miss. Fumbles are NOT per-cell in the ERA — they're
            # captured via the attackTable@fumble attribute, which we
            # surface as @fumble_range in the .txt file.
            if sev or ctype:
                cell = f"{hits}{sev}{ctype}"
            else:
                cell = hits if hits != "0" else "-"
            cells.append(cell)
        rows_out.append((label, cells))

    return {
        "name": weapon,
        "fumble": fumble,
        "rows": rows_out,
        "crit_types_seen": crit_types_seen,
        "crit_sevs_seen": crit_sevs_seen,
    }


def write_weapon_file(
    out_path: Path,
    source_tag: str,
    source_book: str,
    name: str,
    attack_table_id: str,
    fumble_high: str,
    rows: list[tuple[str, list[str]]],
    size_caps: dict[int, int],
) -> None:
    """Serialize one weapon to data/weapons/<slug>.txt.

    The output format is the one load.py's parse_weapon_file() reads:
    @meta lines + chart rows of "label | 20 cells". Missing metadata
    (length, weight, breakage, strength, range_modifiers) is emitted as
    "-" so the loader's range-parsers see "no data" instead of garbage.
    """
    lines: list[str] = []
    lines.append(f"# Attack Table — {name}")
    lines.append(f"# Source: {source_book} (ERA: {source_tag})")
    lines.append("# Auto-generated by .scratch/build_attack_tables.py from the .era archive.")
    lines.append("# Curated metadata (length / weight / breakage / strength /")
    lines.append("# range modifiers) is not present in the ERA source; fill these")
    lines.append("# in by hand if you want them surfaced in the SPA.")
    lines.append("#")
    lines.append("# --- weapon metadata ---")
    lines.append(f"@name:            {name}")
    lines.append(f"@attack_table:    {attack_table_id}")
    lines.append("@two_handed:      no")
    lines.append("@length_ft:       -")
    lines.append("@weight_lb:       -")
    if fumble_high:
        # ERA fumble attr is the HIGH end of the fumble range; the low is 1.
        lines.append(f"@fumble_range:    01 - {int(fumble_high):02d}")
    else:
        lines.append("@fumble_range:    -")
    lines.append("@breakage_nums:   -")
    lines.append("@strength:        -")
    lines.append("@range_modifiers: -")
    for degree, max_roll in sorted(size_caps.items()):
        lines.append(f"@max_degree_{degree}:   {max_roll}")
    lines.append("#")
    lines.append("# --- chart ---")
    lines.append("# Each row: <roll> | <AT20> <AT19> ... <AT1>     (20 cells, space-separated)")
    lines.append("#")
    for label, cells in rows:
        lines.append(f"{label} | " + " ".join(cells))
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_existing_db_weapons() -> set[str]:
    """Return a set of canonicalised (lower) weapon names already in the DB.
    Falls back to an empty set if the DB hasn't been built yet."""
    if not DB_PATH.exists():
        return set()
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("SELECT name FROM weapon").fetchall()
        return {r[0].strip().lower() for r in rows}
    except sqlite3.OperationalError:
        # weapon table doesn't exist yet
        return set()
    finally:
        try:
            conn.close()
        except Exception:
            pass


def load_existing_txt_slugs() -> set[str]:
    """Slugs of weapon .txt files already present on disk — we don't
    overwrite these. The DB-name check covers loaded weapons; this covers
    .txt files written but not yet ingested."""
    if not OUT_DIR.exists():
        return set()
    return {p.stem for p in OUT_DIR.glob("*.txt")}


def canonicalise(name: str) -> str:
    return ERA_TO_DB_ALIASES.get(name, name).strip().lower()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Print actions, write nothing.")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing data/weapons/*.txt files.")
    args = ap.parse_args()

    existing_db = load_existing_db_weapons()
    existing_txt = load_existing_txt_slugs()

    written = 0
    skipped_existing = 0
    skipped_alias = 0
    all_crit_types: set[str] = set()
    all_crit_sevs: set[str] = set()

    for source_tag, era_filename, source_book in SOURCES:
        era_path = ERA_DIR / era_filename
        if not era_path.exists():
            print(f"skip {source_tag}: {era_path} not found", file=sys.stderr)
            continue
        print(f"\n[{source_tag}] decoding {era_path.name}")
        entries = decode_era(era_path)

        # Split into base tables + variants, keyed by name (with the
        # ".table.XML" / ".variant-attackTable.XML" suffix stripped).
        bases: dict[str, bytes] = {}
        variants: list[ET.Element] = []
        for filename, payload in entries.items():
            if filename.endswith(".table.XML"):
                name = filename[: -len(".table.XML")]
                bases[name] = payload
            elif filename.endswith(".variant-attackTable.XML"):
                root = ET.fromstring(payload)
                if root.tag == "VariantAttackTable":
                    variants.append(root)

        # Index variants by base name → list[(degree, cap)].
        caps_by_base: dict[str, dict[int, int]] = {}
        for v in variants:
            vname = v.get("name") or ""
            base = v.get("baseAttackTable") or ""
            # Spell Law's "Fumbling Fire Bolt" etc. are not size variants;
            # they're separate fumble charts. They have no maximumResult
            # and they belong in fumble_table, not attack_table. Skip
            # cleanly without spamming warnings.
            if vname.startswith("Fumbling "):
                continue
            try:
                cap = int(v.get("maximumResult") or "0")
            except ValueError:
                continue
            # Infer the degree from the suffix after the base name. For
            # "Bash Small" with base "Bash Huge" → suffix "Small" → 1.
            # For "Strikes I" with base "Strikes IV" → suffix "I" → 1.
            # For Tiny variants ("Tiny Initial" / "Tiny Next I/II")
            # we fall back to a sequential index.
            suffix = vname.replace(base.rsplit(" ", 1)[0], "").strip()
            degree = SIZE_TO_DEGREE.get(suffix)
            if degree is None:
                roman = {"I": 1, "II": 2, "III": 3}
                tail = vname.rsplit(" ", 1)[-1]
                degree = roman.get(tail)
            if degree is None:
                # "Tiny Initial" → degree 1 by convention (smallest).
                if "Initial" in vname:
                    degree = 1
            if degree is None:
                print(f"  warn: can't infer degree for variant {vname!r} "
                      f"(base={base!r}); skipping cap", file=sys.stderr)
                continue
            caps_by_base.setdefault(base, {})[degree] = cap

        for base_name, payload in sorted(bases.items()):
            canon = canonicalise(base_name)
            if canon in existing_db:
                skipped_existing += 1
                if canon != base_name.lower():
                    skipped_alias += 1
                continue

            slug = slugify(base_name)
            out_path = OUT_DIR / f"{slug}.txt"
            if slug in existing_txt and not args.force:
                # Hand-curated file already on disk — leave it.
                skipped_existing += 1
                continue

            parsed = parse_attack_table(payload)
            all_crit_types.update(parsed["crit_types_seen"])
            all_crit_sevs.update(parsed["crit_sevs_seen"])

            attack_table_id = f"{source_tag}.{slug}"
            size_caps = caps_by_base.get(base_name, {})

            print(f"  + {slug}  ({len(parsed['rows'])} rows"
                  f"{f', caps={size_caps}' if size_caps else ''})")
            if not args.dry_run:
                write_weapon_file(
                    out_path,
                    source_tag, source_book,
                    parsed["name"], attack_table_id,
                    parsed["fumble"], parsed["rows"], size_caps,
                )
                written += 1

    print(f"\nDone: {written} files written, "
          f"{skipped_existing} skipped (already present / aliased).")
    if all_crit_types:
        print(f"Crit types seen across new tables: {sorted(all_crit_types)}")
    if all_crit_sevs:
        print(f"Crit severities seen: {sorted(all_crit_sevs)}")


if __name__ == "__main__":
    main()
