"""/weapons and /charts — list what's loaded in the DB. Ephemeral responses."""

from __future__ import annotations

import discord
from discord import app_commands

from core import connect, list_weapons, list_crit_tables, list_fumble_tables

from .. import render


def register(tree: app_commands.CommandTree) -> None:

    @tree.command(name="weapons", description="List all weapons loaded in the DB.")
    async def weapons_cmd(interaction: discord.Interaction) -> None:
        conn = connect()
        try:
            names = list_weapons(conn)
        finally:
            conn.close()
        await interaction.response.send_message(
            embed=render.weapons_embed(names), ephemeral=True,
        )

    @tree.command(name="charts",
                  description="List all crit and fumble charts loaded in the DB.")
    async def charts_cmd(interaction: discord.Interaction) -> None:
        conn = connect()
        try:
            crits = list_crit_tables(conn)
            fumbles = list_fumble_tables(conn)
        finally:
            conn.close()
        await interaction.response.send_message(
            embed=render.charts_embed(crits, fumbles), ephemeral=True,
        )
