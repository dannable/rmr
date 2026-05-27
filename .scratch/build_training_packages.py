"""Extract RMSS training-package data from an ERA `.era` archive.

Format reuse: the .era is the same reversed-base64-encoded ZIP we saw
for `rmfrpCharacterLaw.professions.era`. Inside are 36
<Name>.trainingPackage.XML files.

Output: one file per TP at data/chargen/training_packages/<slug>.txt
using a layered @-marker format. Each TP carries:

  * @name / @slug / @category / @default_cost
  * @description (free-form, wrapped)
  * @specials block — one "<chance> | <description>" per line
  * @stat_gains block — one line per stat slot:
      - "<Code>"                  guaranteed stat (e.g. "St")
      - "<A> | <B> | <C>"         pick-one-of choice form
  * Rank-assignment blocks — one `@@ <n>` opener per slot, then a few
    @-keys describing the assignment. Optional nested restrictions are
    rendered as additional @-keys with structured values. See the
    inline schema docstring on `render_rank_assignment` below.
  * @profession_costs block — "<Profession Name>: <DP cost>" per line

Idempotent: re-runs regenerate every file from the .era source.
"""

from __future__ import annotations

import base64
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "chargen" / "training_packages"

# Map source tag → (era filename, source-book comment). Add an entry
# when ingesting a new supplement's .era. The `source` tag is stored on
# training_package.source so the SPA can filter by source book.
SOURCE_TO_ERA: dict[str, tuple[str, str]] = {
    "character_law": (
        "rmfrpCharacterLaw.trainingPackages.era",
        "Rolemaster Fantasy Roleplaying — Character Law",
    ),
    "essence_companion": (
        "rmfrpEssenceCompanion.trainingPackages.era",
        "Essence Companion (RMSS)",
    ),
    "channeling_companion": (
        "rmfrpChannelingCompanion.trainingPackages.era",
        "Channeling Companion (RMSS)",
    ),
    "mentalism_companion": (
        "rmfrpMentalismCompanion.trainingPackages.era",
        "Mentalism Companion (RMSS)",
    ),
    "sohk": (
        "rmfrpSchoolOfHardKnocks.trainingPackages.era",
        "School of Hard Knocks (RMSS)",
    ),
}


# ---------------------------------------------------------------------------
# .era → ZIP → entries (lifted from build_professions; same format).
# ---------------------------------------------------------------------------

def decode_era(path: Path) -> dict[str, bytes]:
    raw = path.read_bytes().replace(b"\r", b"").replace(b"\n", b"")
    decoded = base64.b64decode(raw[::-1] + b"==", validate=False)
    with zipfile.ZipFile(io.BytesIO(decoded)) as z:
        return {name: z.read(name) for name in z.namelist()}


# Regex used to repair malformed XML: at least one entry in the
# Mentalism Companion archive (Hermit.trainingPackage.XML) has adjacent
# attributes with no separator — `reference="..."categoryRanks="1"`
# instead of `reference="..." categoryRanks="1"`. Insert a space
# between the closing quote and the next attribute name so the XML
# parser accepts it. Safe even for well-formed XML: in valid XML, the
# character after a closing `"` is always whitespace, `>`, `/`, or `?`,
# never a letter — so the regex only matches data bugs.
_RE_MISSING_ATTR_SPACE = re.compile(rb'"([A-Za-z])')


def _repair_xml(payload: bytes) -> bytes:
    return _RE_MISSING_ATTR_SPACE.sub(rb'" \1', payload)


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _attr(el: ET.Element, name: str, default: str = "") -> str:
    return el.attrib.get(name, default).strip()


def _wrap(text: str, width: int = 78) -> list[str]:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []
    words = text.split(" ")
    out: list[list[str]] = [[]]
    n = 0
    for w in words:
        if n + len(w) + 1 > width and out[-1]:
            out.append([])
            n = 0
        out[-1].append(w)
        n += len(w) + 1
    return [" " + " ".join(line) for line in out]


# ---------------------------------------------------------------------------
# Per-TP render
# ---------------------------------------------------------------------------

def render_specials(root: ET.Element) -> list[str]:
    lines: list[str] = []
    for sp in root.iter("Special"):
        chance = _attr(sp, "chance")
        desc = _attr(sp, "description")
        if chance and desc:
            lines.append(f"{chance} | {desc}")
    return lines


