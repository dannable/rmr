"""/weapons and /charts — list what's loaded in the DB. Ephemeral responses."""

from __future__ import annotations

import discord
from discord import app_commands


def register(tree: app_commands.CommandTree) -> None:

    @tree.command(
        name="weapons",
        description="List all weapons loaded in the DB.",
    )
    async def weapons(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "[stub] /weapons — would list loaded weapons",
            ephemeral=True,
        )

    @tree.command(
        name="charts",
        description="List all crit and fumble charts loaded in the DB.",
    )
    async def charts(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "[stub] /charts — would list loaded crit and fumble charts",
            ephemeral=True,
        )
