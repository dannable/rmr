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


# ---------------------------------------------------------------------------
# Umbrella race + culture sub-pick (Common Men / Mixed Men)
# ---------------------------------------------------------------------------

def test_pick_umbrella_race_exposes_flag(client) -> None:
    """Picking Common Men should flip race_is_umbrella=True so the SPA
    knows to show the Culture sub-picker."""
    _seed_race("common_men", name="Common Men")
    cid = _create_character(client)

    r = client.put(f"/api/v1/characters/{cid}/race", json={"slug": "common_men"})
    assert r.status_code == 200
    body = r.json()
    assert body["race_slug"] == "common_men"
    assert body["race_is_umbrella"] is True
    assert body["culture_slug"] is None
    assert body["culture_name"] is None


def test_pick_concrete_race_has_umbrella_false(client) -> None:
    _seed_race("dwarves")
    cid = _create_character(client)
    r = client.put(f"/api/v1/characters/{cid}/race", json={"slug": "dwarves"})
    body = r.json()
    assert body["race_is_umbrella"] is False


def test_culture_pick_under_umbrella_race(client) -> None:
    """Common Men + Hillmen culture saves and surfaces on subsequent GETs."""
    _seed_race("common_men", name="Common Men")
    _seed_race("hillmen", name="Hillmen")
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "common_men"})

    r = client.put(f"/api/v1/characters/{cid}/culture", json={"slug": "hillmen"})
    assert r.status_code == 200
    body = r.json()
    assert body["culture_slug"] == "hillmen"
    assert body["culture_name"] == "Hillmen"
    # Race stays umbrella; culture sits beside it.
    assert body["race_slug"] == "common_men"
    assert body["race_is_umbrella"] is True

    # GET should reflect the change too.
    r = client.get(f"/api/v1/characters/{cid}")
    assert r.json()["culture_slug"] == "hillmen"


def test_clear_culture(client) -> None:
    _seed_race("common_men", name="Common Men")
    _seed_race("hillmen", name="Hillmen")
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "common_men"})
    client.put(f"/api/v1/characters/{cid}/culture", json={"slug": "hillmen"})

    r = client.put(f"/api/v1/characters/{cid}/culture", json={"slug": None})
    assert r.status_code == 200
    assert r.json()["culture_slug"] is None


def test_culture_pick_requires_umbrella_race(client) -> None:
    """Picking a culture under a concrete race (Dwarves) is a 409 — culture
    is only meaningful as a sub-pick beneath an umbrella race."""
    _seed_race("dwarves")
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "dwarves"})

    r = client.put(f"/api/v1/characters/{cid}/culture", json={"slug": "hillmen"})
    assert r.status_code == 409


def test_culture_pick_rejects_non_men_slug(client) -> None:
    """Common Men + 'dwarves' as a culture is 422 — Dwarves is a race,
    not a Men culture, so the umbrella whitelist filters it out."""
    _seed_race("common_men", name="Common Men")
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "common_men"})

    r = client.put(f"/api/v1/characters/{cid}/culture", json={"slug": "dwarves"})
    assert r.status_code == 422


def test_switching_to_concrete_race_clears_culture(client) -> None:
    """Common Men → pick Hillmen culture → switch to Dwarves should drop
    the culture pick (a Dwarven character can't keep an old Men culture)."""
    _seed_race("common_men", name="Common Men")
    _seed_race("hillmen", name="Hillmen")
    _seed_race("dwarves")
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "common_men"})
    client.put(f"/api/v1/characters/{cid}/culture", json={"slug": "hillmen"})

    r = client.put(f"/api/v1/characters/{cid}/race", json={"slug": "dwarves"})
    body = r.json()
    assert body["race_slug"] == "dwarves"
    assert body["culture_slug"] is None


