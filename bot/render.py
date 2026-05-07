"""Convert core/ result dicts into discord.Embed objects.

Pure rendering — no DB calls, no Discord client interaction. Each function
takes plain Python data and returns an Embed ready to send.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import discord

from core import CRIT_TYPE_NAMES, percentile_faces
from effects import pretty_effect

log = logging.getLogger(__name__)


# ---- d% (percentile-dice) emoji map --------------------------------------

# Loaded once at module import. Format produced by
# scripts/upload_dice_emoji.py:
#     {"tens": {"0": "<:d10t00:NNN>", "10": "<:d10t10:NNN>", ...},
#      "ones": {"0": "<:d10o0:NNN>",  "1":  "<:d10o1:NNN>",  ...}}
# Missing file or malformed JSON falls back to text-only display.
_DICE_EMOJI: dict[str, dict[str, str]] | None = None


def _load_dice_emoji() -> dict[str, dict[str, str]] | None:
    from . import config
    p = Path(config.DICE_EMOJI_PATH)
    if not p.is_file():
        log.info("dice emoji map not found at %s — falling back to text d%%", p)
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "tens" not in data or "ones" not in data:
            raise ValueError("expected keys 'tens' and 'ones'")
        return data
    except Exception as exc:  # noqa: BLE001
        log.warning("failed to load dice emoji map %s: %s", p, exc)
        return None


_DICE_EMOJI = _load_dice_emoji()


def _dice_pair(value: int) -> str:
    """Render one d100 result as a tens-die + ones-die pair.

    Uses Discord custom emoji when available; falls back to a compact text
    form like ``70|8`` (in inline code, monospaced) otherwise.
    """
    tens, ones = percentile_faces(value)
    em = _DICE_EMOJI
    if em:
        t = em.get("tens", {}).get(str(tens))
        o = em.get("ones", {}).get(str(ones))
        if t and o:
            return f"{t}{o}"
    return f"`{tens:02d}|{ones}`"


def format_d100_visual(rolls: list[int], direction: str | None) -> str:
    """Render a sequence of d100 rolls as d% pairs, joined by + or −.

    Examples (with emoji loaded):
        [78]           ->  '<:d10t70:..><:d10o8:..>'
        [99, 47] high  ->  '<…> + <…>'
        [3, 12]  low   ->  '<…> − <…>'
    """
    pairs = [_dice_pair(r) for r in rolls]
    if direction == "low" and len(pairs) > 1:
        return pairs[0] + "".join(f" − {p}" for p in pairs[1:])
    return " + ".join(pairs)


# ---- color palette --------------------------------------------------------

# Severity-graded colors (green → red).
SEVERITY_COLORS = {
    "A": 0x4CAF50,  # green
    "B": 0x9CCC65,  # yellow-green
    "C": 0xFFEB3B,  # yellow
    "D": 0xFF9800,  # orange
    "E": 0xF44336,  # red
}
COLOR_HIT    = 0x2196F3   # plain hits, no crit (blue)
COLOR_MISS   = 0x9E9E9E   # gray
COLOR_FUMBLE = 0x880E4F   # dark magenta
COLOR_INFO   = 0x607D8B   # blue-gray (lists)


# ---- helpers --------------------------------------------------------------

def _band(row: dict) -> str:
    return (str(row["roll_min"]) if row["roll_min"] == row["roll_max"]
            else f"{row['roll_min']}-{row['roll_max']}")


def _color_for_severity(sev: str | None) -> int:
    if not sev:
        return COLOR_HIT
    return SEVERITY_COLORS.get(sev, COLOR_HIT)


# ---- attack-result embed (used by /rmr and /attack) -----------------------

def attack_embed(*,
                 weapon_name: str,
                 at: int,
                 ob: int,
                 db: int = 0,
                 rolls: list[int] | None,
                 roll_value: int | None,
                 direction: str | None,
                 attack_total: int | None,
                 res: dict | None,
                 was_capped_chart: bool = False,
                 cap_value: int | None = None,
                 cap_label: str | None = None,
                 cap_term: str | None = None,
                 ) -> discord.Embed:
    """Render the attack-resolution step.

    `rolls`/`roll_value`/`direction`/`attack_total` are all None for the
    static /attack lookup (no dice). `res` is the attack_result row dict
    (or None if no entry on the chart).
    """
    title = f"{weapon_name} vs AT{at}, OB +{ob}"
    if db:
        title += f", DB {db}"

    # Description: dice math (or static "roll N" line)
    if rolls is not None:
        oe_tag = f"  *(open-ended {direction})*" if direction else ""
        math = f"**{roll_value}**{oe_tag}, +OB {ob}"
        if db:
            math += f", −DB {db}"
        description = (f"d% {format_d100_visual(rolls, direction)} = "
                       f"{math} → **{attack_total}**")
    else:
        description = f"Roll: **{attack_total}**"

    # No chart entry at all (total below chart minimum)
    if res is None:
        embed = discord.Embed(title=title, description=description, color=COLOR_MISS)
        embed.add_field(name="Result",
                        value=f"miss — {attack_total} below chart minimum",
                        inline=False)
        return embed

    band = _band(res)
    cap_tag = "  *(capped to chart max)*" if was_capped_chart else ""
    cell = f"**band {band}{cap_tag}: `{res['raw']}`**"

    # Fumble cell (F on chart)
    if res["is_fumble"]:
        embed = discord.Embed(title=title, description=description, color=COLOR_FUMBLE)
        embed.add_field(name="Result", value=f"{cell} — **FUMBLE**", inline=False)
        return embed

    # Plain miss
    if res["raw"] == "-":
        embed = discord.Embed(title=title, description=description, color=COLOR_MISS)
        embed.add_field(name="Result", value=f"{cell} — miss (no damage)", inline=False)
        return embed

    # Hit, with optional crit
    parts = [f"**{res['hits']} hits**"]
    if res["crit_severity"]:
        if res["crit_type"]:
            ctype = CRIT_TYPE_NAMES.get(res["crit_type"], res["crit_type"])
            parts.append(f"severity **{res['crit_severity']}** {ctype} crit")
        else:
            parts.append(f"severity **{res['crit_severity']}** crit")

    color = _color_for_severity(res["crit_severity"])
    embed = discord.Embed(title=title, description=description, color=color)
    embed.add_field(name="Result", value=f"{cell} — {', '.join(parts)}", inline=False)

    if cap_value is not None:
        term = cap_term or "Size"
        embed.set_footer(text=f"{term} cap ({cap_label}) applied: total clamped to {cap_value}")
    return embed


# ---- UM-fumble preempt embed (used by /rmr only) --------------------------

def um_fumble_embed(*,
                    weapon_name: str,
                    at: int,
                    ob: int,
                    db: int = 0,
                    rolls: list[int],
                    raw_roll: int,
                    fumble_min: int,
                    fumble_max: int,
                    ) -> discord.Embed:
    title = f"{weapon_name} vs AT{at}, OB +{ob}"
    if db:
        title += f", DB {db}"
    description = (f"d% {format_d100_visual(rolls, None)} — "
                   f"unmodified **{raw_roll}** in fumble range "
                   f"`{fumble_min:02d}-{fumble_max:02d}` UM")
    embed = discord.Embed(title=title, description=description, color=COLOR_FUMBLE)
    embed.add_field(name="Result", value="**FUMBLE**", inline=False)
    return embed


# ---- crit embed (used by all crit chains and direct /crit) ----------------

def crit_embed(crit: dict, crit_die: int | None = None) -> discord.Embed:
    """Render a critical_result cell.

    `crit_die` is the d100 roll on the crit chart. When supplied (chained
    from /rmr or passed to /attack), the d% pair is rendered above the
    band/narrative so the GM can see the dice. Pass None for direct
    /crit lookups where the user already supplied the roll value.
    """
    title = f"{crit['crit_table_name']} {crit['severity']} crit"
    band = _band(crit)
    narrative = crit["narrative"] or "*[narrative TODO — fill in from your copy]*"
    color = _color_for_severity(crit["severity"])

    if crit_die is not None:
        header = f"d% {_dice_pair(crit_die)} = **{crit_die}**\n"
    else:
        header = ""

    embed = discord.Embed(title=title,
                          description=f"{header}**Band {band}**\n{narrative}",
                          color=color)
    if crit["effects"]:
        lines = []
        for eff in crit["effects"]:
            cond = f"`[{eff['condition']}]` " if eff["condition"] else ""
            lines.append(f"{cond}{pretty_effect(eff['raw_code'])}")
        embed.add_field(name="Effect", value="\n".join(lines), inline=False)
    return embed


# ---- fumble embed (used by /rmr fumble chain and direct /fumble) ----------

def fumble_embed(row: dict, fumble_die: int | None = None) -> discord.Embed:
    title = f"{row['table_name']} / {row['col_name']}"
    band = _band(row)
    narrative = row["narrative"] or "*[narrative TODO]*"

    if fumble_die is not None:
        header = f"d% {_dice_pair(fumble_die)} = **{fumble_die}**\n"
    else:
        header = ""

    return discord.Embed(title=title,
                         description=f"{header}**Band {band}**\n{narrative}",
                         color=COLOR_FUMBLE)


# ---- info / list embeds ---------------------------------------------------

def weapons_embed(weapons: list[str]) -> discord.Embed:
    embed = discord.Embed(title="Loaded weapons", color=COLOR_INFO)
    embed.description = "\n".join(f"• {w}" for w in weapons) if weapons else "*none loaded*"
    return embed


def charts_embed(crit_charts: list[dict], fumble_tables: list[dict]) -> discord.Embed:
    embed = discord.Embed(title="Loaded charts", color=COLOR_INFO)
    if crit_charts:
        lines = [f"`{c['table_number']}` — {c['name']}" for c in crit_charts]
        embed.add_field(name="Critical Strike Tables",
                        value="\n".join(lines), inline=False)
    if fumble_tables:
        lines = [f"`{f['table_number']}` — {f['name']}" for f in fumble_tables]
        embed.add_field(name="Fumble Tables",
                        value="\n".join(lines), inline=False)
    if not crit_charts and not fumble_tables:
        embed.description = "*none loaded*"
    return embed
