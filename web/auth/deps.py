"""FastAPI dependencies for auth-required routes."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from ..db import connect_rw, get_app_user
from ..session import read_session


def current_user(request: Request) -> dict:
    """Resolve the current app_user from the session cookie or raise 401."""
    sess = read_session(request)
    if not sess or "user_id" not in sess:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    with connect_rw() as conn:
        user = get_app_user(conn, sess["user_id"])
    if not user:
        # Session pointed at a deleted user — treat as logged out.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


CurrentUser = Depends(current_user)