def test_switching_between_umbrella_races_keeps_culture(client) -> None:
    """Common Men → Hillmen → Mixed Men: culture stays Hillmen because
    both umbrella races admit the same 7 sub-cultures."""
    _seed_race("common_men", name="Common Men")
    _seed_race("mixed_men", name="Mixed Men")
    _seed_race("hillmen", name="Hillmen")
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "common_men"})
    client.put(f"/api/v1/characters/{cid}/culture", json={"slug": "hillmen"})

    r = client.put(f"/api/v1/characters/{cid}/race", json={"slug": "mixed_men"})
    body = r.json()
    assert body["race_slug"] == "mixed_men"
    assert body["culture_slug"] == "hillmen"


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
    # Default temps are 50; T-2.1(50) = 0. So total_bonus = 0 for every stat
    # and every RR formula evaluates to 0.
    assert all(s["total_bonus"] == 0 for s in body["stats"])
    assert body["resistance_rolls"]["channeling"] == 0
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
    # All temps default to 50 ⇒ T-2.1(50) = 0 ⇒ basic_bonus = 0 across the
    # board, regardless of race. Race mods land on total_bonus instead.
    assert all(s["basic_bonus"] == 0 for s in body["stats"])
    totals = {s["code"]: s["total_bonus"] for s in body["stats"]}
    assert totals["Co"] == 6   # 0 + 6
    assert totals["Em"] == -4  # 0 + (-4)
    assert totals["In"] == 0
    assert totals["Pr"] == -4

    # RR totals: 3 × stat_bonus + race_RR_mod.
    rr = body["resistance_rolls"]
    # Channeling = 3 × In_bonus + rr_chan = 3×0 + 0 = 0
    assert rr["channeling"] == 0
    # Essence = 3 × Em_bonus + rr_ess = 3×(-4) + 40 = 28
    assert rr["essence"] == 28
    # Mentalism = 3 × Pr_bonus + rr_ment = 3×(-4) + 40 = 28
    assert rr["mentalism"] == 28
    # Arcane = 1 × (Em+In+Pr)_bonus + (chan+ess+ment) = (-4 + 0 + -4) + (0+40+40) = 72
    assert rr["arcane"] == 72
    # Poison/Disease = 3 × Co_bonus + rr_pois = 18 + 20 = 38
    assert rr["poison_disease"] == 38

    # race_rr_mods exposes ONLY the race contribution, parallel-shaped to
    # resistance_rolls so the SPA can render Base / Race / Total columns.
    # Dwarves: rr_chan=0, rr_ess=40, rr_ment=40, rr_pois=20, rr_dis=15.
    rr_race = body["race_rr_mods"]
    assert rr_race["channeling"] == 0
    assert rr_race["essence"] == 40
    assert rr_race["mentalism"] == 40
    assert rr_race["chan_ess"] == 40       # 0 + 40
    assert rr_race["chan_ment"] == 40      # 0 + 40
    assert rr_race["ess_ment"] == 80       # 40 + 40
    assert rr_race["arcane"] == 80         # 0 + 40 + 40
    assert rr_race["poison_disease"] == 20
    assert rr_race["fear"] == 0


def test_stats_high_temp_with_race_changes_total_bonus(client) -> None:
    """At a stat value of 95, the T-2.1 bonus is +8. A Halfling +6 Co
    race mod adds directly to the bonus per RMSS T-1.1, producing a
    total Co bonus of 14."""
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
    assert co["race_mod"] == 6
    # T-2.1(95) sits in the 94-95 band = +7. Race mod adds to the bonus,
    # not the stat, so total_bonus = 7 + 6 = 13.
    assert co["basic_bonus"] == 7
    assert co["total_bonus"] == 13


def test_stats_after_clearing_race_is_back_to_baseline(client) -> None:
    _seed_race("dwarves")
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "dwarves"})
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": None})
    body = client.get(f"/api/v1/characters/{cid}/stats").json()
    assert body["race"] is None
    assert all(s["race_mod"] == 0 for s in body["stats"])
    # All temps still 50, no race mods → all RRs back to 0.
    assert body["resistance_rolls"]["channeling"] == 0


# ---------------------------------------------------------------------------
# Auth gating
# ---------------------------------------------------------------------------

