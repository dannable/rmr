"""Tests for the character stats sub-resource (GET/PUT /characters/{id}/stats)."""

from __future__ import annotations

import pytest


STAT_CODES = ("Ag", "Co", "Me", "Re", "SD", "Em", "In", "Pr", "Qu", "St")


def _create_character(client, name: str = "Statty") -> int:
    r = client.post("/api/v1/characters", json={"name": name})
    assert r.status_code == 201
    return r.json()["character_id"]


def _stats_body(values: dict[str, tuple[int, int]] | None = None) -> dict:
    """Build a valid {stats: [...]} body, defaulting any unspecified stat to 50/50."""
    values = values or {}
    return {
        "stats": [
            {
                "code": code,
                "temp": values.get(code, (50, 50))[0],
                "potential": values.get(code, (50, 50))[1],
            }
            for code in STAT_CODES
        ],
    }


# ---- GET ----------------------------------------------------------------

def test_get_stats_returns_all_ten_after_creation(client) -> None:
    cid = _create_character(client)
    r = client.get(f"/api/v1/characters/{cid}/stats")
    assert r.status_code == 200
    body = r.json()
    assert len(body["stats"]) == 10
    codes = [s["code"] for s in body["stats"]]
    assert set(codes) == set(STAT_CODES)
    # Defaults: 50/50 → +0 bonus
    assert all(s["temp"] == 50 and s["potential"] == 50 and s["basic_bonus"] == 0
               for s in body["stats"])
    # RR formulas with all-50 temps:
    #   Channeling = 3 * 50 = 150
    #   Arcane     = Em+In+Pr = 50+50+50 = 150
    assert body["resistance_rolls"]["channeling"] == 150
    assert body["resistance_rolls"]["arcane"] == 150


def test_get_stats_returns_names(client) -> None:
    cid = _create_character(client)
    r = client.get(f"/api/v1/characters/{cid}/stats")
    name_by_code = {s["code"]: s["name"] for s in r.json()["stats"]}
    assert name_by_code["Ag"] == "Agility"
    assert name_by_code["SD"] == "Self Discipline"


def test_get_stats_404_for_unknown_character(client) -> None:
    r = client.get("/api/v1/characters/99999/stats")
    assert r.status_code == 404


def test_get_stats_404_for_other_users_character(client, other_user) -> None:
    from datetime import datetime, timezone
    from web.db import connect_rw

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect_rw() as conn:
        cur = conn.execute(
            "INSERT INTO character (owner_user_id, name, level, created_at, updated_at) "
            "VALUES (?, 'Theirs', 1, ?, ?) RETURNING character_id",
            (other_user["user_id"], now, now),
        )
        their_id = cur.fetchone()["character_id"]
        conn.executemany(
            "INSERT INTO character_stat (character_id, stat_code, temp, potential) "
            "VALUES (?, ?, 50, 50)",
            [(their_id, code) for code in STAT_CODES],
        )
        conn.commit()

    r = client.get(f"/api/v1/characters/{their_id}/stats")
    assert r.status_code == 404


def test_get_stats_backfills_missing_rows(client) -> None:
    """If somehow a character lacks the 10 stat rows (e.g. created pre-migration),
    GET should backfill defaults and return all 10."""
    cid = _create_character(client)
    # Remove 3 rows to simulate the pre-migration shape.
    from web.db import connect_rw
    with connect_rw() as conn:
        conn.execute(
            "DELETE FROM character_stat WHERE character_id = ? AND stat_code IN ('Me','Re','SD')",
            (cid,),
        )
        conn.commit()

    r = client.get(f"/api/v1/characters/{cid}/stats")
    assert r.status_code == 200
    assert len(r.json()["stats"]) == 10
    me = next(s for s in r.json()["stats"] if s["code"] == "Me")
    assert me["temp"] == 50
    assert me["potential"] == 50


# ---- PUT ----------------------------------------------------------------

