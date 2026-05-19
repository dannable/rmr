"""/spells, /spell-list, /spell, /spell-search — spell-list lookups."""

from __future__ import annotations

import discord
from discord import app_commands

from core import (
    connect,
    list_classes,
    search_classes,
    lists_for_class,
    search_spell_lists,
    get_spell_list,
    spells_on_list,
    classes_for_list,
    get_spell,
    search_spells,
)

from .. import render


# ---------------------------------------------------------------------------
# autocompletes
# ---------------------------------------------------------------------------

async def class_autocomplete(interaction: discord.Interaction, current: str
                              ) -> list[app_commands.Choice[str]]:
    try:
        conn = connect()
        try:
            names = search_classes(conn, current, limit=25)
        finally:
            conn.close()
    except Exception:
        names = []
    return [app_commands.Choice(name=n, value=n) for n in names]


async def spell_list_autocomplete(interaction: discord.Interaction, current: str
                                   ) -> list[app_commands.Choice[str]]:
    try:
        conn = connect()
        try:
            names = search_spell_lists(conn, current, limit=25)
        finally:
            conn.close()
    except Exception:
        names = []
    return [app_commands.Choice(name=n, value=n) for n in names]


# ---------------------------------------------------------------------------
# command registration
# ---------------------------------------------------------------------------

def register(tree: app_commands.CommandTree) -> None:

    # ============================================================
    # /spells [class] — list all spell lists, optionally filtered by class
    # ============================================================
    @tree.command(
        name="spells",
        description="List spell lists available to a class (or all classes).",
    )
    @app_commands.describe(
        caster_class="Class to look up (autocomplete). Omit for a list of classes.",
    )
    @app_commands.autocomplete(caster_class=class_autocomplete)
    async def cmd_spells(
        interaction: discord.Interaction,
        caster_class: str | None = None,
    ) -> None:
        conn = connect()
        try:
            if caster_class is None:
                # No class given — show the class roster as a friendly menu.
                classes = list_classes(conn)
                if not classes:
                    await interaction.response.send_message(
                        "*No spell classes loaded yet.*", ephemeral=True,
                    )
                    return
                embed = discord.Embed(
                    title="Caster classes",
                    color=render.COLOR_INFO,
                )
                by_realm: dict[str, list[str]] = {}
                for c in classes:
                    by_realm.setdefault(c["realm_name"], []).append(c["class_name"])
                for realm, names in by_realm.items():
                    embed.add_field(
                        name=realm,
                        value="\n".join(f"• {n}" for n in names),
                        inline=False,
                    )
                embed.set_footer(text="Run /spells with a class name to see its lists.")
                await interaction.response.send_message(embed=embed)
                return

            lists = lists_for_class(conn, caster_class)
            if not lists:
                await interaction.response.send_message(
                    f"Class `{caster_class}` not found, or has no lists loaded.",
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                embed=render.class_lists_embed(caster_class, lists)
            )
        finally:
            conn.close()

    # ============================================================
    # /spell-list <list_name> — full spell list with parameters
    # ============================================================
    @tree.command(
        name="spell-list",
        description="Show all spells on a spell list (level + name + parameters).",
    )
    @app_commands.describe(list_name="Spell list name (autocomplete)")
    @app_commands.autocomplete(list_name=spell_list_autocomplete)
    async def cmd_spell_list(
        interaction: discord.Interaction,
        list_name: str,
    ) -> None:
        conn = connect()
        try:
            meta = get_spell_list(conn, list_name)
            if meta is None:
                await interaction.response.send_message(
                    f"Spell list `{list_name}` not found.", ephemeral=True,
                )
                return
            spells = spells_on_list(conn, meta["list_id"])
            classes = classes_for_list(conn, meta["list_id"])
            await interaction.response.send_message(
                embed=render.spell_list_embed(meta, spells, classes)
            )
        finally:
            conn.close()

    # ============================================================
    # /spell <list_name> <level> — full spell detail with description
    # ============================================================
    @tree.command(
        name="spell",
        description="Show one spell in full (description + parameters).",
    )
    @app_commands.describe(
        list_name="Spell list the spell belongs to (autocomplete)",
        level="Spell's slot on the list (1-50)",
    )
    @app_commands.autocomplete(list_name=spell_list_autocomplete)
    async def cmd_spell(
        interaction: discord.Interaction,
        list_name: str,
        level: app_commands.Range[int, 1, 50],
    ) -> None:
        conn = connect()
        try:
            spell = get_spell(conn, list_name, level)
            if spell is None:
                await interaction.response.send_message(
                    f"No spell at `{list_name}` level `{level}`.",
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                embed=render.spell_detail_embed(spell)
            )
        finally:
            conn.close()

    # ============================================================
    # /spell-search <query> — search by spell name across all lists
    # ============================================================
    @tree.command(
        name="spell-search",
        description="Find spells by name across all lists.",
    )
    @app_commands.describe(
        query="Substring to search for in spell names",
    )
    async def cmd_spell_search(
        interaction: discord.Interaction,
        query: str,
    ) -> None:
        conn = connect()
        try:
            hits = search_spells(conn, query, limit=25)
            await interaction.response.send_message(
                embed=render.spell_search_embed(query, hits)
            )
        finally:
            conn.close()
