"""Extract RMSS spell-list data from the canonical ERA archives.

Replaces the prior PDF-extraction pipeline (which produced row-misalignment
errors like 'Animal Restoration | I 1 animal | P | touch | U' — the
Roman numeral I leaked from the spell name into the area-of-effect
column). The ERA archives are the publisher's structured digital source
and carry every per-spell field correctly.

Five ERAs are ingested:

    ERA file                                       source tag           lists
    --------------------------------------------   -----------------    -----
    rmfrpSpellLaw.spellLists.era                   spell_law             168
    rmfrpChannelingCompanion.spellLists.era        channeling_companion   48
    rmfrpEssenceCompanion.spellLists.era           essence_companion      49
    rmfrpMentalismCompanion.spellLists.era         mentalism_companion    38
    rmfrpTreasureCompanion.spellLists.era          treasure_companion     22
                                                                       ----
                                                                        325

The Treasure Companion's "Divine Alchemy" and "General Alchemist Base"
categories don't carry an explicit realm. Convention applied here:

    Divine Alchemy           -> Channeling (divine magic = Channeling)
    General Alchemist Base   -> Essence    (alchemy is primarily Essence)

Output layout mirrors the existing scheme so load.py needs only the
new @source key and an extended @category CHECK on the DB side:

    data/spell_lists/<realm>/<slug>.txt   (one file per list)
    data/spell_lists/<realm>_classes.txt  (one file per realm)

Name slugs come from the spell-list name (lowercased, non-alnum -> '_').
No global name collisions exist across the 325 lists, verified by a
pre-extraction scan, so per-realm slug uniqueness is guaranteed.

Idempotent: re-runs regenerate every file from the ERA source.
"""

from __future__ import annotations

import argparse
import base64
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ERA_DIR = ROOT / "ERA"
OUT_DIR = ROOT / "data" / "spell_lists"

# Map source tag → .era filename. Order matters only for diagnostics
# (the loader treats every source uniformly).
SOURCE_TO_ERA: dict[str, str] = {
    "spell_law":             "rmfrpSpellLaw.spellLists.era",
    "channeling_companion":  "rmfrpChannelingCompanion.spellLists.era",
    "essence_companion":     "rmfrpEssenceCompanion.spellLists.era",
    "mentalism_companion":   "rmfrpMentalismCompanion.spellLists.era",
    "treasure_companion":    "rmfrpTreasureCompanion.spellLists.era",
}

# Map class name -> primary realm. Drives realm assignment for Base
# lists (whose category-string carries the class but not the realm).
# Hybrid spellcasters (Sorcerer, Mystic, Healer, Runemage) are filed
# under their "primary" realm per RMSS convention — the realm whose
# stat the profession leans on most heavily.
CLASS_REALMS: dict[str, str] = {
    # ── Channeling
    "Animist":       "Channeling",
    "Cleric":        "Channeling",
    "Healer":        "Channeling",
    "Paladin":       "Channeling",
    "Ranger":        "Channeling",
    # ── Essence
    "Dabbler":       "Essence",
    "Illusionist":   "Essence",
    "Magician":      "Essence",
    "Sorcerer":      "Essence",
    # ── Mentalism
    "Bard":          "Mentalism",
    "Lay Healer":    "Mentalism",
    "Magent":        "Mentalism",
    "Mentalist":     "Mentalism",
    "Monk":          "Mentalism",
    "Mystic":        "Mentalism",
    # ── Channeling Companion
    "Mythic":        "Channeling",
    "Priest":        "Channeling",
    "Summoner":      "Channeling",
    "Warlock":       "Channeling",
    # ── Essence Companion
    "Mana Molder":   "Essence",
    "Runemage":      "Essence",
    "Warrior Mage":  "Essence",
    # ── Mentalism Companion
    "Armsmaster":    "Mentalism",
    "Astrologer":    "Mentalism",
    "Enchanter":     "Mentalism",
    "Seer":          "Mentalism",
    # ── Treasure Companion alchemists
    "Channeling Alchemist": "Channeling",
    "Essence Alchemist":    "Essence",
    "Mentalist Alchemist":  "Mentalism",
    "General Alchemist":    "Essence",   # Treasure Companion convention
}

