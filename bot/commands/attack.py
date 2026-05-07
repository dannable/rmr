"""/rmr (dice roller) and /attack (static lookup)."""

from __future__ import annotations

import asyncio
from typing import Optional

import discord
from discord import app_commands

from core import (
    connect,
    d100,
    get_weapon, attack_lookup, size_cap, search_weapons,
    resolve_crit_table_id, crit_lookup, crit_lookup_by_name,
    fumble_lookup, parse_fumble_crit_chain,
    degree_label,
)

from .. import render


# Time gap between embeds in the chained /rmr flow. Just enough to feel like
# the bot is rolling, not so long that it feels laggy.
EMBED_GAP_SECONDS = 0.7


# ---------------------------------------------------------------------------
# autocomplete
# ---------------------------------------------------------------------------

async def weapon_autocomplete(interaction: discord.Interaction, current: str
                              ) -> list[app_commands.Choice[str]]:
    try:
        conn = connect()
        try:
            names = search_weapons(conn, current, limit=25)
        finally:
            conn.close()
    except Exception:
        names = []
    return [app_commands.Choice(name=n, value=n) for n in names]


# ---------------------------------------------------------------------------
# helpers (orchestration shared by /rmr and /attack)
# ---------------------------------------------------------------------------

def _is_um_fumble(weapon: dict, raw_roll: int) -> bool:
    return bool(
        weapon["fumble_unmodified"]
        and weapon["fumble_min"] is not None
        and weapon["fumble_min"] <= raw_roll <= weapon["fumble_max"]
    )


def _roll_attack_dice(no_open_ended: bool) -> tuple[int, list[int], int, str | None]:
    """Roll d100 with optional open-ended.
    Returns (raw_roll, all_rolls, final_value, direction).
    """
    raw_roll = d100()
    rolls = [raw_roll]
    if no_open_ended:
        return raw_roll, rolls, raw_roll, None
    if raw_roll >= 96:
        while True:
            r = d100()
            rolls.append(r)
            if r < 96:
                break
        return raw_roll, rolls, sum(rolls), "high"
    if raw_roll <= 5:
        while True:
            r = d100()
            rolls.append(r)
            if r < 96:
                break
        return raw_roll, rolls, rolls[0] - sum(rolls[1:]), "low"
    return raw_roll, rolls, raw_roll, None


async def _send_fumble_chain(interaction: discord.Interaction, conn,
                              weapon: dict) -> None:
    """Roll on the weapon's fumble table; chain into the named crit chart if
    the narrative says so. Sends followup embeds with EMBED_GAP_SECONDS pacing.
    """
    table_name = weapon.get("fumble_table_name")
    col_idx = weapon.get("fumble_column_index")
    if not table_name or not col_idx:
        await asyncio.sleep(EMBED_GAP_SECONDS)
        await interaction.followup.send(
            "Weapon has no fumble routing — roll on the appropriate Fumble Table manually.",
            ephemeral=True,
        )
        return

    fumble_die = d100()
    fumble_row = fumble_lookup(conn, table_name, col_idx, fumble_die)
    await asyncio.sleep(EMBED_GAP_SECONDS)
    if fumble_row is None:
        await interaction.followup.send(
            f"No entry on `{table_name}` col `{col_idx}` at `{fumble_die}`.",
            ephemeral=True,
        )
        return
    await interaction.followup.send(embed=render.fumble_embed(fumble_row, fumble_die))

    chain = parse_fumble_crit_chain(fumble_row.get("narrative"))
    if not chain:
        return
    sev, chart_name = chain
    crit_die = d100()
    crit = crit_lookup_by_name(conn, chart_name, sev, crit_die)
    await asyncio.sleep(EMBED_GAP_SECONDS)
    if crit is None:
        await interaction.followup.send(
            f"Could not chain to `{chart_name}` crit chart "
            f"(not loaded, or no entry at {sev}/{crit_die}).",
            ephemeral=True,
        )
        return
    await interaction.followup.send(embed=render.crit_embed(crit, crit_die))


# ---------------------------------------------------------------------------
# command registration
# ---------------------------------------------------------------------------