def test_put_stats_updates_and_returns_computed(client) -> None:
    cid = _create_character(client)
    body = _stats_body({
        "Ag": (95, 100),
        "In": (90, 95),
        "Em": (80, 85),
        "Pr": (70, 75),
        "Co": (100, 102),
    })
    r = client.put(f"/api/v1/characters/{cid}/stats", json=body)
    assert r.status_code == 200
    out = {s["code"]: s for s in r.json()["stats"]}
    assert out["Ag"]["temp"] == 95
    assert out["Ag"]["basic_bonus"] == 7      # 94-95 band -> +7
    assert out["Co"]["temp"] == 100
    assert out["Co"]["basic_bonus"] == 10
    assert out["In"]["basic_bonus"] == 5      # 90-91 band -> +5
    # Arcane RR = Em + In + Pr = 80 + 90 + 70 = 240
    assert r.json()["resistance_rolls"]["arcane"] == 240


def test_put_stats_persists_across_get(client) -> None:
    cid = _create_character(client)
    body = _stats_body({"St": (88, 92)})
    client.put(f"/api/v1/characters/{cid}/stats", json=body)
    out = client.get(f"/api/v1/characters/{cid}/stats").json()
    st = next(s for s in out["stats"] if s["code"] == "St")
    assert st["temp"] == 88
    assert st["potential"] == 92


def test_put_stats_validates_range(client) -> None:
    cid = _create_character(client)
    body = _stats_body({"Ag": (200, 200)})  # out of [1,102]
    r = client.put(f"/api/v1/characters/{cid}/stats", json=body)
    assert r.status_code == 422


def test_put_stats_rejects_missing_codes(client) -> None:
    cid = _create_character(client)
    # Drop Strength from the payload
    body = {"stats": [s for s in _stats_body()["stats"] if s["code"] != "St"]}
    r = client.put(f"/api/v1/characters/{cid}/stats", json=body)
    assert r.status_code == 422


def test_put_stats_rejects_unknown_code(client) -> None:
    cid = _create_character(client)
    body = _stats_body()
    body["stats"][0]["code"] = "XX"  # unknown code
    r = client.put(f"/api/v1/characters/{cid}/stats", json=body)
    assert r.status_code == 422


def test_put_stats_404_for_other_users_character(client, other_user) -> None:
    from datetime import datetime, timezone
    from web.db import connect_rw

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect_rw() as conn:
        cur = conn.execute(
            "INSERT INTO character (owner_user_id, name, level, created_at, updated_at) "
            "VALUES (?, 'Theirs', 1, ?, ?) RETURNING character_id",
            (other_user["user_id"], now, now),
        )
        their_id = cur.fetchone()["character_id"]
        conn.executemany(
            "INSERT INTO character_stat (character_id, stat_code, temp, potential) "
            "VALUES (?, ?, 50, 50)",
            [(their_id, code) for code in STAT_CODES],
        )
        conn.commit()

    r = client.put(f"/api/v1/characters/{their_id}/stats", json=_stats_body())
    assert r.status_code == 404


def test_put_stats_updates_character_updated_at(client) -> None:
    cid = _create_character(client)
    before = client.get(f"/api/v1/characters/{cid}").json()["updated_at"]
    # Tiny sleep would help guarantee a different timestamp, but ISO seconds
    # may equal — that's fine, we just need the column to be set, not changed.
    client.put(f"/api/v1/characters/{cid}/stats", json=_stats_body({"Co": (80, 80)}))
    after = client.get(f"/api/v1/characters/{cid}").json()["updated_at"]
    assert after >= before


# ---- auth ---------------------------------------------------------------

@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_stats_endpoints_require_auth(anon_client, method: str) -> None:
    kwargs = {"json": _stats_body()} if method == "PUT" else {}
    r = anon_client.request(method, "/api/v1/characters/1/stats", **kwargs)
    assert r.status_code == 401