def render_stat_gains(root: ET.Element) -> list[str]:
    """One line per slot.

    A bare `<StatGain>Code</StatGain>` becomes a guaranteed gain — the
    code on its own line. A `<StatGain>` that wraps `<StatGainChoice>`
    children becomes a pipe-separated choice line, e.g. "Em | In | Pr".
    """
    lines: list[str] = []
    sgs = root.find("StatGains")
    if sgs is None:
        return lines
    for sg in sgs.findall("StatGain"):
        choices = sg.findall("StatGainChoice")
        if choices:
            opts = [(c.text or "").strip() for c in choices if (c.text or "").strip()]
            if opts:
                lines.append(" | ".join(opts))
        else:
            code = (sg.text or "").strip()
            if code:
                lines.append(code)
    return lines


def render_profession_costs(root: ET.Element) -> list[str]:
    out: list[str] = []
    for pc in root.iter("ProfessionCost"):
        prof = _attr(pc, "profession")
        cost = _attr(pc, "cost")
        if prof and cost:
            out.append(f"{prof}: {cost}")
    return out


def render_rank_assignment(ra: ET.Element, slot_n: int) -> list[str]:
    """Render one <RankAssignment> as a `@@ <slot>` block.

    A RankAssignment has one of two shapes:

      1. FIXED: `groupName` + `categoryName` attrs — points at exactly one
         (group, category). May still have nested SkillRestriction to lock
         a specific skill within that category.

      2. FLEXIBLE: `reference` attr (a human-readable label like
         "Melee Weapon") + zero or more `<CategoryRestriction>` children
         enumerating the allowed (group, category) pairs. May also have
         `<CategorySpreadRestriction maximum=N>` to cap how many of the
         options the player can spend ranks across.

    In both shapes the assignment carries `categoryRanks` and/or
    `skillRanks` integers. Inside the assignment, additional
    restrictions can appear:

      * <SkillRestriction name="X" classification="Y"/>
      * <SkillSpreadRestriction maximum="N"/>
      * <RanksAssignedRestriction maximum="N"/>
    """
    lines: list[str] = []
    ref = _attr(ra, "reference")
    group = _attr(ra, "groupName")
    cat = _attr(ra, "categoryName")
    cat_ranks = _attr(ra, "categoryRanks") or "0"
    skill_ranks = _attr(ra, "skillRanks") or "0"

    # Header line: @@ <slot> | <kind>
    if ref:
        lines.append(f"@@ {slot_n} | ref:{ref}")
    elif group and cat:
        lines.append(f"@@ {slot_n} | {group}/{cat}")
    else:
        lines.append(f"@@ {slot_n} | (unspecified)")

    lines.append(f"@cat_ranks: {cat_ranks}")
    lines.append(f"@skill_ranks: {skill_ranks}")

    for cr in ra.findall("CategoryRestriction"):
        g = _attr(cr, "groupName")
        c = _attr(cr, "categoryName")
        if g and c:
            lines.append(f"@cat_option: {g}/{c}")

    for sr in ra.findall("SkillRestriction"):
        n = _attr(sr, "name")
        klass = _attr(sr, "classification")
        if n:
            suffix = f" ({klass})" if klass else ""
            lines.append(f"@skill_option: {n}{suffix}")

    csr = ra.find("CategorySpreadRestriction")
    if csr is not None:
        m = _attr(csr, "maximum")
        if m:
            lines.append(f"@cat_spread_max: {m}")

    ssr = ra.find("SkillSpreadRestriction")
    if ssr is not None:
        m = _attr(ssr, "maximum")
        if m:
            lines.append(f"@skill_spread_max: {m}")

    rar = ra.find("RanksAssignedRestriction")
    if rar is not None:
        m = _attr(rar, "maximum")
        if m:
            lines.append(f"@ranks_assigned_max: {m}")

    return lines