def register(tree: app_commands.CommandTree) -> None:

    # ============================================================
    # /rmr — full dice roller
    # ============================================================
    @tree.command(
        name="rmr",
        description="Roll a Rolemaster attack: d100 (open-ended) + OB − DB → chart → crit chain.",
    )
    @app_commands.describe(
        weapon="Weapon name (autocomplete)",
        at="Defender's armor type (1-20)",
        ob="Attacker's offensive bonus",
        db="Defender's defensive bonus (subtracted from the attack total)",
        degree=("Caps the attack roll for charts that scale by degree: "
                "Sweeps/Brawling use Size (Small/Medium/Large/Huge), "
                "Martial Arts Strikes uses Rank (1-4)."),
        no_open_ended="Disable open-ended d100 (default: enabled)",
    )
    @app_commands.autocomplete(weapon=weapon_autocomplete)
    @app_commands.choices(degree=[
        app_commands.Choice(name="1 — Small / Rank 1",  value=1),
        app_commands.Choice(name="2 — Medium / Rank 2", value=2),
        app_commands.Choice(name="3 — Large / Rank 3",  value=3),
        app_commands.Choice(name="4 — Huge / Rank 4",   value=4),
    ])
    async def rmr(
        interaction: discord.Interaction,
        weapon: str,
        at: app_commands.Range[int, 1, 20],
        ob: int,
        db: int = 0,
        degree: Optional[app_commands.Choice[int]] = None,
        no_open_ended: bool = False,
    ) -> None:
        conn = connect()
        try:
            weapon_dict = get_weapon(conn, weapon)
            if weapon_dict is None:
                await interaction.response.send_message(
                    f"Weapon `{weapon}` not found.", ephemeral=True,
                )
                return

            raw_roll, rolls, roll_value, direction = _roll_attack_dice(no_open_ended)

            # UM-fumble preempts everything else.
            if _is_um_fumble(weapon_dict, raw_roll):
                emb = render.um_fumble_embed(
                    weapon_name=weapon, at=at, ob=ob, db=db,
                    rolls=rolls, raw_roll=raw_roll,
                    fumble_min=weapon_dict["fumble_min"],
                    fumble_max=weapon_dict["fumble_max"],
                )
                await interaction.response.send_message(embed=emb)
                await _send_fumble_chain(interaction, conn, weapon_dict)
                return

            attack_total = roll_value + ob - db

            # Apply attacker-degree cap (Sweeps / Brawling = Size, MA Strikes = Rank).
            cap_value = None
            cap_label = None
            cap_term = None
            if degree:
                cap = size_cap(conn, weapon_dict["weapon_id"], degree.value)
                if cap is not None and attack_total > cap:
                    cap_value = cap
                    cap_term = weapon_dict.get("degree_term") or "Size"
                    cap_label = degree_label(cap_term, degree.value)
                    attack_total = cap

            res, was_capped_chart = attack_lookup(
                conn, weapon_dict["weapon_id"], at, attack_total
            )

            attack_emb = render.attack_embed(
                weapon_name=weapon, at=at, ob=ob, db=db,
                rolls=rolls, roll_value=roll_value, direction=direction,
                attack_total=attack_total, res=res,
                was_capped_chart=was_capped_chart,
                cap_value=cap_value, cap_label=cap_label, cap_term=cap_term,
            )
            await interaction.response.send_message(embed=attack_emb)

            # Empty cell → done after the first embed.
            if res is None or res["raw"] == "-":
                return

            # F cell on chart → fumble chain.
            if res["is_fumble"]:
                await _send_fumble_chain(interaction, conn, weapon_dict)
                return

            # Crit chain.
            if not res["crit_severity"]:
                return
            ct_id = resolve_crit_table_id(conn, res, weapon_dict["default_crit_table_id"])
            if ct_id is None:
                await asyncio.sleep(EMBED_GAP_SECONDS)
                await interaction.followup.send(
                    "Could not resolve crit table — chart may not be loaded.",
                    ephemeral=True,
                )
                return

            crit_die = d100()
            crit = crit_lookup(conn, ct_id, res["crit_severity"], crit_die)
            await asyncio.sleep(EMBED_GAP_SECONDS)
            if crit is None:
                await interaction.followup.send(
                    f"No entry on `{res['crit_severity']}` column at `{crit_die}`.",
                    ephemeral=True,
                )
                return
            await interaction.followup.send(embed=render.crit_embed(crit, crit_die))
        finally:
            conn.close()

    # ============================================================
    # /attack — static lookup (no dice on the attack roll)
    # ============================================================
    @tree.command(
        name="attack",
        description="Static attack-chart lookup (no dice). Optionally chains to a crit roll.",
    )
    @app_commands.describe(
        weapon="Weapon name (autocomplete)",
        armor_type="Defender's armor type (1-20)",
        attack_roll="Modified attack-roll total",
        crit_roll="Optional d100 for the crit chain",
    )
    @app_commands.autocomplete(weapon=weapon_autocomplete)
    async def attack(
        interaction: discord.Interaction,
        weapon: str,
        armor_type: app_commands.Range[int, 1, 20],
        attack_roll: int,
        crit_roll: Optional[app_commands.Range[int, 1, 100]] = None,
    ) -> None:
        conn = connect()
        try:
            weapon_dict = get_weapon(conn, weapon)
            if weapon_dict is None:
                await interaction.response.send_message(
                    f"Weapon `{weapon}` not found.", ephemeral=True,
                )
                return

            res, was_capped = attack_lookup(
                conn, weapon_dict["weapon_id"], armor_type, attack_roll
            )
            attack_emb = render.attack_embed(
                weapon_name=weapon, at=armor_type, ob=0,
                rolls=None, roll_value=None, direction=None,
                attack_total=attack_roll, res=res,
                was_capped_chart=was_capped,
            )
            await interaction.response.send_message(embed=attack_emb)

            # Optional crit chain
            if crit_roll is None or res is None:
                return
            if not res.get("crit_severity"):
                return
            ct_id = resolve_crit_table_id(conn, res, weapon_dict["default_crit_table_id"])
            if ct_id is None:
                await asyncio.sleep(EMBED_GAP_SECONDS)
                await interaction.followup.send(
                    "Could not resolve crit table — chart may not be loaded.",
                    ephemeral=True,
                )
                return
            crit = crit_lookup(conn, ct_id, res["crit_severity"], crit_roll)
            await asyncio.sleep(EMBED_GAP_SECONDS)
            if crit is None:
                await interaction.followup.send(
                    f"No entry on `{res['crit_severity']}` column at `{crit_roll}`.",
                    ephemeral=True,
                )
                return
            await interaction.followup.send(embed=render.crit_embed(crit, crit_roll))
        finally:
            conn.close()
