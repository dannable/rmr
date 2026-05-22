"""Tests for the skills catalog API (web/api/skills.py).

The schema-build fixture leaves the skill_category_group table empty.
We seed a minimal "Crafts-like" fixture inline so the assertions are
debuggable.
"""

from __future__ import annotations

import pytest


def _seed_skill_group(slug: str = "test_crafts") -> int:
    """Insert one group + 1 category + 2 skills + 1 table. Returns group_id."""
    from web.db import connect_rw
    with connect_rw() as conn:
        # Wipe any prior fixture rows for this slug so re-runs are clean.
        cur = conn.execute(
            "SELECT group_id FROM skill_category_group WHERE slug = ?", (slug,)
        ).fetchone()
        if cur:
            conn.execute("DELETE FROM skill_category_group WHERE slug = ?", (slug,))
            conn.commit()

        cur = conn.execute(
            """INSERT INTO skill_category_group (slug, section, name, page_div, page_content)
               VALUES (?, 'A-1.99', 'Test Crafts', 99, 100) RETURNING group_id""",
            (slug,),
        )
        group_id = cur.fetchone()[0]
        conn.execute(
            """INSERT INTO skill_category (
                group_id, name, skills_list, restricted, stat_bonuses,
                rank_progression, category_progression, parent_group,
                classification, description
               ) VALUES (?, 'Test Crafts', 'Cooking, Sewing', '—',
                         'Ag/Me/SD', 'Combined', '0 • 0 • 0 • 0 • 0',
                         'Craft', 'Static Maneuver',
                         'A test crafts category.')""",
            (group_id,),
        )
        for name, stat, desc in [
            ("Cooking", "In", "Cook food."),
            ("Sewing",  "In", "Sew things."),
        ]:
            conn.execute(
                "INSERT INTO skill (group_id, name, stat, description) "
                "VALUES (?, ?, ?, ?)",
                (group_id, name, stat, desc),
            )
        cur = conn.execute(
            """INSERT INTO skill_table (group_id, name, columns, general_mods) VALUES
               (?, 'Test Table T-9.9', 'roll | result | percent | time | mod | description',
                'Practiced: +5' || char(10) || 'Improvised: -10')
               RETURNING table_id""",
            (group_id,),
        )
        tid = cur.fetchone()[0]
        conn.execute(
            """INSERT INTO skill_table_row (
                table_id, sort_order, roll, result, percent, time, mod, description
               ) VALUES (?, 0, '01-05', 'Failure', '0%', '—', '+0', 'You fail.')""",
            (tid,),
        )
        conn.commit()
    return group_id


# ---------------------------------------------------------------------------
# list / detail / search
# ---------------------------------------------------------------------------

def test_list_skill_groups(client) -> None:
    _seed_skill_group("test_crafts")
    r = client.get("/api/v1/skills")
    assert r.status_code == 200
    body = r.json()
    slugs = {g["slug"] for g in body}
    assert "test_crafts" in slugs


def test_get_skill_group_detail(client) -> None:
    _seed_skill_group("test_crafts")
    r = client.get("/api/v1/skills/test_crafts")
    assert r.status_code == 200
    g = r.json()
    assert g["slug"] == "test_crafts"
    assert g["section"] == "A-1.99"
    assert len(g["categories"]) == 1
    cat = g["categories"][0]
    assert cat["name"] == "Test Crafts"
    assert cat["stat_bonuses"] == "Ag/Me/SD"
    assert {s["name"] for s in g["skills"]} == {"Cooking", "Sewing"}
    assert len(g["tables"]) == 1
    t = g["tables"][0]
    assert t["name"] == "Test Table T-9.9"
    assert t["columns"] == ["roll", "result", "percent", "time", "mod", "description"]
    assert t["general_mods"] == ["Practiced: +5", "Improvised: -10"]
    assert len(t["rows"]) == 1
    assert t["rows"][0]["roll"] == "01-05"


def test_get_unknown_group_returns_404(client) -> None:
    r = client.get("/api/v1/skills/no_such_group_xyz")
    assert r.status_code == 404


def test_sohk_data_round_trips(client) -> None:
    """Inject SOHK data directly into the seed group, verify the API surfaces
    it on Skill.sohk_data + SkillGroupDetail.sohk_notes."""
    import json as _json
    from web.db import connect_rw
    _seed_skill_group("test_crafts")
    with connect_rw() as conn:
        # Drop SOHK payload onto the first skill, plus group + category notes.
        sohk = {
            "optional_stats": "In/Re/Pr",
            "ep_cost": "1 every 4 rounds",
            "distance_multiplier": "0.5",
            "notes": "Practitioners must be sober.",
            "specialties": ["Knives", "Hooks"],
            "example_difficulties": {
                "Routine": "Boiling water.",
                "Hard":    "A multi-course banquet under deadline.",
            },
        }
        conn.execute(
            "UPDATE skill SET sohk_data = ? WHERE name = 'Cooking'",
            (_json.dumps(sohk),),
        )
        conn.execute(
            "UPDATE skill_category_group SET sohk_notes = ? WHERE slug = 'test_crafts'",
            ("Crafts maneuvers consume EP only when rushed.",),
        )
        conn.commit()

    r = client.get("/api/v1/skills/test_crafts")
    assert r.status_code == 200
    g = r.json()
    assert g["sohk_notes"].startswith("Crafts maneuvers consume EP")
    cook = next(s for s in g["skills"] if s["name"] == "Cooking")
    sd = cook["sohk_data"]
    assert sd["optional_stats"] == "In/Re/Pr"
    assert sd["ep_cost"] == "1 every 4 rounds"
    assert sd["specialties"] == ["Knives", "Hooks"]
    assert sd["example_difficulties"]["Routine"] == "Boiling water."
    # Other skills carry the empty default payload.
    sew = next(s for s in g["skills"] if s["name"] == "Sewing")
    assert sew["sohk_data"]["optional_stats"] == ""
    assert sew["sohk_data"]["specialties"] == []