# Category strings the ERAs use, parsed into (sub_category, owning_class).
# A category like "RMFRP Spell Law - Animist Base" decomposes to
# sub_category="Base", owning_class="Animist". For lists with no class
# (Open / Closed / Evil), owning_class is None and the realm is parsed
# straight from the category suffix.
CATEGORY_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Open <Realm>, Closed <Realm>, Evil <Realm>
    (re.compile(r"^Open (Channeling|Essence|Mentalism)$"),   "Open"),
    (re.compile(r"^Closed (Channeling|Essence|Mentalism)$"), "Closed"),
    (re.compile(r"^Evil (Channeling|Essence|Mentalism)$"),   "Evil"),
    # <Class> Base — e.g. Animist Base, Mana Molder Base
    (re.compile(r"^(.+?) Base$"),                              "Base"),
    # <Realm> Training Package — Essence Companion / Mentalism Companion
    (re.compile(r"^(Channeling|Essence|Mentalism) Training Package$"),
                                                              "Training Package"),
    # Treasure Companion's standalone categories
    (re.compile(r"^Divine Alchemy$"),                          "Divine Alchemy"),
]


def decode_era(path: Path) -> dict[str, bytes]:
    """Decode a `.era` file into {filename: raw bytes} per archive entry.

    Same trick as build_professions.py: the byte stream is the base64
    encoding REVERSED — reverse-then-decode lands at a regular ZIP."""
    raw = path.read_bytes()
    stripped = raw.replace(b"\r", b"").replace(b"\n", b"")
    decoded = base64.b64decode(stripped[::-1] + b"==", validate=False)
    with zipfile.ZipFile(io.BytesIO(decoded)) as z:
        return {name: z.read(name) for name in z.namelist()}


def slugify(name: str) -> str:
    """Lowercase + non-alnum runs collapsed to underscore."""
    s = re.sub(r"[^a-z0-9]+", "_", name.lower())
    return s.strip("_")


def parse_category(cat_raw: str) -> tuple[str, str, str | None]:
    """Decompose an ERA <category> string into (realm, sub_category, class).

    The ERA prefixes everything with the book name, e.g.
    "RMFRP Spell Law - Animist Base" or
    "RMFRP Treasure Companion - Channeling Alchemist Base".

    Returns:
      realm        : 'Channeling' | 'Essence' | 'Mentalism'
      sub_category : the value that lands on spell_list.category
      class_name   : owning class, or None for shared-access lists

    Raises ValueError on unrecognised category structure so the
    extractor fails loudly rather than silently mis-filing a list."""
    # Strip the leading "RMFRP <Book Name> - " prefix.
    body = re.sub(r"^RMFRP [^-]+ - ", "", cat_raw).strip()

    for pat, sub_cat in CATEGORY_PATTERNS:
        m = pat.match(body)
        if not m:
            continue
        if sub_cat in ("Open", "Closed", "Evil"):
            # Pattern captured the realm directly.
            return (m.group(1), sub_cat, None)
        if sub_cat == "Base":
            # Captured the class; realm comes from CLASS_REALMS.
            class_name = m.group(1).strip()
            if class_name not in CLASS_REALMS:
                raise ValueError(
                    f"Unknown Base-list class {class_name!r} (full cat "
                    f"{cat_raw!r}) — extend CLASS_REALMS to map it."
                )
            return (CLASS_REALMS[class_name], "Base", class_name)
        if sub_cat == "Training Package":
            return (m.group(1), "Training Package", None)
        if sub_cat == "Divine Alchemy":
            # Treasure Companion convention: divine alchemy → Channeling.
            return ("Channeling", "Divine Alchemy", None)
    raise ValueError(
        f"Unrecognised category structure {cat_raw!r}. Extend "
        f"CATEGORY_PATTERNS or CLASS_REALMS."
    )


def _attr(el: ET.Element, name: str, default: str = "") -> str:
    return (el.attrib.get(name) or "").strip()


