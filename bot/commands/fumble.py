"""/fumble — direct lookup on a fumble table."""

from __future__ import annotations

import discord
from discord import app_commands

from core import connect, fumble_lookup, search_fumble_tables

from .. import render


async def fumble_table_autocomplete(interaction: discord.Interaction, current: str
                                     ) -> list[app_commands.Choice[str]]:
    try:
        conn = connect()
        try:
            names = search_fumble_tables(conn, current, limit=25)
        finally:
            conn.close()
    except Exception:
        names = []
    return [app_commands.Choice(name=n, value=n) for n in names]


def register(tree: app_commands.CommandTree) -> None:

    @tree.command(
        name="fumble",
        description="Look up a fumble-table cell by table, column index, and d100 roll.",
    )
    @app_commands.describe(
        table="Fumble table name (autocomplete)",
        col_index="Column index (1-based; e.g. 1=One-Handed Arms)",
        roll="d100 roll on the fumble table (1-100)",
    )
    @app_commands.autocomplete(table=fumble_table_autocomplete)
    async def fumble(
        interaction: discord.Interaction,
        table: str,
        col_index: app_commands.Range[int, 1, 10],
        roll: app_commands.Range[int, 1, 100],
    ) -> None:
        conn = connect()
        try:
            res = fumble_lookup(conn, table, col_index, roll)
        finally:
            conn.close()
        if res is None:
            await interaction.response.send_message(
                f"No entry: `{table}` / col `{col_index}` / roll `{roll}`.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(embed=render.fumble_embed(res, roll))