def test_search_skills_by_name(client) -> None:
    _seed_skill_group("test_crafts")
    r = client.get("/api/v1/skills/search?q=cook")
    assert r.status_code == 200
    body = r.json()
    assert any(h["name"] == "Cooking" and h["group_slug"] == "test_crafts" for h in body)


def test_search_requires_q(client) -> None:
    r = client.get("/api/v1/skills/search")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# auth gating
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/api/v1/skills",
    "/api/v1/skills/test_crafts",
    "/api/v1/skills/search?q=cook",
])
def test_endpoints_require_auth(anon_client, path: str) -> None:
    r = anon_client.get(path)
    assert r.status_code == 401, f"{path} expected 401, got {r.status_code}"


# ---------------------------------------------------------------------------
# PUT /api/v1/skills/{slug} — wholesale edit
# ---------------------------------------------------------------------------

def test_put_skill_group_updates_db_and_file(client, tmp_path, monkeypatch) -> None:
    """PUT should wipe + replace the group's children, stamp audit fields,
    and rewrite data/skills/<slug>.txt at the configured project root."""
    # Redirect file write-back to a temp directory so we don't clobber
    # data/skills/test_crafts.txt under the repo.
    from web.api import skills as skills_api
    monkeypatch.setattr(skills_api, "_PROJECT_ROOT", tmp_path)

    _seed_skill_group("test_crafts")
    r = client.get("/api/v1/skills/test_crafts")
    assert r.status_code == 200
    original = r.json()

    # Fix an extraction error (skill description) + add a row to the table
    # + rewrite a GM mod entry. Send back the full group payload.
    payload = {
        "name": original["name"],
        "categories": [
            {**c, "description": "Edited category description."}
            for c in original["categories"]
        ],
        "skills": [
            {**s, "description": f"Edited: {s['description']}"}
            for s in original["skills"]
        ],
        "tables": [
            {
                **t,
                "general_mods": ["New mod: +99"],
                "rows": t["rows"] + [{
                    "roll": "UM 100", "result": "Unusual Success",
                    "percent": "150%", "time": "1.0u", "mod": "+50",
                    "description": "Astounding.",
                }],
            }
            for t in original["tables"]
        ],
    }
    r = client.put("/api/v1/skills/test_crafts", json=payload)
    assert r.status_code == 200, r.text
    updated = r.json()

    assert updated["categories"][0]["description"] == "Edited category description."
    assert all(s["description"].startswith("Edited: ") for s in updated["skills"])
    assert updated["tables"][0]["general_mods"] == ["New mod: +99"]
    assert len(updated["tables"][0]["rows"]) == 2
    assert updated["tables"][0]["rows"][1]["roll"] == "UM 100"
    assert updated["updated_at"] is not None

    # The file should now exist under the tmp project root.
    written = tmp_path / "data" / "skills" / "test_crafts.txt"
    assert written.exists(), "expected write-back to create data/skills/test_crafts.txt"
    body = written.read_text(encoding="utf-8")
    assert "@group_name: Test Crafts" in body
    assert "@@ Cooking" in body
    assert "UM 100 | Unusual Success" in body
    assert "@general_mods:" in body
    assert "New mod: +99" in body


def test_put_unknown_group_returns_404(client, tmp_path, monkeypatch) -> None:
    from web.api import skills as skills_api
    monkeypatch.setattr(skills_api, "_PROJECT_ROOT", tmp_path)

    r = client.put(
        "/api/v1/skills/no_such_group_xyz",
        json={"categories": [], "skills": [], "tables": []},
    )
    assert r.status_code == 404


def test_put_requires_auth(anon_client) -> None:
    r = anon_client.put(
        "/api/v1/skills/test_crafts",
        json={"categories": [], "skills": [], "tables": []},
    )
    assert r.status_code == 401


def test_put_roundtrip_parses_back(client, tmp_path, monkeypatch) -> None:
    """The serialised file should round-trip through load.parse_skill_file
    without losing structure — guards against subtle format drift."""
    from web.api import skills as skills_api
    monkeypatch.setattr(skills_api, "_PROJECT_ROOT", tmp_path)

    _seed_skill_group("test_crafts")
    r = client.get("/api/v1/skills/test_crafts")
    original = r.json()
    # Send the same payload back so an identity edit produces a parseable file.
    payload = {
        "categories": original["categories"],
        "skills": original["skills"],
        "tables": original["tables"],
    }
    r = client.put("/api/v1/skills/test_crafts", json=payload)
    assert r.status_code == 200

    from load import parse_skill_file
    parsed = parse_skill_file(tmp_path / "data" / "skills" / "test_crafts.txt")
    assert parsed["slug"] == "test_crafts"
    assert parsed["name"] == "Test Crafts"
    assert len(parsed["categories"]) == 1
    assert {s["name"] for s in parsed["skills"]} == {"Cooking", "Sewing"}
    assert len(parsed["tables"]) == 1
    assert parsed["tables"][0]["general_mods"] == [
        "Practiced: +5", "Improvised: -10",
    ]
    assert parsed["tables"][0]["rows"][0]["roll"] == "01-05"
