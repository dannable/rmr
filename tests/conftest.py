"""Shared pytest fixtures.

The env-var assignments here must happen BEFORE any `import core.db` /
`import web.*` because core.db reads DB_PATH at module load. The
test process gets a private SQLite file under tmp; the production DB
is never touched.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# ---- env setup (must run before any web/core imports) -------------------
_TMP_DB = Path(tempfile.gettempdir()) / "rmr-pytest.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["DB_PATH"] = str(_TMP_DB)

# web.config refuses to load without these — they're not exercised by tests
# because we override the auth dependency, but the app still imports config.
os.environ.setdefault("DISCORD_CLIENT_ID", "test-client")
os.environ.setdefault("DISCORD_CLIENT_SECRET", "test-secret")
os.environ.setdefault("WEB_SESSION_SECRET", "test-session-secret-very-long-12345678")

# Ensure the repo root is importable.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


# ---- fixtures -----------------------------------------------------------

import pytest  # noqa: E402  (imports after env setup, on purpose)


@pytest.fixture(scope="session", autouse=True)
def _build_schema() -> None:
    """Build a fresh DB once per test session by running load.py's schema apply."""
    from load import init_db  # noqa: WPS433  (deliberate late import)
    conn = init_db(reset=True)
    conn.close()


@pytest.fixture
def fresh_db() -> None:
    """Wipe character + app_user rows between tests so each test starts clean."""
    from web.db import connect_rw
    with connect_rw() as conn:
        conn.execute("DELETE FROM character")
        conn.execute("DELETE FROM app_user")
        conn.commit()


@pytest.fixture
def fake_user(fresh_db) -> dict:
    """Insert a fake app_user row and return it as the dict the API expects."""
    from web.db import connect_rw, upsert_app_user
    with connect_rw() as conn:
        row = upsert_app_user(
            conn,
            discord_id="999000111",
            discord_username="tester",
            discord_avatar=None,
        )
    return row


@pytest.fixture
def other_user(fresh_db) -> dict:
    """A second user, used to test cross-owner authorization scoping."""
    from web.db import connect_rw, upsert_app_user
    with connect_rw() as conn:
        row = upsert_app_user(
            conn,
            discord_id="888777666",
            discord_username="other",
            discord_avatar=None,
        )
    return row


@pytest.fixture
def client(fake_user):
    """TestClient with the auth dependency overridden to return fake_user."""
    from fastapi.testclient import TestClient
    from web.auth.deps import current_user
    from web.main import app

    app.dependency_overrides[current_user] = lambda: fake_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def anon_client():
    """TestClient with no auth override — should hit 401 on protected routes."""
    from fastapi.testclient import TestClient
    from web.main import app

    # Clear any leftover overrides from prior tests (defensive).
    app.dependency_overrides.clear()
    with TestClient(app) as c:
        yield c
