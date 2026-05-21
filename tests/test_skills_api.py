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
