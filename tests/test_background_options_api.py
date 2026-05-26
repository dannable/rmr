"""Tests for the background-options endpoints (RMSS T-1.5)."""

from __future__ import annotations


def _create_character(client, name: str = "Test") -> int:
    r = client.post("/api/v1/characters", json={"name": name})
    assert r.status_code == 201
    return r.json()["character_id"]


def _seed_race(slug: str = "test_race", bg_opts: int = 5) -> int:
    """Minimal race insert — only the columns required by max_options."""
    from web.db import connect_rw
    with connect_rw() as conn:
        conn.execute("DELETE FROM race WHERE slug = ?", (slug,))
        # Pad the NOT-NULL stat / RR / prog columns with neutral defaults.
        conn.execute(
            "INSERT INTO race (slug, name, bg_opts, body_dev_prog, "
            "                  chan_pp_prog, ess_pp_prog, ment_pp_prog) "
            "VALUES (?, ?, ?, '', '', '', '')",
            (slug, f"Test {slug}", bg_opts),
        )
        rid = conn.execute(
            "SELECT race_id FROM race WHERE slug = ?", (slug,),
        ).fetchone()[0]
        conn.commit()
    return rid


def test_get_returns_catalog_and_empty_picks_for_new_character(client) -> None:
    cid = _create_character(client)
    r = client.get(f"/api/v1/characters/{cid}/background-options")
    assert r.status_code == 200
    body = r.json()
    assert body["picks"] == []
    assert body["max_options"] == 0          # no race set
    keys = {entry["key"] for entry in body["catalog"]}
    assert "extra_languages" in keys
    assert "extra_money" in keys


def test_get_reports_max_options_from_race(client) -> None:
    _seed_race("bg_test_race", bg_opts=5)
    cid = _create_character(client)
    # Wire the race onto the character.
    r = client.put(f"/api/v1/characters/{cid}/race", json={"slug": "bg_test_race"})
    assert r.status_code == 200
    r = client.get(f"/api/v1/characters/{cid}/background-options")
    assert r.json()["max_options"] == 5


def test_put_persists_picks(client) -> None:
    _seed_race("bg_test_race", bg_opts=5)
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "bg_test_race"})

    picks = [
        {"option_key": "extra_languages",  "detail": "Sindarin"},
        {"option_key": "extra_money",      "detail": ""},
        {"option_key": "extra_weapon_ranks", "detail": "Broadsword"},
    ]
    r = client.put(
        f"/api/v1/characters/{cid}/background-options",
        json={"picks": picks},
    )
    assert r.status_code == 200
    body = r.json()
    assert [p["option_key"] for p in body["picks"]] == [
        "extra_languages", "extra_money", "extra_weapon_ranks",
    ]
    assert body["picks"][0]["detail"] == "Sindarin"
    assert body["max_options"] == 5

    # GET sees the same picks in order.
    r = client.get(f"/api/v1/characters/{cid}/background-options")
    assert [p["option_key"] for p in r.json()["picks"]] == [
        "extra_languages", "extra_money", "extra_weapon_ranks",
    ]


def test_put_rejects_unknown_option_key(client) -> None:
    cid = _create_character(client)
    r = client.put(
        f"/api/v1/characters/{cid}/background-options",
        json={"picks": [{"option_key": "no_such_option_xyz", "detail": ""}]},
    )
    assert r.status_code == 422


def test_put_allows_over_budget_picks(client) -> None:
    """The server stores GM-approved over-budget picks; the SPA warns."""
    _seed_race("bg_small_race", bg_opts=2)
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "bg_small_race"})

    picks = [{"option_key": "extra_money", "detail": ""}] * 4   # 4 picks > 2 max
    r = client.put(
        f"/api/v1/characters/{cid}/background-options",
        json={"picks": picks},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["picks"]) == 4
    assert body["max_options"] == 2


def test_endpoints_require_auth(anon_client) -> None:
    r = anon_client.get("/api/v1/characters/1/background-options")
    assert r.status_code == 401
    r = anon_client.put(
        "/api/v1/characters/1/background-options",
        json={"picks": []},
    )
    assert r.status_code == 401
