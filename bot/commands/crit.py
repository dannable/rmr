"""/crit — direct lookup on a critical strike chart."""

from __future__ import annotations

import discord
from discord import app_commands

from core import connect, crit_lookup_by_name, search_crit_tables

from .. import render


async def crit_table_autocomplete(interaction: discord.Interaction, current: str
                                   ) -> list[app_commands.Choice[str]]:
    try:
        conn = connect()
        try:
            names = search_crit_tables(conn, current, limit=25)
        finally:
            conn.close()
    except Exception:
        names = []
    return [app_commands.Choice(name=n, value=n) for n in names]


def register(tree: app_commands.CommandTree) -> None:

    @tree.command(
        name="crit",
        description="Look up a critical strike chart cell by chart, severity, and d100 roll.",
    )
    @app_commands.describe(
        chart="Crit chart name (autocomplete)",
        severity="Column label — usually A/B/C/D/E (case-sensitive)",
        roll="d100 roll on the crit chart (1-100)",
    )
    @app_commands.autocomplete(chart=crit_table_autocomplete)
    async def crit(
        interaction: discord.Interaction,
        chart: str,
        severity: str,
        roll: app_commands.Range[int, 1, 100],
    ) -> None:
        conn = connect()
        try:
            res = crit_lookup_by_name(conn, chart, severity, roll)
        finally:
            conn.close()
        if res is None:
            await interaction.response.send_message(
                f"No entry: `{chart}` / `{severity}` / roll `{roll}` "
                "(check chart name and severity column).",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(embed=render.crit_embed(res, roll))
