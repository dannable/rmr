"""FastAPI application entry point.

Run in dev:  python -m web        (binds 127.0.0.1:8000)
Or:          uvicorn web.main:app --reload --port 8000

In production, CLIENT_DIST points at the built SPA bundle and FastAPI serves
both the API and the static assets out of one process. The catch-all route at
the bottom returns index.html for any unmatched path so React Router's
client-side routes resolve cleanly on a hard refresh.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.characters import router as characters_router
from .api.me import router as me_router
from .api.professions import router as professions_router
from .api.races import router as races_router
from .api.skills import router as skills_router
from .api.spells import router as spells_router
from .auth.discord import router as auth_router
from .config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="rmr-web", version="0.1.0")

    # The SPA runs on a different origin in dev (5173) and needs cookies.
    # In prod (same-origin via CLIENT_DIST), this middleware is a no-op.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.client_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router)
    app.include_router(me_router)
    app.include_router(characters_router)
    app.include_router(professions_router)
    app.include_router(races_router)
    app.include_router(skills_router)
    app.include_router(spells_router)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    # ---- SPA static serving (prod only) ----
    dist = settings.client_dist
    if dist and dist.is_dir() and (dist / "index.html").is_file():
        # Mount /assets (Vite's hashed static bundle) directly for cache headers.
        assets_dir = dist / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        index_html = dist / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str, request: Request) -> FileResponse:
            # Never swallow API/auth paths — those should have matched a router.
            if full_path.startswith(("api/", "auth/")):
                raise HTTPException(status_code=404)
            candidate = dist / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index_html)

    return app


app = create_app()
