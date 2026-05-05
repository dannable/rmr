"""Bot configuration: token, guild IDs, db path. Reads .env if present."""

from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv is optional — the env vars may already be set by the shell or
    # by docker-compose `env_file`.
    pass


DISCORD_BOT_TOKEN: str = os.environ.get("DISCORD_BOT_TOKEN", "").strip()

# Comma-separated guild IDs (snowflake ints). Empty → global sync (slow).
_raw = os.environ.get("GUILD_IDS", "").strip()
GUILD_IDS: list[int] = [int(x) for x in (s.strip() for s in _raw.split(",")) if x]

# DB_PATH is read by core/db.py via os.environ; we just expose it for logging.
DB_PATH: str = os.environ.get("DB_PATH", "<default>")


def validate() -> None:
    """Raise SystemExit if anything required is missing."""
    if not DISCORD_BOT_TOKEN:
        raise SystemExit(
            "DISCORD_BOT_TOKEN is not set. Copy .env.example to .env and fill it in."
        )