def _seed_adolescence_rows() -> None:
    """Seed a minimal adolescence_rank fixture for Dwarves.

    Mirrors the real source-data shape: each leaf skill is preceded by
    its "skill category" header, so grouped_ranks() puts each leaf in
    its proper group. Specifier-required rows (Riding free-text, two
    weapon dropdowns) sit under their own categories the way they do
    in the real table.
    """
    from web.db import connect_rw
    rows = [
        ("Armor • Light skill category",   "dwarves", "0"),
        ("Soft Leather skill",             "dwarves", "0"),
        ("Rigid Leather skill",            "dwarves", "1"),
        ("Athletic • Brawn skill category","dwarves", "1"),
        ("Climbing skill",                 "dwarves", "5"),
        # Riding falls under "Outdoor • Animal" in the real T-1.6.
        ("Outdoor • Animal skill category", "dwarves", "0"),
        ("Riding skill (usually horses)",  "dwarves", "1"),
        # Each "1 Weapon Based on Culture/Race ‡" leaf is preceded by
        # its weapon-category header in the real source data.
        ("Weapon • 1-H Edged skill category", "dwarves", "0"),
        ("[Weapon • 1-H Edged skill category] 1 Weapon Based on Culture/Race ‡", "dwarves", "2"),
        ("Weapon • 1-H Conc. skill category", "dwarves", "0"),
        ("[Weapon • 1-H Conc. skill category] 1 Weapon Based on Culture/Race ‡", "dwarves", "1"),
        # Summary row — must be classified as kind="summary" so the apply
        # path skips it (otherwise it leaks into character_skill).
        ("Hobby Ranks (see Section 13.0) ‡", "dwarves", "12"),
    ]
    with connect_rw() as conn:
        conn.execute("DELETE FROM adolescence_rank WHERE culture_slug = 'dwarves'")
        for skill, slug, val in rows:
            conn.execute(
                "INSERT INTO adolescence_rank (skill, culture_slug, value) VALUES (?, ?, ?)",
                (skill, slug, val),
            )
        conn.commit()


# Dwarven culture_data with a small weapons list spanning two categories,
# used for verifying the dropdown filter on the adolescence GET response.
DWARVEN_CULTURE_DATA = (
    '{"weapons": "Dagger, handaxe, short sword, club, war hammer, mace"}'
)


# ---------------------------------------------------------------------------
# GET /api/v1/characters/{id}/adolescence-ranks
# ---------------------------------------------------------------------------

def test_adolescence_empty_when_no_race(client) -> None:
    cid = _create_character(client)
    r = client.get(f"/api/v1/characters/{cid}/adolescence-ranks")
    assert r.status_code == 200
    body = r.json()
    assert body == {"culture_slug": None, "culture_name": None, "groups": []}


def test_adolescence_umbrella_race_without_culture_returns_empty_groups(client) -> None:
    """Common Men with no culture picked: response carries the umbrella
    race header (culture_slug == race.slug) but groups is empty so the
    SPA shows "pick a culture in Step 2" rather than rendering an empty
    table."""
    _seed_race("common_men", name="Common Men")  # no T-1.6 rows for umbrella
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "common_men"})

    r = client.get(f"/api/v1/characters/{cid}/adolescence-ranks")
    assert r.status_code == 200
    body = r.json()
    assert body["culture_slug"] == "common_men"
    assert body["culture_name"] == "Common Men"
    assert body["groups"] == []


def test_adolescence_umbrella_race_with_culture_returns_culture_ranks(client) -> None:
    """Common Men + picked culture: the API resolves T-1.6 data via the
    culture slug, not the umbrella race. culture_slug/_name in the
    response reflect the SUB-culture (Dwarves here, reused as a stand-in
    for any specific culture row that has T-1.6 data)."""
    _seed_race("common_men", name="Common Men")
    _seed_race("dwarves")  # has T-1.6 data via _seed_adolescence_rows
    _seed_adolescence_rows()
    # We need "dwarves" in UMBRELLA_CULTURE_SLUGS to validate this — but
    # it isn't (only the 7 Men cultures are). So we use Hillmen for the
    # full end-to-end and seed dwarves-shape rows under hillmen's slug.
    _seed_race("hillmen", name="Hillmen")
    from web.db import connect_rw
    with connect_rw() as conn:
        # Copy the dwarves T-1.6 rows under hillmen so we have data the
        # API can return.
        rows = conn.execute(
            "SELECT skill, value FROM adolescence_rank WHERE culture_slug = 'dwarves'"
        ).fetchall()
        for r in rows:
            conn.execute(
                "INSERT OR REPLACE INTO adolescence_rank (skill, culture_slug, value) "
                "VALUES (?, 'hillmen', ?)",
                (r["skill"], r["value"]),
            )
        conn.commit()

    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "common_men"})
    client.put(f"/api/v1/characters/{cid}/culture", json={"slug": "hillmen"})

    r = client.get(f"/api/v1/characters/{cid}/adolescence-ranks")
    assert r.status_code == 200
    body = r.json()
    # culture_slug in the response is the resolved sub-culture, NOT the
    # umbrella race — that's what powers the SPA's "as a Hillmen" label.
    assert body["culture_slug"] == "hillmen"
    assert body["culture_name"] == "Hillmen"
    # Non-empty groups now that the culture has T-1.6 data.
    assert len(body["groups"]) > 0


