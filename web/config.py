"""Web-app settings, loaded from environment (.env auto-loaded by dotenv).

Kept deliberately small: anything we want to override per-deployment lives here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    discord_client_id: str
    discord_client_secret: str
    redirect_uri: str
    client_url: str
    session_secret: str
    insecure_cookies: bool
    client_dist: Path | None  # directory of built SPA assets, or None in dev

    @classmethod
    def from_env(cls) -> "Settings":
        def req(key: str) -> str:
            v = os.environ.get(key, "").strip()
            if not v:
                raise RuntimeError(
                    f"{key} is not set. Copy .env.example to .env and fill it in."
                )
            return v

        client_dist_env = os.environ.get("CLIENT_DIST", "").strip()
        client_dist = Path(client_dist_env) if client_dist_env else None

        return cls(
            discord_client_id=req("DISCORD_CLIENT_ID"),
            discord_client_secret=req("DISCORD_CLIENT_SECRET"),
            redirect_uri=os.environ.get(
                "WEB_REDIRECT_URI",
                "http://localhost:8000/auth/discord/callback",
            ),
            client_url=os.environ.get("WEB_CLIENT_URL", "http://localhost:5173"),
            session_secret=req("WEB_SESSION_SECRET"),
            insecure_cookies=os.environ.get("WEB_INSECURE_COOKIES", "0") == "1",
            client_dist=client_dist,
        )


_cached: Settings | None = None


def get_settings() -> Settings:
    global _cached
    if _cached is None:
        _cached = Settings.from_env()
    return _cached
