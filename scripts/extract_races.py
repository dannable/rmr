"""Extract the Race Abilities Table T-1.1 from the RMSS Character Generation PDF.

Produces one .txt file per race under data/chargen/races/, mirroring the
shape of data/crit_tables/*.txt (header @-keys + data lines).

Approach:
  - Read PDF page 3 (the canonical placement of T-1.1 in §3.3). Page 31 has
    an identical reprint in §11.1; we ignore it.
  - Extract text and walk it line by line. The 12 race names are a fixed
    list, so we match prefixes against that list rather than doing
    positional/x-bucket reconstruction.
  - The page has two blocks for the same set of races:
        (1) racial stat-mod table: 10 stat mods + 5 RR mods + 1 BG-opts col
        (2) skill-rank-bonus-progression table: 4 progressions (Body Dev,
            Channeling PP Dev, Essence PP Dev, Mentalism PP Dev), each
            five "•"-separated integers.
  - We write one file per race combining both blocks.

Re-run is idempotent: existing files are overwritten and the previous
contents are saved as .txt.bak (same convention as extract_skeletons.py).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pdfplumber

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent


def _find_pdf() -> Path:
    """Locate Rolemaster Character Generation.pdf. The PDF is gitignored, so
    a worktree might not have its own copy — fall back to the main repo
    (this worktree's grandparent of grandparent) when missing.
    """
    candidates = [
        ROOT / "Rolemaster Character Generation.pdf",
        # Worktree fallback: <main-repo>/Rolemaster Character Generation.pdf
        # The worktree lives at <main-repo>/.claude/worktrees/<name>/.
        ROOT.parent.parent.parent / "Rolemaster Character Generation.pdf",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(
        "Rolemaster Character Generation.pdf not found in any of:\n  "
        + "\n  ".join(str(c) for c in candidates)
    )


PDF_PATH = _find_pdf()
OUT_DIR = ROOT / "data" / "chargen" / "races"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# T-1.1 is on PDF page index 3 in our copy (§3.3 placement).
RACE_TABLE_PAGE_INDEX = 3

# Canonical list of race names in order. Matching is prefix-based on each
# line, so order matters only when one name is a prefix of another — there
# are none in this set. Names appear verbatim as they're printed in T-1.1.
RACES: tuple[str, ...] = (
    "Common Men",
    "Mixed Men",
    "High Men",
    "Wood Elves",
    "Grey Elves",
    "High Elves",
    "Half-elves",
    "Dwarves",
    "Halflings",
    "Common Orcs",
    "Greater Orcs",
    "Half-orcs",
)

STAT_CODES = ("Ag", "Co", "Me", "Re", "SD", "Em", "In", "Pr", "Qu", "St")
RR_CODES = ("Ess", "Chan", "Ment", "Pois", "Dis")

PROGRESSION_LABELS = (
    "body_dev_prog",   # column header: Body Development
    "chan_pp_prog",    # Channeling PP Development
    "ess_pp_prog",     # Essence PP Development
    "ment_pp_prog",    # Mentalism PP Development
)

# Tokens within a progression are separated by " • " (U+2022). pdfplumber
# may render the bullet either as the literal char or surrounded by spaces.
PROGRESSION_BULLET = "•"


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

def _strip_race_prefix(line: str, race: str) -> str | None:
    """If `line` contains "<race> ", return everything after that occurrence.

    pdfplumber's text extraction sometimes folds the page's side-caption text
    into the table's leftmost column. e.g. "High Men"'s row on page 3 comes
    out as "Table T-1.1 High Men -2 +4 ...". Searching for the race name as
    a substring (rather than line.startswith) handles that without losing
    matches on clean rows. None of the 12 race names is a prefix of another.
    """
    needle = race + " "
    idx = line.find(needle)
    if idx != -1:
        return line[idx + len(needle):].strip()
    if line.strip() == race:
        return ""
    return None


def parse_stat_block(text: str) -> dict[str, dict]:
    """Parse the racial-stat-mod block (10 stat + 5 RR + 1 BG opts per race).

    Returns {race_name: {stat_mods: {...}, rr_mods: {...}, bg_opts: int}}.
    """
    out: dict[str, dict] = {}
    for race in RACES:
        match = None
        for line in text.splitlines():
            rest = _strip_race_prefix(line.strip(), race)
            if rest is None:
                continue
            # The progression block also has lines starting with the race
            # name. Distinguish: the stat-mod row has 16 plain integers
            # while the progression row contains "•" bullets.
            if PROGRESSION_BULLET in rest:
                continue
            tokens = rest.split()
            ints = [t for t in tokens if re.fullmatch(r"[+-]?\d+", t)]
            if len(ints) >= 16:
                match = ints[:16]
                break
        if match is None:
            raise RuntimeError(f"could not find stat-mod row for {race!r}")
        stat_mods = dict(zip(STAT_CODES, (int(x) for x in match[:10])))
        rr_mods = dict(zip(RR_CODES, (int(x) for x in match[10:15])))
        bg_opts = int(match[15])
        out[race] = {"stat_mods": stat_mods, "rr_mods": rr_mods, "bg_opts": bg_opts}
    return out


def parse_progression_block(text: str) -> dict[str, dict]:
    """Parse the four 5-step progressions per race.

    Returns {race_name: {body_dev_prog: "0 • 6 • 4 • 2 • 1", ...}}.
    """
    out: dict[str, dict] = {}
    for race in RACES:
        found: dict[str, str] | None = None
        for line in text.splitlines():
            rest = _strip_race_prefix(line.strip(), race)
            if rest is None or PROGRESSION_BULLET not in rest:
                continue
            # Split on whitespace; pick out integers (handling +N too).
            tokens = [t for t in rest.split() if t != PROGRESSION_BULLET]
            ints = [t for t in tokens if re.fullmatch(r"[+-]?\d+", t)]
            if len(ints) < 20:
                continue
            # Re-group into four 5-tuples.
            groups = [ints[i:i + 5] for i in range(0, 20, 5)]
            found = {
                label: " " + PROGRESSION_BULLET + " " for label in []
            }  # placeholder; replaced below
            found = {
                label: f" {PROGRESSION_BULLET} ".join(group)
                for label, group in zip(PROGRESSION_LABELS, groups)
            }
            break
        if found is None:
            raise RuntimeError(f"could not find progression row for {race!r}")
        out[race] = found
    return out


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

def _slug(race: str) -> str:
    return race.lower().replace(" ", "_").replace("-", "_")


def _fmt_stat_mods(mods: dict[str, int]) -> str:
    return " ".join(f"{code}={'+' if v > 0 else ''}{v}" for code, v in mods.items())


def write_race_file(
    race: str,
    stats: dict,
    progs: dict,
) -> Path:
    slug = _slug(race)
    out = OUT_DIR / f"{slug}.txt"
    if out.exists():
        out.replace(out.with_suffix(".txt.bak"))

    lines = [
        f"# {race}",
        "# Source: Rolemaster Character Generation, Race Abilities Table T-1.1 (§3.3).",
        "# Generated by scripts/extract_races.py.",
        "#",
        f"@name:           {race}",
        f"@slug:           {slug}",
        f"@stat_mods:      {_fmt_stat_mods(stats['stat_mods'])}",
        f"@rr_mods:        {_fmt_stat_mods(stats['rr_mods'])}",
        f"@bg_opts:        {stats['bg_opts']}",
        f"@body_dev_prog:  {progs['body_dev_prog']}",
        f"@chan_pp_prog:   {progs['chan_pp_prog']}",
        f"@ess_pp_prog:    {progs['ess_pp_prog']}",
        f"@ment_pp_prog:   {progs['ment_pp_prog']}",
    ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"Reading {PDF_PATH}")
    with pdfplumber.open(PDF_PATH) as pdf:
        page = pdf.pages[RACE_TABLE_PAGE_INDEX]
        # x_tolerance=3 prevents tokens like "+100" from getting split on
        # narrow kerning (a known pdfplumber default-tolerance issue).
        text = page.extract_text(x_tolerance=3) or ""

    stats_by_race = parse_stat_block(text)
    progs_by_race = parse_progression_block(text)

    print(f"Writing {len(RACES)} race files to {OUT_DIR}")
    for race in RACES:
        out = write_race_file(race, stats_by_race[race], progs_by_race[race])
        print(f"  {race:14s} -> {out.name}")

    print()
    print("Next: review the generated files; then write core/chargen/race.py")
    print("with a loader that turns these into structured Race dataclasses,")
    print("along with unit tests pinning known values (High Men: +4 Pr, -5 Ess RR, etc).")


if __name__ == "__main__":
    main()