def test_apply_adolescence_under_umbrella_requires_culture(client) -> None:
    """Trying to apply adolescence ranks when race is umbrella but no
    culture is picked yet should 409, not silently no-op."""
    _seed_race("common_men", name="Common Men")
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "common_men"})

    r = client.post(f"/api/v1/characters/{cid}/apply-adolescence")
    assert r.status_code == 409
    assert "culture" in r.json()["detail"].lower()


def test_adolescence_returns_grouped_ranks_for_race(client) -> None:
    _seed_race("dwarves")
    _seed_adolescence_rows()
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "dwarves"})

    r = client.get(f"/api/v1/characters/{cid}/adolescence-ranks")
    assert r.status_code == 200
    body = r.json()
    assert body["culture_slug"] == "dwarves"
    assert body["culture_name"] == "Dwarves"

    # Six groups — one per "skill category" header in the fixture, plus
    # the synthetic "Summary" bucket for the Hobby Ranks row.
    cats = [g["category"] for g in body["groups"]]
    assert cats == [
        "Armor • Light skill category",
        "Athletic • Brawn skill category",
        "Outdoor • Animal skill category",
        "Weapon • 1-H Edged skill category",
        "Weapon • 1-H Conc. skill category",
        "Summary",
    ]

    # Compare leaves as (name, value) pairs — the AdolescenceSkill model
    # adds choice_* fields that we don't want to spell out here, since
    # they're tested separately in test_adolescence_rows_carry_choice_metadata.
    def names_values(group: dict) -> list[tuple[str, str]]:
        return [(s["name"], s["value"]) for s in group["skills"]]

    armor = body["groups"][0]
    assert armor["value"] == "0"
    assert names_values(armor) == [
        ("Soft Leather skill", "0"),
        ("Rigid Leather skill", "1"),
    ]

    athletic = body["groups"][1]
    assert athletic["value"] == "1"
    assert names_values(athletic) == [("Climbing skill", "5")]

    outdoor = body["groups"][2]
    assert names_values(outdoor) == [("Riding skill (usually horses)", "1")]

    edged = body["groups"][3]
    assert names_values(edged) == [
        ("[Weapon • 1-H Edged skill category] 1 Weapon Based on Culture/Race ‡", "2"),
    ]

    summary = body["groups"][5]
    assert summary["category"] == "Summary"
    assert names_values(summary) == [
        ("Hobby Ranks (see Section 13.0) ‡", "12"),
    ]


def test_adolescence_404_for_other_users_character(client, other_user) -> None:
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
    r = client.get(f"/api/v1/characters/{their_id}/adolescence-ranks")
    assert r.status_code == 404


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/v1/races", None),
    ("PUT", "/api/v1/characters/1/race", {"slug": "dwarves"}),
    ("GET", "/api/v1/characters/1/adolescence-ranks", None),
    ("PUT", "/api/v1/characters/1/adolescence-choices", {"choices": []}),
    ("POST", "/api/v1/characters/1/apply-adolescence", None),
])
def test_endpoints_require_auth(anon_client, method: str, path: str, body) -> None:
    kwargs = {"json": body} if body is not None else {}
    r = anon_client.request(method, path, **kwargs)
    assert r.status_code == 401, f"{method} {path} expected 401, got {r.status_code}"


