"""Tests for the character CRUD endpoints (web/api/characters.py)."""

from __future__ import annotations

import pytest


# ---- create -------------------------------------------------------------

def test_create_character_returns_201_with_payload(client) -> None:
    r = client.post("/api/v1/characters", json={"name": "Varak"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Varak"
    assert body["level"] == 1
    assert body["character_id"] > 0
    assert body["owner_user_id"] > 0
    assert body["created_at"] == body["updated_at"]


def test_create_rejects_empty_name(client) -> None:
    r = client.post("/api/v1/characters", json={"name": ""})
    assert r.status_code == 422


def test_create_rejects_overly_long_name(client) -> None:
    r = client.post("/api/v1/characters", json={"name": "x" * 200})
    assert r.status_code == 422


# ---- list ---------------------------------------------------------------

def test_list_empty_initially(client) -> None:
    r = client.get("/api/v1/characters")
    assert r.status_code == 200
    assert r.json() == []


def test_list_returns_only_my_characters(client, other_user) -> None:
    # Mine
    mine = client.post("/api/v1/characters", json={"name": "Mine A"}).json()
    client.post("/api/v1/characters", json={"name": "Mine B"}).json()

    # Insert one for the other user directly so the test client can't see it.
    from web.db import connect_rw
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect_rw() as conn:
        conn.execute(
            "INSERT INTO character (owner_user_id, name, level, created_at, updated_at) "
            "VALUES (?, 'Theirs', 1, ?, ?)",
            (other_user["user_id"], now, now),
        )
        conn.commit()

    r = client.get("/api/v1/characters")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    names = {c["name"] for c in body}
    assert names == {"Mine A", "Mine B"}
    # Owner scoping holds for the mine record we just made.
    assert all(c["owner_user_id"] == mine["owner_user_id"] for c in body)


# ---- get ----------------------------------------------------------------

def test_get_my_character(client) -> None:
    created = client.post("/api/v1/characters", json={"name": "Gandalf"}).json()
    r = client.get(f"/api/v1/characters/{created['character_id']}")
    assert r.status_code == 200
    assert r.json()["name"] == "Gandalf"


def test_get_unknown_id_returns_404(client) -> None:
    r = client.get("/api/v1/characters/99999")
    assert r.status_code == 404


def test_get_other_users_character_returns_404(client, other_user) -> None:
    # Create one for the other user directly.
    from web.db import connect_rw
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect_rw() as conn:
        cur = conn.execute(
            "INSERT INTO character (owner_user_id, name, level, created_at, updated_at) "
            "VALUES (?, 'Theirs', 1, ?, ?) RETURNING character_id",
            (other_user["user_id"], now, now),
        )
        their_id = cur.fetchone()["character_id"]
        conn.commit()

    # Should look indistinguishable from "doesn't exist" to the wrong owner.
    r = client.get(f"/api/v1/characters/{their_id}")
    assert r.status_code == 404


# ---- delete -------------------------------------------------------------

def test_delete_my_character_returns_204(client) -> None:
    created = client.post("/api/v1/characters", json={"name": "Doomed"}).json()
    cid = created["character_id"]

    r = client.delete(f"/api/v1/characters/{cid}")
    assert r.status_code == 204

    # Gone.
    r = client.get(f"/api/v1/characters/{cid}")
    assert r.status_code == 404


def test_delete_unknown_id_returns_404(client) -> None:
    r = client.delete("/api/v1/characters/99999")
    assert r.status_code == 404


def test_delete_other_users_character_returns_404(client, other_user) -> None:
    from web.db import connect_rw
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect_rw() as conn:
        cur = conn.execute(
            "INSERT INTO character (owner_user_id, name, level, created_at, updated_at) "
            "VALUES (?, 'Survivor', 1, ?, ?) RETURNING character_id",
            (other_user["user_id"], now, now),
        )
        their_id = cur.fetchone()["character_id"]
        conn.commit()

    r = client.delete(f"/api/v1/characters/{their_id}")
    assert r.status_code == 404

    # Confirm their character is still there (a direct DB check; the API
    # would refuse to surface it under the test client's user anyway).
    with connect_rw() as conn:
        row = conn.execute(
            "SELECT character_id FROM character WHERE character_id = ?",
            (their_id,),
        ).fetchone()
    assert row is not None


# ---- auth ---------------------------------------------------------------

@pytest.mark.parametrize("method,path", [
    ("GET", "/api/v1/characters"),
    ("POST", "/api/v1/characters"),
    ("GET", "/api/v1/characters/1"),
    ("DELETE", "/api/v1/characters/1"),
])
def test_endpoints_require_auth(anon_client, method: str, path: str) -> None:
    kwargs = {"json": {"name": "x"}} if method == "POST" else {}
    r = anon_client.request(method, path, **kwargs)
    assert r.status_code == 401, f"{method} {path} should require auth, got {r.status_code}"
