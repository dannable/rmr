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

def _seed_race(slug: str = "dwarves", culture_data: str = "{}", **overrides) -> dict:
    """Insert a race row directly via SQL. Returns the inserted row dict.

    `culture_data` is a JSON-encoded string of rich-text fields (as
    persisted by load.py from data/chargen/cultures/<slug>.txt). Empty
    "{}" is the default — matches the post-migration state of races
    that don't have a culture entry.
    """
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
                bg_opts, body_dev_prog, chan_pp_prog, ess_pp_prog, ment_pp_prog,
                culture_data
            ) VALUES (?, ?,  ?, ?, ?, ?, ?,  ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?,  ?, ?, ?, ?, ?,  ?)
            ON CONFLICT(slug) DO UPDATE SET
                name = excluded.name,
                culture_data = excluded.culture_data""",
            (slug, defaults["name"],
             defaults["stat_ag"], defaults["stat_co"], defaults["stat_me"],
             defaults["stat_re"], defaults["stat_sd"], defaults["stat_em"],
             defaults["stat_in"], defaults["stat_pr"], defaults["stat_qu"],
             defaults["stat_st"],
             defaults["rr_ess"], defaults["rr_chan"], defaults["rr_ment"],
             defaults["rr_pois"], defaults["rr_dis"], defaults["bg_opts"],
             defaults["body_dev_prog"], defaults["chan_pp_prog"],
             defaults["ess_pp_prog"], defaults["ment_pp_prog"],
             culture_data),
        )
        conn.commit()
    return {"slug": slug, "culture_data": culture_data, **defaults}


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
    # race_rr_mods should be all zeros for an unraced character.
    assert all(v == 0 for v in body["race_rr_mods"].values())


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
    # RR totals: Channeling = 3 * In_eff = 3 * 50 = 150 + rr_chan(0) = 150
    # Essence = 3 * Em_eff = 3 * 46 = 138 + rr_ess(40) = 178
    assert body["resistance_rolls"]["channeling"] == 150
    assert body["resistance_rolls"]["essence"] == 178
    # Arcane = (Em+In+Pr)_eff + (chan+ess+ment) = (46+50+46) + (0+40+40) = 222
    assert body["resistance_rolls"]["arcane"] == 222
    # Poison/Disease: 3 * Co_eff = 3 * 56 = 168 + rr_pois(20) = 188
    assert body["resistance_rolls"]["poison_disease"] == 188

    # race_rr_mods exposes ONLY the race contribution, parallel-shaped to
    # resistance_rolls so the SPA can render Base / Race / Total columns.
    # Dwarves: rr_chan=0, rr_ess=40, rr_ment=40, rr_pois=20, rr_dis=15.
    rr_race = body["race_rr_mods"]
    assert rr_race["channeling"] == 0
    assert rr_race["essence"] == 40
    assert rr_race["mentalism"] == 40
    # Hybrids stack: chan_ess sums chan + ess race mods.
    assert rr_race["chan_ess"] == 40       # 0 + 40
    assert rr_race["chan_ment"] == 40      # 0 + 40
    assert rr_race["ess_ment"] == 80       # 40 + 40
    assert rr_race["arcane"] == 80         # 0 + 40 + 40
    # Poison/Disease uses rr_pois only (RR formula collapses to one row).
    assert rr_race["poison_disease"] == 20
    assert rr_race["fear"] == 0
    # Sanity: total - race = base = the formula component
    # Channeling base = 150 - 0 = 150 = 3 * In_eff = 3 * 50 = 150 ✓
    # Essence base = 178 - 40 = 138 = 3 * Em_eff = 3 * 46 = 138 ✓
    assert body["resistance_rolls"]["essence"] - rr_race["essence"] == 138
    assert body["resistance_rolls"]["arcane"] - rr_race["arcane"] == 142


def test_stats_high_temp_with_race_changes_basic_bonus(client) -> None:
    """Race mod most visibly affects basic_bonus when temp is near a T-2.1
    band edge. Halfling +6 Co pushes Co=95 into the 101 band."""
    _seed_race("halflings", name="Halflings",
               stat_ag=6, stat_co=6, stat_me=0, stat_re=0, stat_sd=-4,
               stat_em=-2, stat_in=0, stat_pr=-6, stat_qu=4, stat_st=-8,
               rr_ess=50, rr_chan=0, rr_ment=40, rr_pois=30, rr_dis=15)
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "halflings"})
    # Set Co temp to 95.
    full_stats = client.get(f"/api/v1/characters/{cid}/stats").json()["stats"]
    body_stats = [
        {"code": s["code"],
         "temp": 95 if s["code"] == "Co" else s["temp"],
         "potential": s["potential"]}
        for s in full_stats
    ]
    client.put(f"/api/v1/characters/{cid}/stats", json={"stats": body_stats})

    body = client.get(f"/api/v1/characters/{cid}/stats").json()
    co = next(s for s in body["stats"] if s["code"] == "Co")
    assert co["temp"] == 95
    assert co["race_mod"] == 6                     # Halfling Co mod
    # Co eff = 95 + 6 = 101, T-2.1 band 101 = +12
    assert co["basic_bonus"] == 12


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


# ---------------------------------------------------------------------------
# culture_data round-trip
# ---------------------------------------------------------------------------

def test_race_response_includes_culture_data(client) -> None:
    """A race seeded with a non-empty culture_data JSON returns the parsed
    object on /api/v1/races, with each key/value preserved."""
    import json
    culture = {
        "build": "Short, stocky, strong.",
        "weapons": "Dagger, handaxe, short sword.",
        "religion": "Most Dwarves revere a single deity.",
    }
    _seed_race("dwarves", culture_data=json.dumps(culture))
    r = client.get("/api/v1/races")
    assert r.status_code == 200
    dwarves = next(race for race in r.json() if race["slug"] == "dwarves")
    assert dwarves["culture_data"] == culture


def test_race_response_empty_culture_data_when_unseeded(client) -> None:
    """A race seeded with the default empty culture_data shows {} on the
    API (matches the schema column default for races without a PDF entry)."""
    _seed_race("common_men", name="Common Men")
    r = client.get("/api/v1/races")
    assert r.status_code == 200
    cm = next(race for race in r.json() if race["slug"] == "common_men")
    assert cm["culture_data"] == {}


def test_race_response_handles_malformed_culture_data(client) -> None:
    """If culture_data isn't valid JSON (corruption / older row), the API
    falls back to {} rather than 500-ing."""
    _seed_race("urbanmen", name="Urbanmen", culture_data="this isn't json")
    r = client.get("/api/v1/races")
    assert r.status_code == 200
    um = next(race for race in r.json() if race["slug"] == "urbanmen")
    assert um["culture_data"] == {}