# ---------------------------------------------------------------------------
# adolescence choices + apply
# ---------------------------------------------------------------------------

def test_adolescence_rows_carry_choice_metadata(client) -> None:
    """The GET response identifies which rows need user input + provides
    dropdown options filtered by RMSS weapon category."""
    _seed_race("dwarves", culture_data=DWARVEN_CULTURE_DATA)
    _seed_adolescence_rows()
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "dwarves"})

    body = client.get(f"/api/v1/characters/{cid}/adolescence-ranks").json()
    # Flatten every leaf skill for easier assertions.
    all_skills = {s["name"]: s for g in body["groups"] for s in g["skills"]}

    # Plain leaf — no choice needed.
    climbing = all_skills["Climbing skill"]
    assert climbing["choice_kind"] is None
    assert climbing["choice_options"] is None

    # Riding row — free-text input.
    riding = all_skills["Riding skill (usually horses)"]
    assert riding["choice_kind"] == "text"
    assert riding["choice_options"] is None
    assert riding["choice"] is None

    # Weapon rows — dropdowns filtered to the race's matching weapons.
    edged = all_skills[
        "[Weapon • 1-H Edged skill category] 1 Weapon Based on Culture/Race ‡"
    ]
    assert edged["choice_kind"] == "select"
    assert set(edged["choice_options"]) == {"Dagger", "handaxe", "short sword"}
    conc = all_skills[
        "[Weapon • 1-H Conc. skill category] 1 Weapon Based on Culture/Race ‡"
    ]
    assert conc["choice_kind"] == "select"
    assert set(conc["choice_options"]) == {"club", "war hammer", "mace"}


def test_save_and_clear_adolescence_choices(client) -> None:
    _seed_race("dwarves", culture_data=DWARVEN_CULTURE_DATA)
    _seed_adolescence_rows()
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "dwarves"})

    # Save Riding + 1-H Edged picks.
    r = client.put(
        f"/api/v1/characters/{cid}/adolescence-choices",
        json={"choices": [
            {"t16_row": "Riding skill (usually horses)", "choice": "war boars"},
            {"t16_row":
                "[Weapon • 1-H Edged skill category] 1 Weapon Based on Culture/Race ‡",
             "choice": "short sword"},
        ]},
    )
    assert r.status_code == 200
    by_name = {s["name"]: s for g in r.json()["groups"] for s in g["skills"]}
    assert by_name["Riding skill (usually horses)"]["choice"] == "war boars"
    assert by_name[
        "[Weapon • 1-H Edged skill category] 1 Weapon Based on Culture/Race ‡"
    ]["choice"] == "short sword"

    # Clear by sending an empty string.
    r = client.put(
        f"/api/v1/characters/{cid}/adolescence-choices",
        json={"choices": [
            {"t16_row": "Riding skill (usually horses)", "choice": ""},
        ]},
    )
    by_name = {s["name"]: s for g in r.json()["groups"] for s in g["skills"]}
    assert by_name["Riding skill (usually horses)"]["choice"] is None


def test_apply_adolescence_writes_character_skill_rows(client) -> None:
    _seed_race("dwarves", culture_data=DWARVEN_CULTURE_DATA)
    _seed_adolescence_rows()
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "dwarves"})
    # Save both specifier picks.
    client.put(
        f"/api/v1/characters/{cid}/adolescence-choices",
        json={"choices": [
            {"t16_row": "Riding skill (usually horses)", "choice": "horses"},
            {"t16_row":
                "[Weapon • 1-H Edged skill category] 1 Weapon Based on Culture/Race ‡",
             "choice": "short sword"},
            {"t16_row":
                "[Weapon • 1-H Conc. skill category] 1 Weapon Based on Culture/Race ‡",
             "choice": "mace"},
        ]},
    )

    r = client.post(f"/api/v1/characters/{cid}/apply-adolescence")
    assert r.status_code == 200
    result = r.json()
    # Applied: 5 leaf-skill rows + 1 category row (Athletic • Brawn = 1).
    # The other category-rank rows in the fixture are 0 → skipped.
    # Hobby Ranks is a summary row → also skipped.
    assert result["applied"] == 6
    assert result["skipped_pending"] == []

    # Verify the actual character_skill rows — both skill and category kinds.
    from web.db import connect_rw
    with connect_rw() as conn:
        rows = conn.execute(
            "SELECT skill, kind, rank, source FROM character_skill "
            "WHERE character_id = ?",
            (cid,),
        ).fetchall()
    skills = {(r["skill"], r["kind"]): (r["rank"], r["source"]) for r in rows}
    assert skills[("Rigid Leather",            "skill")]    == (1, "adolescence")
    assert skills[("Climbing",                 "skill")]    == (5, "adolescence")
    assert skills[("Riding (horses)",          "skill")]    == (1, "adolescence")
    assert skills[("1-H Edged: short sword",   "skill")]    == (2, "adolescence")
    assert skills[("1-H Conc.: mace",          "skill")]    == (1, "adolescence")
    # NEW: category-level rank from adolescence applies too.
    assert skills[("Athletic • Brawn",         "category")] == (1, "adolescence")


