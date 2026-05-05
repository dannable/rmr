"""Extract skeleton data files for all crit and fumble tables.

Produces files under data/crit_tables/ and data/fumble_tables/ with:
  * full structure (every roll band, every column)
  * verbatim effect-code text for crit cells (best-effort by x-position bucketing)
  * narrative column set to "TODO" — to be filled in from the source by hand
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pdfplumber

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
PDF_PATH = ROOT / "Rolemaster FRP - Arms Law.pdf"
CRIT_OUT = ROOT / "data" / "crit_tables"
FUMBLE_OUT = ROOT / "data" / "fumble_tables"
CRIT_OUT.mkdir(parents=True, exist_ok=True)
FUMBLE_OUT.mkdir(parents=True, exist_ok=True)

# Canonical row labels (verified across pages — same 19 bands per crit table).
CRIT_ROW_LABELS = [
    "01-05","06-10","11-15","16-20","21-35","36-45","46-50","51-55",
    "56-60","61-65","66","67-70","71-75","76-80","81-85","86-90",
    "91-95","96-99","100",
]

FUMBLE_ROW_LABELS = [
    "01-25","26-30","31-40","41-50","51-60","61-65","66","67-70",
    "71-80","81-85","86-90","91-95","96-99","100",
]

# Section-4 standalone tables. (pdfidx, slug, display_name, table_number, crit_letter, special_columns)
# special_columns: None for standard A-E shape; otherwise list of column labels.
LARGE_CREATURE_COLS = ["normal", "magic", "mithril", "holy_arms", "slaying"]

CRIT_TABLES = [
    (94,  "brawling",            "Brawling",                 "4.1",  None, None),
    (95,  "grapple",             "Grapple",                  "4.2",  "G",  None),
    (96,  "krush",               "Krush",                    "4.3",  "K",  None),
    (97,  "large_creature",      "Large Creature",           "4.4",  None, LARGE_CREATURE_COLS),
    (98,  "martial_arts_strikes","Martial Arts Strikes",     "4.5",  None, None),
    (99,  "martial_arts_sweeps", "Martial Arts Sweeps",      "4.6",  None, None),
    (100, "puncture",            "Puncture",                 "4.7",  "P",  None),
    (101, "slash",               "Slash",                    "4.8",  "S",  None),
    (102, "subdual",             "Subdual",                  "4.9",  None, None),
    (103, "super_large",         "Super Large Creature",     "4.10", None, LARGE_CREATURE_COLS),
    (104, "tiny",                "Tiny",                     "4.11", "T",  None),
    (105, "unbalancing",         "Unbalancing",              "4.12", "U",  None),
]

FUMBLE_TABLES = [
    (106, "weapon_fumble",     "Weapon Fumble Table",     "4.13",
        ["One-Handed Arms", "Two-Handed Arms", "Polearms and Spears",
         "Mounted Arms", "Thrown Arms", "Missile Weapons"]),
    (107, "non_weapon_fumble", "Non-Weapon Fumble Table", "4.14",
        ["Martial Arts Strikes", "Martial Arts Sweeps", "Brawling", "Animal"]),
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def cluster_by_y(words: list[dict], tol: float = 4.0) -> list[list[dict]]:
    if not words:
        return []
    by_top = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines: list[list[dict]] = [[by_top[0]]]
    for w in by_top[1:]:
        if abs(w["top"] - lines[-1][0]["top"]) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    for line in lines:
        line.sort(key=lambda w: w["x0"])
    return lines


def line_text(line: list[dict]) -> str:
    return " ".join(w["text"] for w in line)


def is_effect_line(line: list[dict]) -> bool:
    text = line_text(line).lower().strip()
    if not text:
        return False
    narrative_signals = (
        " you ", " foe", " your ", " his ", " the ", " and ",
        " is ", " are ", " he ", " a ", " to ", " of ", " on ",
    )
    narr_hits = sum(1 for s in narrative_signals if s in f" {text} ")
    if narr_hits >= 3:
        return False
    effect_chars = set("0123456789+-–—()πϖ∏∑∫,.Hh ")
    effect_chars.update("/wo:%")  # for "w/o", "5%", "with X:"
    n_effect = sum(1 for c in text if c in effect_chars)
    return n_effect / max(1, len(text)) >= 0.7


def bucket_by_x(line: list[dict], col_centers: list[float]) -> list[str]:
    bounds = [(a + b) / 2 for a, b in zip(col_centers, col_centers[1:])]
    buckets: list[list[str]] = [[] for _ in col_centers]
    for w in line:
        idx = 0
        for i, b in enumerate(bounds):
            if w["x0"] >= b:
                idx = i + 1
        buckets[idx].append(w["text"])
    return [" ".join(b).strip() or "—" for b in buckets]


# ---------------------------------------------------------------------------
# header detection
# ---------------------------------------------------------------------------

def find_severity_header(words: list[dict]) -> list[float] | None:
    """Look for an 'A B C D E' header line. Returns x-centers or None."""
    for line in cluster_by_y(words):
        texts = [w["text"] for w in line]
        if len(line) < 5:
            continue
        # Find a contiguous A,B,C,D,E (case-insensitive) subsequence
        for i in range(len(line) - 4):
            sub = [t.upper() for t in texts[i:i + 5]]
            if sub == ["A", "B", "C", "D", "E"]:
                return [(w["x0"] + w["x1"]) / 2 for w in line[i:i + 5]]
    return None


def find_special_header(words: list[dict], expected_cols: list[str]) -> list[float] | None:
    """For Large Creature tables, columns are named (e.g. 'normal','magic',...).
    Find these words as a single line near the top and return x-centers."""
    cols_lower = [c.lower().split("_")[0] for c in expected_cols]
    for line in cluster_by_y(words):
        texts = [w["text"].lower() for w in line]
        # Allow extra header words; just need each expected column to appear
        found_idx: list[int] = []
        for c in cols_lower:
            for i, t in enumerate(texts):
                if t == c and i not in found_idx:
                    found_idx.append(i)
                    break
            else:
                break
        if len(found_idx) == len(cols_lower):
            return [(line[i]["x0"] + line[i]["x1"]) / 2 for i in found_idx]
    return None


# ---------------------------------------------------------------------------
# row detection
# ---------------------------------------------------------------------------

def find_row_y_positions(words: list[dict], header_x_min: float) -> list[float]:
    """Find row y-positions in the leftmost label column.

    Brawling-style charts render labels as just the trailing digit (e.g. "5"
    for "01-05"); other charts have full "01-05" tokens. Either way we want
    one y per row — and there are 19 rows in every standard crit table.

    Strategy: gather every digit-only token at x < header_x_min, then
    deduplicate y-positions that are within 4px (likely the same physical
    row, e.g. paired stacked digits in "100" or "66"). Trust the result;
    no further merging — different rows are typically 17+ px apart.
    """
    left = [w for w in words
            if w["x0"] < header_x_min - 10
            and re.match(r"^\d{1,3}(-\d{1,3})?$", w["text"])]
    if not left:
        return []
    ys = sorted({round(w["top"], 1) for w in left})
    # Merge anything within 4px (truly the same line)
    merged: list[float] = []
    for y in ys:
        if merged and y - merged[-1] <= 4:
            continue
        merged.append(y)
    return merged


# ---------------------------------------------------------------------------
# crit-table extraction
# ---------------------------------------------------------------------------

def extract_crit_table(page, special_cols: list[str] | None) -> tuple[list[str], list[dict]]:
    """Returns (col_labels, cells)."""
    # x_tolerance=3 keeps tokens like "(+10)" together; previously they split
    # at the "(" boundary and only "(+" landed in the right bucket.
    words = page.extract_words(x_tolerance=3, y_tolerance=2,
                               keep_blank_chars=False, use_text_flow=False)

    if special_cols:
        col_centers = find_special_header(words, special_cols)
        col_labels = special_cols
    else:
        col_centers = find_severity_header(words)
        col_labels = list("ABCDE")

    if col_centers is None:
        raise RuntimeError("Could not find header row")

    # Find row y-positions
    row_ys = find_row_y_positions(words, min(col_centers))

    # Map to canonical labels (assume all 19 bands present, in order).
    # If we get fewer/more clusters, still proceed but warn.
    n_expected = len(CRIT_ROW_LABELS)
    if len(row_ys) != n_expected:
        sys.stderr.write(
            f"  warn: found {len(row_ys)} row clusters, expected {n_expected}\n"
        )
    # Use as many as we have; if too many, trim from the end (likely a footer).
    row_ys = row_ys[:n_expected]
    labels_for_rows = CRIT_ROW_LABELS[: len(row_ys)]

    cells: list[dict] = []
    for i, (label, y0) in enumerate(zip(labels_for_rows, row_ys)):
        y_end = row_ys[i + 1] - 2 if i + 1 < len(row_ys) else page.height - 30
        block = [bw for bw in words if y0 - 2 <= bw["top"] < y_end]
        # Exclude leftmost-column label tokens
        block = [bw for bw in block if bw["x0"] >= min(col_centers) - 30]
        lines = cluster_by_y(block)
        eff_lines = [ln for ln in lines if is_effect_line(ln)]
        if not eff_lines and lines:
            eff_lines = [lines[-1]]
        for eff_line in eff_lines:
            buckets = bucket_by_x(eff_line, col_centers)
            for col_idx, code in enumerate(buckets):
                cells.append({
                    "row_label": label,
                    "col_index": col_idx + 1,
                    "col_label": col_labels[col_idx],
                    "effect_code": code,
                    "is_alt": len(eff_lines) > 1,
                })
    return col_labels, cells


def write_crit_skeleton(slug: str, name: str, table_number: str, crit_letter: str | None,
                        col_labels: list[str], cells: list[dict]) -> Path:
    out = CRIT_OUT / f"{slug}.txt"
    if out.exists():
        out.replace(out.with_suffix(".txt.bak"))
    is_special = col_labels != list("ABCDE")
    lines: list[str] = [
        f"# Critical Strike Table {table_number} — {name}",
        f"# Skeleton generated by extract_skeletons.py.",
        f"# Effect codes are extracted verbatim from the PDF by x-position bucketing.",
        f"# Narratives are TODO — fill in from your source copy.",
        f"# Some armor-conditional cells may be split across multiple lines tagged",
        f"# 'alt' — review and rename the condition (e.g. 'with shield' / 'without shield').",
        f"#",
        f"@name:           {name}",
        f"@table_number:   {table_number}",
        f"@crit_type_code: {crit_letter or ''}",
        f"@notes:          Skeleton; narratives need to be transcribed.",
    ]
    if is_special:
        lines.append(f"@column_axis:    attack_type")
        for i, lbl in enumerate(col_labels, start=1):
            lines.append(f"@column_{i}:        {lbl}")
    else:
        lines.append(f"@column_axis:    severity")
    lines.append("#")
    seen_alt: set[tuple[str, int]] = set()
    for c in cells:
        cond = ""
        if c["is_alt"]:
            key = (c["row_label"], c["col_index"])
            if key in seen_alt:
                cond = " | alt"
            else:
                seen_alt.add(key)
        col_field = c["col_label"]  # severity letter or attack-type name
        code = c["effect_code"] or "—"
        lines.append(f"{c['row_label']} | {col_field} | TODO | {code}{cond}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# fumble-table extraction
# ---------------------------------------------------------------------------

def write_fumble_skeleton(slug: str, name: str, table_number: str,
                          col_names: list[str]) -> Path:
    out = FUMBLE_OUT / f"{slug}.txt"
    if out.exists():
        out.replace(out.with_suffix(".txt.bak"))
    lines: list[str] = [
        f"# Fumble Table {table_number} — {name}",
        f"# Skeleton generated by extract_skeletons.py.",
        f"# Each cell is narrative-only (no separate effect code).",
        f"# Narratives are TODO — fill in from your source copy.",
        f"#",
        f"@name:         {name}",
        f"@table_number: {table_number}",
    ]
    for i, cn in enumerate(col_names, start=1):
        lines.append(f"@column_{i}:    {cn}")
    lines.append("#")
    lines.append(f"# Format: <roll-band> | <col_index 1..{len(col_names)}> | <narrative>")
    lines.append("#")
    for label in FUMBLE_ROW_LABELS:
        for col in range(1, len(col_names) + 1):
            lines.append(f"{label} | {col} | TODO")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    with pdfplumber.open(PDF_PATH) as pdf:
        print("Critical strike tables:")
        for pdfidx, slug, name, num, letter, special_cols in CRIT_TABLES:
            page = pdf.pages[pdfidx]
            cropped = page.within_bbox((25, 30, page.width - 25, page.height - 5))
            try:
                col_labels, cells = extract_crit_table(cropped, special_cols)
                out = write_crit_skeleton(slug, name, num, letter, col_labels, cells)
                n_rows = len({c["row_label"] for c in cells})
                n_alts = sum(1 for c in cells if c["is_alt"])
                shape = "/".join(col_labels) if special_cols else "A-E"
                print(f"  {slug:24s} cols={shape:30s} {n_rows:2d} rows, "
                      f"{len(cells):4d} cells ({n_alts} alt-effect) -> {out.name}")
            except Exception as e:
                print(f"  {slug:24s} FAILED: {e}")

        print("Fumble tables:")
        for _pdfidx, slug, name, num, col_names in FUMBLE_TABLES:
            out = write_fumble_skeleton(slug, name, num, col_names)
            print(f"  {slug:24s} {len(FUMBLE_ROW_LABELS):2d} rows × "
                  f"{len(col_names)} cols -> {out.name}")


if __name__ == "__main__":
    main()
