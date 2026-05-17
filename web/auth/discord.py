"""Discord OAuth2 authorization-code flow.

Endpoints:
  GET  /auth/discord/login    -> 302 to Discord with a fresh `state` nonce
  GET  /auth/discord/callback -> exchange `code`, upsert app_user, set session,
                                 then 302 back to the SPA.
  POST /auth/logout           -> clear the session cookie.

Scopes: identify (gives us id, username, avatar). We don't request email or
guilds — minimal exposure for the bot-group use case.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from ..config import get_settings
from ..db import connect_rw, upsert_app_user
from ..session import (
    clear_oauth_state,
    clear_session,
    read_oauth_state,
    write_oauth_state,
    write_session,
)

router = APIRouter(prefix="/auth", tags=["auth"])

DISCORD_AUTHORIZE = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN = "https://discord.com/api/oauth2/token"
DISCORD_USER = "https://discord.com/api/users/@me"


@router.get("/discord/login")
def login() -> RedirectResponse:
    settings = get_settings()
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": settings.discord_client_id,
        "redirect_uri": settings.redirect_uri,
        "response_type": "code",
        "scope": "identify",
        "state": state,
        "prompt": "none",  # silent re-auth when already logged in to Discord
    }
    resp = RedirectResponse(url=f"{DISCORD_AUTHORIZE}?{urlencode(params)}")
    write_oauth_state(resp, state)
    return resp


@router.get("/discord/callback")
async def callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
) -> RedirectResponse:
    settings = get_settings()
    expected_state = read_oauth_state(request)
    if not expected_state or not secrets.compare_digest(expected_state, state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            DISCORD_TOKEN,
            data={
                "client_id": settings.discord_client_id,
                "client_secret": settings.discord_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_resp.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=f"Discord token exchange failed: {token_resp.text}",
            )
        access_token = token_resp.json()["access_token"]

        user_resp = await client.get(
            DISCORD_USER,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch Discord user")
        u = user_resp.json()

    with connect_rw() as conn:
        row = upsert_app_user(
            conn,
            discord_id=u["id"],
            discord_username=u.get("username") or u.get("global_name"),
            discord_avatar=u.get("avatar"),
        )

    resp = RedirectResponse(url=settings.client_url)
    write_session(resp, {"user_id": row["user_id"], "discord_id": row["discord_id"]})
    clear_oauth_state(resp)
    return resp


@router.post("/logout")
def logout() -> Response:
    resp = Response(status_code=204)
    clear_session(resp)
    return resp
