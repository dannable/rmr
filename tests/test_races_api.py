"""Tests for the race endpoint + race-aware stats response.

The `client` fixture starts with an empty race table (the session schema
build doesn't load reference data). Each test seeds the specific race row
it needs via _seed_race — that keeps test failures readable.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _seed_race(slug: str = "dwarves", **overrides) -> dict:
    """Insert a race row directly via SQL. Returns the inserted row dict."""
    defaults = {
        "name": "Dwarves",
        # Famously magic-resistant: +6 Co, -2 Ag/Qu, etc.
        "stat_ag": -2, "stat_co": 6, "stat_me": 0, "stat_re": 0, "stat_sd": 2,
        "stat_em": -4, "stat_in": 0, "stat_pr": -4, "stat_qu": -2, "stat_st": 2,
        "rr_ess": 40, "rr_chan": 0, "rr_ment": 40, "rr_pois": 20, "rr_dis": 15,
        "bg_opts": 5,
        "body_dev_prog": "0 • 7 • 4 • 2 • 1",
        "chan_pp_prog":  "0 • 8 • 7 • 6 • 5",
        "ess_pp_prog":   "0 • 9 • 8 • 7 • 6",
        "ment_pp_prog":  "0 • 9 • 8 • 7 • 6",
    }
    defaults.update(overrides)
    from web.db import connect_rw
    with connect_rw() as conn:
        conn.execute(
            """INSERT INTO race (slug, name,
                stat_ag, stat_co, stat_me, stat_re, stat_sd,
                stat_em, stat_in, stat_pr, stat_qu, stat_st,
                rr_ess, rr_chan, rr_ment, rr_pois, rr_dis,
                bg_opts, body_dev_prog, chan_pp_prog, ess_pp_prog, ment_pp_prog
            ) VALUES (?, ?,  ?, ?, ?, ?, ?,  ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?,  ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET name = excluded.name""",
            (slug, defaults["name"],
             defaults["stat_ag"], defaults["stat_co"], defaults["stat_me"],
             defaults["stat_re"], defaults["stat_sd"], defaults["stat_em"],
             defaults["stat_in"], defaults["stat_pr"], defaults["stat_qu"],
             defaults["stat_st"],
             defaults["rr_ess"], defaults["rr_chan"], defaults["rr_ment"],
             defaults["rr_pois"], defaults["rr_dis"], defaults["bg_opts"],
             defaults["body_dev_prog"], defaults["chan_pp_prog"],
             defaults["ess_pp_prog"], defaults["ment_pp_prog"]),
        )
        conn.commit()
    return {"slug": slug, **defaults}


def _create_character(client, name: str = "Test") -> int:
    r = client.post("/api/v1/characters", json={"name": name})
    assert r.status_code == 201
    return r.json()["character_id"]


# ---------------------------------------------------------------------------
# GET /api/v1/races
# ---------------------------------------------------------------------------

def test_list_races_returns_seeded(client) -> None:
    _seed_race("dwarves", name="Dwarves")
    _seed_race("high_men", name="High Men",
               stat_ag=-2, stat_co=4, stat_st=4, stat_pr=4,
               rr_ess=-5, rr_chan=-5, rr_ment=-5, rr_pois=0, rr_dis=0)
    r = client.get("/api/v1/races")
    assert r.status_code == 200
    body = r.json()
    slugs = {race["slug"] for race in body}
    assert {"dwarves", "high_men"} <= slugs
    # Each race has the projected RR mod shape.
    dwarves = next(race for race in body if race["slug"] == "dwarves")
    assert dwarves["rr_mods"]["essence"] == 40
    assert dwarves["rr_mods"]["chan_ess"] == 40   # 0 + 40
    assert dwarves["rr_mods"]["arcane"] == 80     # 0 + 40 + 40


def test_list_races_requires_auth(anon_client) -> None:
    r = anon_client.get("/api/v1/races")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# PUT /api/v1/characters/{id}/race
# ---------------------------------------------------------------------------

def test_pick_race_for_character(client) -> None:
    _seed_race("dwarves")
    cid = _create_character(client)

    r = client.put(f"/api/v1/characters/{cid}/race", json={"slug": "dwarves"})
    assert r.status_code == 200
    body = r.json()
    assert body["race_slug"] == "dwarves"
    assert body["race_name"] == "Dwarves"

    # GET should reflect the change too.
    r = client.get(f"/api/v1/characters/{cid}")
    assert r.json()["race_slug"] == "dwarves"


def test_clear_race(client) -> None:
    _seed_race("dwarves")
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "dwarves"})

    r = client.put(f"/api/v1/characters/{cid}/race", json={"slug": None})
    assert r.status_code == 200
    assert r.json()["race_slug"] is None


def test_pick_unknown_race_returns_422(client) -> None:
    cid = _create_character(client)
    r = client.put(f"/api/v1/characters/{cid}/race", json={"slug": "vulcans"})
    assert r.status_code == 422


def test_pick_race_for_other_users_character_404(client, other_user) -> None:
    _seed_race("dwarves")
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
    r = client.put(f"/api/v1/characters/{their_id}/race", json={"slug": "dwarves"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Race-aware stats response
# ---------------------------------------------------------------------------

def test_stats_no_race_has_zero_mods(client) -> None:
    cid = _create_character(client)
    body = client.get(f"/api/v1/characters/{cid}/stats").json()
    assert body["race"] is None
    assert all(s["race_mod"] == 0 for s in body["stats"])
    # Channeling RR = 3 * 50 = 150, unchanged from no-race era.
    assert body["resistance_rolls"]["channeling"] == 150


def test_stats_with_race_applies_mods(client) -> None:
    _seed_race("dwarves")
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "dwarves"})
    body = client.get(f"/api/v1/characters/{cid}/stats").json()

    assert body["race"] == {"slug": "dwarves", "name": "Dwarves"}
    mods = {s["code"]: s["race_mod"] for s in body["stats"]}
    assert mods["Co"] == 6
    assert mods["Ag"] == -2
    # Dwarves with all-50 temps: Co eff=56 → still +0 (band 31-69), but Em eff=46
    # is also in the +0 band, etc. So basic_bonus values are still 0.
    assert all(s["basic_bonus"] == 0 for s in body["stats"])
    # RR: Channeling = 3 * In_eff = 3 * 50 = 150 + rr_chan(0) = 150
    # Essence = 3 * Em_eff = 3 * 46 = 138 + rr_ess(40) = 178
    assert body["resistance_rolls"]["channeling"] == 150
    assert body["resistance_rolls"]["essence"] == 178
    # Arcane = (Em+In+Pr)_eff + (chan+ess+ment) = (46+50+46) + (0+40+40) = 222
    assert body["resistance_rolls"]["arcane"] == 222
    # Poison/Disease: 3 * Co_eff = 3 * 56 = 168 + rr_pois(20) = 188
    assert body["resistance_rolls"]["poison_disease"] == 188


def test_stats_after_clearing_race_is_back_to_baseline(client) -> None:
    _seed_race("dwarves")
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "dwarves"})
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": None})
    body = client.get(f"/api/v1/characters/{cid}/stats").json()
    assert body["race"] is None
    assert all(s["race_mod"] == 0 for s in body["stats"])
    assert body["resistance_rolls"]["channeling"] == 150


# ---------------------------------------------------------------------------
# Auth gating
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/v1/races", None),
    ("PUT", "/api/v1/characters/1/race", {"slug": "dwarves"}),
])
def test_endpoints_require_auth(anon_client, method: str, path: str, body) -> None:
    kwargs = {"json": body} if body is not None else {}
    r = anon_client.request(method, path, **kwargs)
    assert r.status_code == 401, f"{method} {path} expected 401, got {r.status_code}"
