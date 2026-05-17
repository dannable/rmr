"""Stateless signed-cookie sessions.

Why not a server-side session store: we only carry the app_user.user_id and
a CSRF/OAuth state nonce. A signed cookie is sufficient and lets us scale
horizontally without any shared cache. itsdangerous handles the signing.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .config import get_settings

SESSION_COOKIE = "rmr_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

# Short-lived cookie used to carry the OAuth `state` value between the
# /login redirect and the /callback. Separate from the session cookie so we
# never accidentally invalidate an existing login.
OAUTH_STATE_COOKIE = "rmr_oauth_state"
OAUTH_STATE_MAX_AGE = 60 * 10  # 10 minutes


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret, salt="rmr-session")


def _state_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret, salt="rmr-oauth-state")


def _cookie_kwargs(max_age: int) -> dict[str, Any]:
    s = get_settings()
    return dict(
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=not s.insecure_cookies,
        path="/",
    )


def write_session(resp: Response, payload: dict) -> None:
    token = _serializer().dumps(payload)
    resp.set_cookie(SESSION_COOKIE, token, **_cookie_kwargs(SESSION_MAX_AGE))


def read_session(req: Request) -> dict | None:
    token = req.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        return _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None


def clear_session(resp: Response) -> None:
    resp.delete_cookie(SESSION_COOKIE, path="/")


def write_oauth_state(resp: Response, state: str) -> None:
    token = _state_serializer().dumps({"state": state})
    resp.set_cookie(OAUTH_STATE_COOKIE, token, **_cookie_kwargs(OAUTH_STATE_MAX_AGE))


def read_oauth_state(req: Request) -> str | None:
    token = req.cookies.get(OAUTH_STATE_COOKIE)
    if not token:
        return None
    try:
        data = _state_serializer().loads(token, max_age=OAUTH_STATE_MAX_AGE)
    except BadSignature:
        return None
    return data.get("state")


def clear_oauth_state(resp: Response) -> None:
    resp.delete_cookie(OAUTH_STATE_COOKIE, path="/")
