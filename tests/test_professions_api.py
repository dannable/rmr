"""Tests for the profession endpoints + character profession picker.

The session schema build leaves the profession tables empty; each test
seeds the minimal "Test Magician"-ish fixture it needs via _seed_profession
so failures point straight at the row in question rather than a global
dataset.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _seed_profession(slug: str = "test_magician", **overrides) -> int:
    """Insert one profession + its child rows. Returns profession_id."""
    from web.db import connect_rw

    defaults = {
        "name": "Test Magician",
        "description": "Pure spell users who toss elemental dice around.",
        "realms": ["Essence"],
        "prime_stats": ["Em", "Re"],
        "group_bonuses": [
            ("Directed Spells", 10),
            ("Power Awareness", 10),
        ],
        "category_bonuses": [
            ("Lore", "Magical", 5),
        ],
        "category_costs": [
            ("Armor", "Heavy", "11"),
            ("Armor", "Light", "9"),
            ("Spells", "Own Realm Own Base Lists", "3/3/3"),
        ],
        "skill_cost_modifiers": [
            ("Self Control", "Self Control", "Meditation",
             "Static Maneuver", 0.5),
        ],
        "favorite_skills": [
            ("Awareness", "Perceptions", "Alertness", "Static Maneuver"),
            ("Body Development", "Body Development", "Body Development",
             "Special Maneuver"),
        ],
    }
    defaults.update(overrides)

    with connect_rw() as conn:
        # Idempotent re-seed: wipe any prior fixture row.
        existing = conn.execute(
            "SELECT profession_id FROM profession WHERE slug = ?", (slug,)
        ).fetchone()
        if existing:
            conn.execute("DELETE FROM profession WHERE slug = ?", (slug,))

        cur = conn.execute(
            "INSERT INTO profession (slug, name, description, portrait_path) "
            "VALUES (?, ?, ?, ?) RETURNING profession_id",
            (slug, defaults["name"], defaults["description"], None),
        )
        pid = cur.fetchone()[0]
        for realm in defaults["realms"]:
            conn.execute(
                "INSERT INTO profession_realm (profession_id, realm_name) VALUES (?, ?)",
                (pid, realm),
            )
        for stat in defaults["prime_stats"]:
            conn.execute(
                "INSERT INTO profession_prime_stat (profession_id, stat_code) VALUES (?, ?)",
                (pid, stat),
            )
        for g, b in defaults["group_bonuses"]:
            conn.execute(
                "INSERT INTO profession_group_bonus (profession_id, group_name, bonus) "
                "VALUES (?, ?, ?)", (pid, g, b),
            )
        for g, c, b in defaults["category_bonuses"]:
            conn.execute(
                "INSERT INTO profession_category_bonus "
                "(profession_id, group_name, category_name, bonus) "
                "VALUES (?, ?, ?, ?)", (pid, g, c, b),
            )
        for g, c, cost in defaults["category_costs"]:
            conn.execute(
                "INSERT INTO profession_category_cost "
                "(profession_id, group_name, category_name, cost) "
                "VALUES (?, ?, ?, ?)", (pid, g, c, cost),
            )
        for g, c, s, klass, mod in defaults["skill_cost_modifiers"]:
            conn.execute(
                "INSERT INTO profession_skill_cost_modifier "
                "(profession_id, group_name, category_name, skill_name, "
                " classification, modifier) "
                "VALUES (?, ?, ?, ?, ?, ?)", (pid, g, c, s, klass, mod),
            )
        for i, (g, c, s, klass) in enumerate(defaults["favorite_skills"]):
            conn.execute(
                "INSERT INTO profession_favorite_skill "
                "(profession_id, group_name, category_name, skill_name, "
                " classification, sort_order) "
                "VALUES (?, ?, ?, ?, ?, ?)", (pid, g, c, s, klass, i),
            )
        conn.commit()
    return pid


def _create_character(client, name: str = "Test") -> int:
    r = client.post("/api/v1/characters", json={"name": name})
    assert r.status_code == 201
    return r.json()["character_id"]


# ---------------------------------------------------------------------------
# GET /api/v1/professions
# ---------------------------------------------------------------------------

def test_list_professions(client) -> None:
    _seed_profession("test_magician")
    r = client.get("/api/v1/professions")
    assert r.status_code == 200
    body = r.json()
    slugs = {p["slug"] for p in body}
    assert "test_magician" in slugs
    row = next(p for p in body if p["slug"] == "test_magician")
    assert row["realms"] == ["Essence"]
    assert sorted(row["prime_stats"]) == ["Em", "Re"]


def test_get_profession_detail(client) -> None:
    _seed_profession("test_magician")
    r = client.get("/api/v1/professions/test_magician")
    assert r.status_code == 200
    p = r.json()
    assert p["name"] == "Test Magician"
    assert {b["group_name"] for b in p["group_bonuses"]} == {
        "Directed Spells", "Power Awareness",
    }
    assert p["category_bonuses"][0]["bonus"] == 5
    # Cost strings come through verbatim — that's the contract.
    costs_by_path = {(c["group_name"], c["category_name"]): c["cost"]
                     for c in p["category_costs"]}
    assert costs_by_path[("Spells", "Own Realm Own Base Lists")] == "3/3/3"
    fav_names = {f["skill_name"] for f in p["favorite_skills"]}
    assert "Alertness" in fav_names
    assert p["skill_cost_modifiers"][0]["modifier"] == 0.5


def test_get_unknown_profession_returns_404(client) -> None:
    r = client.get("/api/v1/professions/no_such_profession_xyz")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/v1/characters/{id}/profession
# ---------------------------------------------------------------------------

def test_pick_profession_for_character(client) -> None:
    _seed_profession("test_magician")
    cid = _create_character(client)

    r = client.put(f"/api/v1/characters/{cid}/profession", json={"slug": "test_magician"})
    assert r.status_code == 200
    body = r.json()
    assert body["profession_slug"] == "test_magician"
    assert body["profession_name"] == "Test Magician"

    # The GET-by-id should reflect the change.
    r = client.get(f"/api/v1/characters/{cid}")
    assert r.json()["profession_slug"] == "test_magician"


def test_clear_profession(client) -> None:
    _seed_profession("test_magician")
    cid = _create_character(client)
    client.put(f"/api/v1/characters/{cid}/profession", json={"slug": "test_magician"})

    r = client.put(f"/api/v1/characters/{cid}/profession", json={"slug": None})
    assert r.status_code == 200
    assert r.json()["profession_slug"] is None


def test_pick_unknown_profession_returns_422(client) -> None:
    cid = _create_character(client)
    r = client.put(
        f"/api/v1/characters/{cid}/profession",
        json={"slug": "no_such_profession_xyz"},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# auth gating
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/api/v1/professions",
    "/api/v1/professions/test_magician",
])
def test_endpoints_require_auth(anon_client, path: str) -> None:
    r = anon_client.get(path)
    assert r.status_code == 401, f"{path} expected 401, got {r.status_code}"


# ---------------------------------------------------------------------------
# loader round-trip
# ---------------------------------------------------------------------------

def test_parse_profession_file_handles_slashed_group_names(tmp_path) -> None:
    """Group names like "Science/Analytic" and "Technical/Trade" contain
    a slash that collides with our '/' path separator. The parser must
    rsplit so the slash stays in the group name, not become a category
    boundary."""
    from load import parse_profession_file
    body = """\
@name: Slash Tester
@slug: slash_tester
@realms: Essence
@prime_stats: Em
@description: For testing the slash-in-group-name edge case.

@category_costs:
Science/Analytic/Basic: 1/4
Technical/Trade/General: 3/7

@favorite_skills:
Science/Analytic/Basic/Math Theory (Static Maneuver)
"""
    f = tmp_path / "slash_tester.txt"
    f.write_text(body, encoding="utf-8")
    data = parse_profession_file(f)
    costs = {(c[0], c[1]): c[2] for c in data["category_costs"]}
    # "Science/Analytic" should be the group, "Basic" the category — not
    # "Science" and "Analytic/Basic".
    assert ("Science/Analytic", "Basic") in costs
    assert costs[("Science/Analytic", "Basic")] == "1/4"
    assert ("Technical/Trade", "General") in costs
    fav = data["favorite_skills"][0]
    # Skill "Math Theory" sits under "Science/Analytic" / "Basic".
    assert fav == ("Science/Analytic", "Basic", "Math Theory", "Static Maneuver")