def _wrap_description(text: str, width: int = 78) -> list[str]:
    """Word-wrap a description into lines, preserving paragraph breaks."""
    if not text:
        return []
    out: list[str] = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            out.append("")
            continue
        line = ""
        for w in words:
            if not line:
                line = w
            elif len(line) + 1 + len(w) <= width:
                line += " " + w
            else:
                out.append(line)
                line = w
        if line:
            out.append(line)
    return out


def _emit_list_file(
    out_dir: Path,
    *,
    source: str,
    realm: str,
    sub_category: str,
    class_name: str | None,
    list_name: str,
    spells: list[dict],
) -> Path:
    """Write a per-list .txt in the canonical format.

    Format (extended with @source):
      # comment block describing provenance
      @source:  spell_law
      @realm:   Channeling
      @name:    Animal Mastery
      @category: Base
      @class:   Animist
      #
      <chart rows: level | name | area | duration | range | type>
      #
      # Descriptions
      @@ 1
      <wrapped description text>
      @@ 2
      ...
    """
    slug = slugify(list_name)
    out_path = out_dir / f"{slug}.txt"
    lines: list[str] = []
    lines.append(f"# Spell List — {list_name} ({sub_category})")
    lines.append(f"# Extracted from ERA {SOURCE_TO_ERA[source]}")
    lines.append("# Generated by scripts/build_spell_lists_era.py.")
    lines.append("#")
    lines.append(f"@source:    {source}")
    lines.append(f"@realm:     {realm}")
    lines.append(f"@name:      {list_name}")
    lines.append(f"@category:  {sub_category}")
    if class_name:
        lines.append(f"@class:     {class_name}")
    lines.append("#")
    lines.append("# Format: <level> | <spell_name> | <area_effect> | <duration> | <range> | <type>")
    lines.append("# A trailing '*' on the name marks a Concentration / continuing-effect spell.")
    lines.append("#")
    # Pipe-separated chart rows, sorted by level.
    for sp in sorted(spells, key=lambda s: (s["level"], s["name"])):
        nm = sp["name"] + ("*" if sp.get("starred") else "")
        lines.append(
            f"{sp['level']:>2} | {nm} | {sp['area'] or ''} | "
            f"{sp['duration'] or ''} | {sp['range'] or ''} | {sp['type'] or ''}"
        )
    # Description block.
    has_descs = any(sp.get("description") for sp in spells)
    if has_descs:
        lines.append("")
        lines.append("# Descriptions")
        for sp in sorted(spells, key=lambda s: (s["level"], s["name"])):
            desc = sp.get("description") or ""
            if not desc.strip():
                continue
            lines.append(f"@@ {sp['level']}")
            lines.extend(_wrap_description(desc))
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def _parse_xml(raw: bytes, source: str, ) -> dict:
    """Parse one spell-list XML into a structured dict."""
    root = ET.fromstring(raw.decode("utf-8", errors="replace"))
    cat = (root.findtext("category") or "").strip()
    name = (root.findtext("name") or "").strip()
    if not name or not cat:
        raise ValueError(f"{source}: XML missing <name> or <category>")
    realm, sub_cat, class_name = parse_category(cat)
    spells: list[dict] = []
    for sp in root.findall("spells/spell"):
        sp_name = (sp.findtext("name") or "").strip()
        starred = sp_name.endswith("*")
        if starred:
            sp_name = sp_name.rstrip("* ").rstrip()
        params = sp.find("parameters")
        area = duration = range_str = type_str = ""
        if params is not None:
            area      = (params.findtext("Area-of-Effect") or "").strip()
            duration  = (params.findtext("Duration") or "").strip()
            range_str = (params.findtext("Range") or "").strip()
            type_str  = (params.findtext("Type") or "").strip()
        try:
            level = int((sp.findtext("level") or "0").strip())
        except ValueError:
            level = 0
        spells.append({
            "level": level, "name": sp_name, "starred": starred,
            "area": area, "duration": duration,
            "range": range_str, "type": type_str,
            "description": (sp.findtext("description") or "").strip(),
        })
    return {
        "source": source, "realm": realm,
        "sub_category": sub_cat, "class_name": class_name,
        "list_name": name, "spells": spells,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--source", action="append",
        help="Subset of sources to process (default: all). "
             "Choices: " + ", ".join(sorted(SOURCE_TO_ERA)),
    )
    ap.add_argument(
        "--out", type=Path, default=OUT_DIR,
        help="Output directory (default: data/spell_lists).",
    )
    ap.add_argument(
        "--clean", action="store_true",
        help="Wipe the per-realm subdirectories before writing. Recommended "
             "for a fresh re-import; without it, stale PDF-derived files "
             "from earlier passes will persist.",
    )
    args = ap.parse_args()

    selected = sorted(args.source) if args.source else sorted(SOURCE_TO_ERA)
    bad = [s for s in selected if s not in SOURCE_TO_ERA]
    if bad:
        ap.error(f"Unknown sources: {bad}. "
                  f"Choices: {sorted(SOURCE_TO_ERA)}")

    args.out.mkdir(parents=True, exist_ok=True)

    # Collect everything first so we can build the per-realm class index
    # files at the end (one pass through all sources).
    lists_by_realm: dict[str, list[dict]] = defaultdict(list)
    for source in selected:
        era_path = ERA_DIR / SOURCE_TO_ERA[source]
        if not era_path.exists():
            print(f"  SKIP {source}: {era_path.name} not found")
            continue
        files = decode_era(era_path)
        print(f"  {source}: {len(files)} list XMLs in {era_path.name}")
        for fname, raw in files.items():
            parsed = _parse_xml(raw, source)
            lists_by_realm[parsed["realm"]].append(parsed)

    # Clean per-realm output dirs if asked.
    if args.clean:
        for realm in ("Channeling", "Essence", "Mentalism"):
            realm_dir = args.out / realm.lower()
            if realm_dir.is_dir():
                for f in realm_dir.glob("*.txt"):
                    f.unlink()

    # Emit per-list files and consolidated per-realm class index files.
    total_written = 0
    class_index_by_realm: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    # (class_name, list_name, source) so we can deduplicate within a
    # realm when we write the index — same (class, list) pair from
    # different sources is genuinely distinct, but a redundant within-
    # source duplicate is not.
    for realm, items in sorted(lists_by_realm.items()):
        realm_dir = args.out / realm.lower()
        realm_dir.mkdir(parents=True, exist_ok=True)
        for item in items:
            _emit_list_file(
                realm_dir,
                source=item["source"],
                realm=item["realm"],
                sub_category=item["sub_category"],
                class_name=item["class_name"],
                list_name=item["list_name"],
                spells=item["spells"],
            )
            total_written += 1
            if item["class_name"]:
                class_index_by_realm[realm].append((
                    item["class_name"], item["list_name"], item["source"],
                ))

    # Class index files — one per realm. The loader auto-grants every
    # declared class access to all Open + Closed lists in that realm
    # (per RMSS convention), so the index file only enumerates the
    # explicit Base-list memberships.
    for realm, pairs in class_index_by_realm.items():
        idx_path = args.out / f"{realm.lower()}_classes.txt"
        lines = [
            f"# {realm} Realm — class-to-list index",
            f"# Extracted from canonical ERA archives across:",
        ]
        sources_used = sorted({s for _, _, s in pairs})
        for s in sources_used:
            lines.append(f"#   - {SOURCE_TO_ERA[s]}")
        lines += [
            "# Generated by scripts/build_spell_lists_era.py.",
            "#",
            f"@realm: {realm}",
            "#",
            "# Every declared class also gets implicit access to all Open and",
            "# Closed lists in this realm — load.py grants those memberships",
            "# automatically; this file only enumerates the class-specific",
            "# Base / supplement Base lists.",
            "#",
            "# Format: <class_name> | <list_name>",
            "#",
        ]
        for class_name, list_name, _ in sorted(set(pairs)):
            lines.append(f"{class_name} | {list_name}")
        idx_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\nWrote {total_written} spell-list files + "
          f"{len(class_index_by_realm)} class index files to {args.out}/")


if __name__ == "__main__":
    main()
