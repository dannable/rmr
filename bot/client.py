"""Discord client subclass. Owns the CommandTree and the sync logic."""

from __future__ import annotations

import logging

import discord
from discord import app_commands

from . import config

log = logging.getLogger(__name__)


class RMRClient(discord.Client):
    def __init__(self) -> None:
        # Default intents only — slash commands don't need MESSAGE_CONTENT.
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        # Import command modules and register their commands on the tree.
        from .commands import attack, crit, fumble, info
        attack.register(self.tree)
        crit.register(self.tree)
        fumble.register(self.tree)
        info.register(self.tree)

        if config.GUILD_IDS:
            for gid in config.GUILD_IDS:
                guild = discord.Object(id=gid)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                log.info("Synced %d commands to guild %d", len(synced), gid)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d commands globally (~1h propagation)", len(synced))

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id=%s)", self.user, self.user.id if self.user else "?")
        log.info("Watching %d guild(s)", len(self.guilds))


def run() -> None:
    config.validate()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log.info("rmr-bot starting (DB_PATH=%s, guilds=%s)",
             config.DB_PATH,
             config.GUILD_IDS or "global sync")
    client = RMRClient()
    client.run(config.DISCORD_BOT_TOKEN, log_handler=None)
