"""/crit — direct lookup on a critical strike chart."""

from __future__ import annotations

import discord
from discord import app_commands


async def crit_table_autocomplete(interaction: discord.Interaction, current: str
                                   ) -> list[app_commands.Choice[str]]:
    try:
        from core import connect, search_crit_tables
        with connect() as conn:
            names = search_crit_tables(conn, current, limit=25)
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
        await interaction.response.send_message(
            f"[stub] /crit chart={chart!r} severity={severity!r} roll={roll}",
            ephemeral=True,
        )
