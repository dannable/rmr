"""/fumble — direct lookup on a fumble table."""

from __future__ import annotations

import discord
from discord import app_commands


async def fumble_table_autocomplete(interaction: discord.Interaction, current: str
                                     ) -> list[app_commands.Choice[str]]:
    try:
        from core import connect, search_fumble_tables
        with connect() as conn:
            names = search_fumble_tables(conn, current, limit=25)
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
        col_index="Column index (1-based)",
        roll="d100 roll on the fumble table (1-100)",
    )
    @app_commands.autocomplete(table=fumble_table_autocomplete)
    async def fumble(
        interaction: discord.Interaction,
        table: str,
        col_index: app_commands.Range[int, 1, 10],
        roll: app_commands.Range[int, 1, 100],
    ) -> None:
        await interaction.response.send_message(
            f"[stub] /fumble table={table!r} col={col_index} roll={roll}",
            ephemeral=True,
        )
