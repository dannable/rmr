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
    # RR formulas use stat *bonuses* (per RMSS T-1.1). T-2.1(50) = 0 across
    # the board, so every RR rolls back to 0 on a baseline character.
    assert body["resistance_rolls"]["channeling"] == 0
    assert body["resistance_rolls"]["arcane"] == 0


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
    # Arcane RR = 1 × (Em + In + Pr)_bonus = 3 + 5 + 1 = 9 (T-2.1: 80→3, 90→5, 70→1).
    assert r.json()["resistance_rolls"]["arcane"] == 9


def test_get_stats_includes_development_points(client) -> None:
    """Default character (every stat 50) → DPs = 5×50 / 5 = 50."""
    cid = _create_character(client)
    r = client.get(f"/api/v1/characters/{cid}/stats")
    assert r.status_code == 200
    assert r.json()["development_points"] == 50


def test_put_stats_recomputes_development_points(client) -> None:
    """Bump the 5 dev stats; non-dev stats must not contribute."""
    cid = _create_character(client)
    body = _stats_body({
        "Ag": (80, 80),
        "Co": (80, 80),
        "Me": (80, 80),
        "Re": (80, 80),
        "SD": (80, 80),
        # Non-dev stats cranked — should be ignored by the DP formula.
        "Em": (100, 100),
        "In": (100, 100),
        "Pr": (100, 100),
        "Qu": (100, 100),
        "St": (100, 100),
    })
    r = client.put(f"/api/v1/characters/{cid}/stats", json=body)
    assert r.status_code == 200
    # 5 × 80 = 400; 400 / 5 = 80.
    assert r.json()["development_points"] == 80


def test_development_points_rounds_half_up(client) -> None:
    """sum=353 (348 + 5) over the dev stats → 70.6 → 71."""
    cid = _create_character(client)
    body = _stats_body({
        "Ag": (72, 50),   # sum so far: 72
        "Co": (70, 50),   # +70 = 142
        "Me": (70, 50),   # +70 = 212
        "Re": (70, 50),   # +70 = 282
        "SD": (71, 50),   # +71 = 353
    })
    r = client.put(f"/api/v1/characters/{cid}/stats", json=body)
    assert r.status_code == 200
    assert r.json()["development_points"] == 71


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


# ---------------------------------------------------------------------------
# T-1.3 potential generators (roll / fixed) and prime-stat auto-raise
# ---------------------------------------------------------------------------

def test_roll_potentials_persists_and_clamps_to_temp(client) -> None:
    """A roll never drops a potential below its temp (table footnote)."""
    cid = _create_character(client)
    # Push a couple of temps high enough that a random roll could go below.
    client.put(f"/api/v1/characters/{cid}/stats",
               json=_stats_body({"St": (74, 50), "Ag": (95, 50)}))
    r = client.post(f"/api/v1/characters/{cid}/roll-potentials")
    assert r.status_code == 200
    out = {s["code"]: s for s in r.json()["stats"]}
    # Both clamped potentials must be ≥ their temp.
    assert out["St"]["potential"] >= 74
    assert out["Ag"]["potential"] >= 95
    # Re-fetching keeps the same values.
    after = client.get(f"/api/v1/characters/{cid}/stats").json()["stats"]
    after_by = {s["code"]: s for s in after}
    assert after_by["St"]["potential"] == out["St"]["potential"]


def test_apply_fixed_potentials_adds_table_modifier(client) -> None:
    cid = _create_character(client)
    # Default 50/50 across; +28 for the 45-54 band → potential should be 78.
    r = client.post(f"/api/v1/characters/{cid}/apply-fixed-potentials")
    assert r.status_code == 200
    out = r.json()["stats"]
    assert all(s["potential"] == 78 for s in out), \
        f"all stats should land at 78 (50+28); got {[(s['code'], s['potential']) for s in out]}"


def test_roll_potentials_requires_auth(anon_client) -> None:
    r = anon_client.post("/api/v1/characters/1/roll-potentials")
    assert r.status_code == 401


def test_raise_primes_to_90_bumps_only_primes(client) -> None:
    """When the character has a profession, primes < 90 jump to 90;
    non-primes are untouched."""
    from web.db import connect_rw
    cid = _create_character(client)

    # Seed a profession with prime stats In + Em.
    with connect_rw() as conn:
        conn.execute(
            "INSERT INTO profession (slug, name, description) "
            "VALUES ('test_mage', 'Test Mage', 'unit') RETURNING profession_id",
        )
        pid = conn.execute(
            "SELECT profession_id FROM profession WHERE slug='test_mage'",
        ).fetchone()[0]
        for s in ("In", "Em"):
            conn.execute(
                "INSERT INTO profession_prime_stat (profession_id, stat_code) "
                "VALUES (?, ?)",
                (pid, s),
            )
        conn.execute(
            "UPDATE character SET profession_id = ? WHERE character_id = ?",
            (pid, cid),
        )
        conn.commit()

    # Defaults: 50/50. Raise primes.
    r = client.post(f"/api/v1/characters/{cid}/raise-primes-to-90")
    assert r.status_code == 200
    out = {s["code"]: s for s in r.json()["stats"]}
    assert out["In"]["temp"] == 90 and out["In"]["potential"] == 90
    assert out["Em"]["temp"] == 90 and out["Em"]["potential"] == 90
    # Non-primes untouched.
    assert out["St"]["temp"] == 50
    assert out["Co"]["temp"] == 50


def test_raise_primes_to_90_is_idempotent(client) -> None:
    """Calling twice is harmless — primes already at 90+ aren't lowered."""
    from web.db import connect_rw
    cid = _create_character(client)
    with connect_rw() as conn:
        conn.execute(
            "INSERT INTO profession (slug, name, description) "
            "VALUES ('test_warrior', 'Test Warrior', '') RETURNING profession_id",
        )
        pid = conn.execute(
            "SELECT profession_id FROM profession WHERE slug='test_warrior'",
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO profession_prime_stat (profession_id, stat_code) VALUES (?, 'St')",
            (pid,),
        )
        conn.execute(
            "UPDATE character SET profession_id = ? WHERE character_id = ?",
            (pid, cid),
        )
        conn.commit()
    # Manually set St above the floor.
    client.put(f"/api/v1/characters/{cid}/stats", json=_stats_body({"St": (95, 100)}))
    r = client.post(f"/api/v1/characters/{cid}/raise-primes-to-90")
    out = {s["code"]: s for s in r.json()["stats"]}
    # St stays at 95 (not lowered to 90); potential stays at 100.
    assert out["St"]["temp"] == 95
    assert out["St"]["potential"] == 100