def render_training_package(
    root: ET.Element,
    source_tag: str,
    source_book: str,
    era_filename: str,
) -> str:
    name = _attr(root, "name")
    slug = slugify(name)

    category_el = root.find("Category")
    category = (category_el.text or "").strip() if category_el is not None else ""

    desc_el = root.find("Description")
    description = (desc_el.text or "").strip() if desc_el is not None else ""

    dc_el = root.find("DefaultCost")
    default_cost = (dc_el.text or "").strip() if dc_el is not None else ""

    lines: list[str] = []
    lines.append(f"# Training Package: {name}")
    lines.append(f"# Source: {source_book} (ERA: {era_filename})")
    lines.append(f"# Generated by .scratch/build_training_packages.py")
    lines.append("#")
    lines.append(f"@name: {name}")
    lines.append(f"@slug: {slug}")
    lines.append(f"@source: {source_tag}")
    lines.append(f"@category: {category}")
    lines.append(f"@default_cost: {default_cost}")
    lines.append("@description:")
    lines.extend(_wrap(description))

    specials = render_specials(root)
    if specials:
        lines.append("")
        lines.append("# Random outfitting roll: "
                     "<chance%> | <item description>. Each row is rolled "
                     "independently.")
        lines.append("@specials:")
        lines.extend(specials)

    stat_lines = render_stat_gains(root)
    if stat_lines:
        lines.append("")
        lines.append("# Stat gains. One slot per line; a `X | Y | Z` line is "
                     "a pick-one choice.")
        lines.append("@stat_gains:")
        lines.extend(stat_lines)

    ras = root.find("RankAssignments")
    if ras is not None:
        lines.append("")
        lines.append("# " + "=" * 67)
        lines.append("# RANK ASSIGNMENTS")
        lines.append("# " + "=" * 67)
        for i, ra in enumerate(ras.findall("RankAssignment"), 1):
            lines.append("")
            lines.extend(render_rank_assignment(ra, i))

    prof_costs = render_profession_costs(root)
    if prof_costs:
        lines.append("")
        lines.append("@profession_costs:")
        lines.extend(prof_costs)

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

_SOURCE_SLUG_SUFFIX: dict[str, str] = {
    "character_law":        "",     # default — bare slug
    "essence_companion":    "ec",
    "channeling_companion": "cc",
    "mentalism_companion":  "mc",
    "sohk":                 "sohk",
}


def process_one_era(
    source_tag: str,
    era_filename: str,
    source_book: str,
    used_slugs: set[str],
) -> int:
    """Decode + render one .era archive. Returns the file-count written.

    Slug collisions between sources (e.g. "Librarian" appears in both
    Essence Companion and SOHK with different content) get disambiguated
    by appending `_<source_suffix>` to the colliding slug. SOURCE_TO_ERA
    insertion order decides who keeps the bare slug — character_law goes
    first, then the companions, so a Character Law "X" always claims
    "x.txt" and any later supplement's "X" becomes "x_ec.txt" / "x_sohk.txt"
    etc.
    """
    era_path = ROOT / "ERA" / era_filename
    if not era_path.exists():
        print(f"  skip source={source_tag}: missing {era_path}")
        return 0
    entries = decode_era(era_path)
    print(f"\n[{source_tag}] decoded {len(entries)} entries from {era_path.name}")

    suffix = _SOURCE_SLUG_SUFFIX.get(source_tag, source_tag)
    n_written = 0
    for filename, payload in sorted(entries.items()):
        root = ET.fromstring(_repair_xml(payload))
        name = _attr(root, "name")
        if not name:
            continue
        slug = slugify(name)
        if slug in used_slugs:
            disambiguated = f"{slug}_{suffix}" if suffix else f"{slug}_{source_tag}"
            print(f"  slug collision: {name!r} -> {disambiguated} "
                  f"(already used by an earlier source)")
            slug = disambiguated
        used_slugs.add(slug)
        text = render_training_package(root, source_tag, source_book, era_filename)
        # The @slug line embedded in the file must match the filename so
        # the loader stores it under the disambiguated slug.
        text = re.sub(r"^@slug:.*$", f"@slug: {slug}",
                      text, count=1, flags=re.MULTILINE)
        (OUT_DIR / f"{slug}.txt").write_text(text, encoding="utf-8", newline="\n")
        n_written += 1

        n_ras = len(list(root.iter("RankAssignment")))
        n_specials = len(list(root.iter("Special")))
        n_costs = len(list(root.iter("ProfessionCost")))
        print(f"  {slug:30s}  ras={n_ras:2d}  specials={n_specials:2d}  prof_costs={n_costs:2d}")

    return n_written


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    total = 0
    used_slugs: set[str] = set()
    for source_tag, (era_filename, source_book) in SOURCE_TO_ERA.items():
        total += process_one_era(source_tag, era_filename, source_book, used_slugs)

    print(f"\nwrote {total} training-package files across "
          f"{len(SOURCE_TO_ERA)} source(s)")


if __name__ == "__main__":
    main()