def test_apply_skips_pending_picks(client) -> None:
    _seed_race("dwarves", culture_data=DWARVEN_CULTURE_DATA)
    _seed_adolescence_rows()
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "dwarves"})
    # Pick Riding but leave both weapon rows blank.
    client.put(
        f"/api/v1/characters/{cid}/adolescence-choices",
        json={"choices": [
            {"t16_row": "Riding skill (usually horses)", "choice": "horses"},
        ]},
    )
    r = client.post(f"/api/v1/characters/{cid}/apply-adolescence")
    result = r.json()
    # Applied: 3 leaf skills (Rigid Leather, Climbing, Riding) + 1 category
    # (Athletic • Brawn). Both weapons → skipped (no specifier picked).
    assert result["applied"] == 4
    assert set(result["skipped_pending"]) == {
        "[Weapon • 1-H Edged skill category] 1 Weapon Based on Culture/Race ‡",
        "[Weapon • 1-H Conc. skill category] 1 Weapon Based on Culture/Race ‡",
    }


def test_apply_is_idempotent(client) -> None:
    """Re-applying replaces adolescence-sourced rows; doesn't double them up."""
    _seed_race("dwarves", culture_data=DWARVEN_CULTURE_DATA)
    _seed_adolescence_rows()
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/race", json={"slug": "dwarves"})
    client.put(
        f"/api/v1/characters/{cid}/adolescence-choices",
        json={"choices": [
            {"t16_row": "Riding skill (usually horses)", "choice": "horses"},
            {"t16_row":
                "[Weapon • 1-H Edged skill category] 1 Weapon Based on Culture/Race ‡",
             "choice": "short sword"},
            {"t16_row":
                "[Weapon • 1-H Conc. skill category] 1 Weapon Based on Culture/Race ‡",
             "choice": "mace"},
        ]},
    )
    # First apply
    client.post(f"/api/v1/characters/{cid}/apply-adolescence")
    # Change weapon pick and re-apply
    client.put(
        f"/api/v1/characters/{cid}/adolescence-choices",
        json={"choices": [
            {"t16_row":
                "[Weapon • 1-H Edged skill category] 1 Weapon Based on Culture/Race ‡",
             "choice": "Dagger"},
        ]},
    )
    client.post(f"/api/v1/characters/{cid}/apply-adolescence")
    from web.db import connect_rw
    with connect_rw() as conn:
        skills = {
            r["skill"]: r["rank"]
            for r in conn.execute(
                "SELECT skill, rank FROM character_skill WHERE character_id = ?",
                (cid,),
            ).fetchall()
        }
    # Old "1-H Edged: short sword" should be GONE; new "1-H Edged: Dagger" present.
    assert "1-H Edged: short sword" not in skills
    assert skills["1-H Edged: Dagger"] == 2
    # Other rows unchanged.
    assert skills["1-H Conc.: mace"] == 1
    assert skills["Riding (horses)"] == 1


def test_apply_requires_race(client) -> None:
    """Apply with no race set returns 409."""
    cid = _create_character(client)
    r = client.post(f"/api/v1/characters/{cid}/apply-adolescence")
    assert r.status_code == 409


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
