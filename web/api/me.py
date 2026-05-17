"""GET /api/v1/me — the round-trip the SPA uses to detect a logged-in session."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..auth.deps import CurrentUser

router = APIRouter(prefix="/api/v1", tags=["me"])


class Me(BaseModel):
    user_id: int
    discord_id: str
    discord_username: str | None = None
    discord_avatar: str | None = None


@router.get("/me", response_model=Me)
def me(user: dict = CurrentUser) -> Me:
    return Me(
        user_id=user["user_id"],
        discord_id=user["discord_id"],
        discord_username=user["discord_username"],
        discord_avatar=user["discord_avatar"],
    )
