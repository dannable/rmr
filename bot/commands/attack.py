"""/rmr (dice roll) and /attack (static lookup) — scaffold echo bodies.

Real logic gets wired in step 4. Right now each command just echoes its
parameters back as an ephemeral message so we can verify command registration,
parameter parsing, and autocomplete are working.
"""

from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands


# ---------------------------------------------------------------------------
# autocomplete callback (shared by /rmr and /attack)
# ---------------------------------------------------------------------------

async def weapon_autocomplete(interaction: discord.Interaction, current: str
                              ) -> list[app_commands.Choice[str]]:
    """Return up to 25 weapons whose names contain `current` (case-insensitive)."""
    try:
        from core import connect, search_weapons
        with connect() as conn:
            names = search_weapons(conn, current, limit=25)
    except Exception:
        names = []  # DB missing → no suggestions; command still runs
    return [app_commands.Choice(name=n, value=n) for n in names]


# ---------------------------------------------------------------------------
# command registration
# ---------------------------------------------------------------------------

def register(tree: app_commands.CommandTree) -> None:

    @tree.command(
        name="rmr",
        description="Roll a Rolemaster attack: d100 (open-ended) + OB → chart → crit chain.",
    )
    @app_commands.describe(
        weapon="Weapon name (autocomplete)",
        at="Defender's armor type (1-20)",
        ob="Attacker's offensive bonus",
        attack_size="For sweeps-style charts: attacker size category",
        no_open_ended="Disable open-ended d100 (default: enabled)",
    )
    @app_commands.autocomplete(weapon=weapon_autocomplete)
    @app_commands.choices(attack_size=[
        app_commands.Choice(name="Small (degree 1)",  value=1),
        app_commands.Choice(name="Medium (degree 2)", value=2),
        app_commands.Choice(name="Large (degree 3)",  value=3),
        app_commands.Choice(name="Huge (degree 4)",   value=4),
    ])
    async def rmr(
        interaction: discord.Interaction,
        weapon: str,
        at: app_commands.Range[int, 1, 20],
        ob: int,
        attack_size: Optional[app_commands.Choice[int]] = None,
        no_open_ended: bool = False,
    ) -> None:
        size = f", size={attack_size.name}" if attack_size else ""
        oe = " (no open-ended)" if no_open_ended else ""
        await interaction.response.send_message(
            f"[stub] /rmr weapon={weapon!r} AT={at} OB={ob}{size}{oe}",
            ephemeral=True,
        )

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
        cr = f" crit_roll={crit_roll}" if crit_roll is not None else ""
        await interaction.response.send_message(
            f"[stub] /attack weapon={weapon!r} AT={armor_type} roll={attack_roll}{cr}",
            ephemeral=True,
        )
