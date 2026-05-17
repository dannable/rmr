"""Extract chargen reference data from Rolemaster Character Generation PDF.

This is the Phase-0 ingest pass for the character builder — analogous to
extract_skeletons.py for the Arms Law charts. Day-1 scope:

  1. Dump raw text from the pages covering §3 Culture & Race (pp 21-27 in
     the book; PDF indices 22-28 in our copy). Output goes to
     data/chargen/_raw/ so a human can verify alignment before we commit
     to structured parsers.
  2. Extract the Basic Stat Bonus Table T-2.1 (already transcribed into
     core/chargen/stats.py) as a cross-check.

Later phases will add structured parsers for:
  - Race Abilities Table T-1.1 (stat mods, RR mods, BG options)
  - Culture adolescence skill ranks
  - Profession Table T-1.4 (prime stats, realm, profession bonuses)
  - Skill cost matrix
  - Training packages
  - Hobbies / Background Options
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pdfplumber

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = ROOT / "Rolemaster Character Generation.pdf"
OUT_DIR = ROOT / "data" / "chargen" / "_raw"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Book pages 21-27 (§3 Culture & Race) map to PDF indices ~22-28 in our PDF.
# Verified by the outline pass in .scratch/pdf_outline.txt: PDF page 22 starts
# the body of §3 (after the cover/TOC pages).
CULTURE_RACE_PAGES = list(range(20, 30))

# §5 Stats (book p. 27) lives around PDF index 9-10 per our copy's pagination,
# and §12.3 Stat Bonus table is on PDF index ~28 (book p. 54). The exact PDF
# page for T-2.1 was confirmed by hand: see core.chargen.stats.
STAT_BONUS_TABLE_PAGE = 28


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")


def dump_page_text(pdf, idx: int, label: str) -> Path:
    text = pdf.pages[idx].extract_text(x_tolerance=2) or ""
    out = OUT_DIR / f"page{idx:03d}_{_safe(label)}.txt"
    out.write_text(text, encoding="utf-8")
    return out


def dump_page_words(pdf, idx: int, label: str) -> Path:
    """Word-level dump preserving x/y positions — needed for table parsing later."""
    words = pdf.pages[idx].extract_words(
        x_tolerance=2, y_tolerance=2, keep_blank_chars=False, use_text_flow=False
    )
    lines: list[str] = ["x0\ttop\tx1\tbottom\ttext"]
    for w in words:
        lines.append(
            f"{w['x0']:.2f}\t{w['top']:.2f}\t{w['x1']:.2f}\t{w['bottom']:.2f}\t{w['text']}"
        )
    out = OUT_DIR / f"page{idx:03d}_{_safe(label)}.words.tsv"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> None:
    if not PDF_PATH.exists():
        print(f"PDF not found: {PDF_PATH}", file=sys.stderr)
        sys.exit(1)

    print(f"Dumping raw pages to {OUT_DIR}")
    with pdfplumber.open(PDF_PATH) as pdf:
        print(f"PDF has {len(pdf.pages)} pages")

        for idx in CULTURE_RACE_PAGES:
            if idx >= len(pdf.pages):
                break
            t = dump_page_text(pdf, idx, f"culture_race_p{idx}")
            w = dump_page_words(pdf, idx, f"culture_race_p{idx}")
            print(f"  page {idx:3d} -> {t.name}, {w.name}")

        # Stat-bonus page (already encoded; this is a cross-check artefact).
        t = dump_page_text(pdf, STAT_BONUS_TABLE_PAGE, "stat_bonus_T-2.1")
        w = dump_page_words(pdf, STAT_BONUS_TABLE_PAGE, "stat_bonus_T-2.1")
        print(f"  page {STAT_BONUS_TABLE_PAGE:3d} -> {t.name}, {w.name}")

    print()
    print("Next steps (manual review):")
    print("  1. Open data/chargen/_raw/ and skim the culture_race_pXX.txt dumps.")
    print("  2. Identify the Race Abilities Table T-1.1 grid in the .words.tsv —")
    print("     we'll write a positional parser similar to extract_skeletons.py.")
    print("  3. The dumped output is gitignored (under data/chargen/_raw/);")
    print("     authored data goes under data/chargen/{races,cultures,...}.")


if __name__ == "__main__":
    main()
