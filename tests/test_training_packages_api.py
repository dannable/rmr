"""Tests for the training-packages endpoints + loader.

The session schema build leaves training_package empty; each test seeds
the minimal "Test Knight"-ish fixture it needs so failures point straight
at the row in question.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _seed_tp(slug: str = "test_knight") -> int:
    """Insert one TP + its child rows. Returns training_package_id."""
    from web.db import connect_rw
    with connect_rw() as conn:
        cur = conn.execute(
            "SELECT training_package_id FROM training_package WHERE slug = ?", (slug,)
        ).fetchone()
        if cur:
            conn.execute("DELETE FROM training_package WHERE slug = ?", (slug,))

        cur = conn.execute(
            "INSERT INTO training_package (slug, name, category, description, default_cost) "
            "VALUES (?, ?, ?, ?, ?) RETURNING training_package_id",
            (slug, "Test Knight", "RMFRP Test",
             "A warrior dedicated to a cause or a lord.", 57),
        )
        tpid = cur.fetchone()[0]
        # 2 specials.
        for i, (chance, desc) in enumerate([
            (30, "Warhorse"),
            (40, "Weapon (+10 non-magic)"),
        ]):
            conn.execute(
                "INSERT INTO training_package_special "
                "(training_package_id, sort_order, chance, description) VALUES (?, ?, ?, ?)",
                (tpid, i, chance, desc),
            )
        # 1 guaranteed stat gain + 1 choice slot.
        conn.execute(
            "INSERT INTO training_package_stat_gain "
            "(training_package_id, sort_order, stat_code, has_choice) VALUES (?, 0, 'St', 0)",
            (tpid,),
        )
        conn.execute(
            "INSERT INTO training_package_stat_gain "
            "(training_package_id, sort_order, stat_code, has_choice) VALUES (?, 1, NULL, 1)",
            (tpid,),
        )
        for c in ("Em", "In"):
            conn.execute(
                "INSERT INTO training_package_stat_gain_choice "
                "(training_package_id, sort_order, stat_code) VALUES (?, 1, ?)",
                (tpid, c),
            )
        # 1 flexible RA + 1 fixed RA.
        conn.execute(
            """INSERT INTO training_package_rank_assignment (
                training_package_id, sort_order,
                reference_label, group_name, category_name,
                cat_ranks, skill_ranks,
                cat_spread_max, skill_spread_max, ranks_assigned_max
            ) VALUES (?, 0, 'Melee Weapon', NULL, NULL, 2, 2, 1, 1, NULL)""",
            (tpid,),
        )
        for j, (g, c) in enumerate([
            ("Weapon", "1-H Edged"),
            ("Weapon", "2-Handed"),
        ]):
            conn.execute(
                "INSERT INTO training_package_ra_category_option "
                "(training_package_id, sort_order, option_index, group_name, category_name) "
                "VALUES (?, 0, ?, ?, ?)",
                (tpid, j, g, c),
            )
        conn.execute(
            """INSERT INTO training_package_rank_assignment (
                training_package_id, sort_order,
                reference_label, group_name, category_name,
                cat_ranks, skill_ranks,
                cat_spread_max, skill_spread_max, ranks_assigned_max
            ) VALUES (?, 1, NULL, 'Armor', 'Heavy', 2, 2, NULL, NULL, NULL)""",
            (tpid,),
        )
        conn.execute(
            "INSERT INTO training_package_ra_skill_option "
            "(training_package_id, sort_order, option_index, skill_name, classification) "
            "VALUES (?, 1, 0, 'Plate', 'Special Maneuver')",
            (tpid,),
        )
        # 2 profession costs.
        for prof, cost in [("Fighter", 32), ("Magician", 56)]:
            conn.execute(
                "INSERT INTO training_package_profession_cost "
                "(training_package_id, profession_name, cost) VALUES (?, ?, ?)",
                (tpid, prof, cost),
            )
        conn.commit()
    return tpid


# ---------------------------------------------------------------------------
# GET /api/v1/training-packages
# ---------------------------------------------------------------------------

def test_list_training_packages(client) -> None:
    _seed_tp("test_knight")
    r = client.get("/api/v1/training-packages")
    assert r.status_code == 200
    body = r.json()
    slugs = {tp["slug"] for tp in body}
    assert "test_knight" in slugs
    row = next(tp for tp in body if tp["slug"] == "test_knight")
    assert row["name"] == "Test Knight"
    assert row["default_cost"] == 57


def test_get_training_package_detail(client) -> None:
    _seed_tp("test_knight")
    r = client.get("/api/v1/training-packages/test_knight")
    assert r.status_code == 200
    tp = r.json()
    assert tp["name"] == "Test Knight"
    assert tp["default_cost"] == 57

    # Specials present + ordered.
    assert len(tp["specials"]) == 2
    assert tp["specials"][0]["chance"] == 30
    assert tp["specials"][0]["description"] == "Warhorse"

    # Stat gains: first is guaranteed St, second is a choice between Em/In.
    assert tp["stat_gains"][0]["stat_code"] == "St"
    assert tp["stat_gains"][0]["choices"] == []
    assert tp["stat_gains"][1]["stat_code"] is None
    assert sorted(tp["stat_gains"][1]["choices"]) == ["Em", "In"]

    # Rank assignments: first flexible, second fixed.
    ras = tp["rank_assignments"]
    assert ras[0]["reference_label"] == "Melee Weapon"
    assert ras[0]["cat_ranks"] == 2
    assert ras[0]["cat_spread_max"] == 1
    assert {(o["group_name"], o["category_name"]) for o in ras[0]["category_options"]} == {
        ("Weapon", "1-H Edged"), ("Weapon", "2-Handed"),
    }
    assert ras[1]["reference_label"] is None
    assert ras[1]["group_name"] == "Armor"
    assert ras[1]["category_name"] == "Heavy"
    assert ras[1]["skill_options"] == [
        {"skill_name": "Plate", "classification": "Special Maneuver"},
    ]

    # Profession costs come back with both rows.
    cost_by_prof = {pc["profession_name"]: pc["cost"] for pc in tp["profession_costs"]}
    assert cost_by_prof == {"Fighter": 32, "Magician": 56}


def test_get_unknown_tp_returns_404(client) -> None:
    r = client.get("/api/v1/training-packages/no_such_tp")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# auth gating
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/api/v1/training-packages",
    "/api/v1/training-packages/test_knight",
])
def test_endpoints_require_auth(anon_client, path: str) -> None:
    r = anon_client.get(path)
    assert r.status_code == 401, f"{path} expected 401, got {r.status_code}"


# ---------------------------------------------------------------------------
# loader round-trip
# ---------------------------------------------------------------------------

def test_parse_training_package_file(tmp_path) -> None:
    """Spot-check the parser end-to-end: build a small .txt, parse it,
    confirm every section round-trips into the dict shape the loader
    expects."""
    from load import parse_training_package_file
    body = """\
@name: Mini Knight
@slug: mini_knight
@category: RMFRP Test
@default_cost: 50
@description:
 A test knight. Has horses. Hits things.

@specials:
30 | Warhorse
40 | Plate Armor

@stat_gains:
St
Em | In | Pr

@@ 1 | ref:Melee Weapon
@cat_ranks: 2
@skill_ranks: 2
@cat_option: Weapon/1-H Edged
@cat_option: Weapon/2-Handed
@cat_spread_max: 1

@@ 2 | Armor/Heavy
@cat_ranks: 2
@skill_ranks: 2
@skill_option: Plate (Special Maneuver)
@ranks_assigned_max: 1

@@ 3 | Science/Analytic/Basic
@skill_ranks: 1

@profession_costs:
Fighter: 32
Magician: 56
"""
    f = tmp_path / "mini_knight.txt"
    f.write_text(body, encoding="utf-8")
    data = parse_training_package_file(f)
    assert data["name"] == "Mini Knight"
    assert data["slug"] == "mini_knight"
    assert data["default_cost"] == 50

    # Specials
    assert data["specials"] == [
        {"chance": 30, "description": "Warhorse"},
        {"chance": 40, "description": "Plate Armor"},
    ]

    # Stat gains — first guaranteed, second choice.
    assert data["stat_gains"][0] == {"stat_code": "St", "choices": []}
    assert data["stat_gains"][1]["stat_code"] is None
    assert data["stat_gains"][1]["choices"] == ["Em", "In", "Pr"]

    # Rank assignments: 3 blocks.
    ras = data["rank_assignments"]
    assert len(ras) == 3
    assert ras[0]["reference_label"] == "Melee Weapon"
    assert ras[0]["cat_spread_max"] == 1
    assert ras[0]["category_options"] == [
        ("Weapon", "1-H Edged"), ("Weapon", "2-Handed"),
    ]
    assert ras[1]["group_name"] == "Armor"
    assert ras[1]["category_name"] == "Heavy"
    assert ras[1]["skill_options"] == [("Plate", "Special Maneuver")]
    assert ras[1]["ranks_assigned_max"] == 1
    # Slashed group name parses correctly — "Science/Analytic" is the group,
    # "Basic" the category, not "Science" / "Analytic/Basic".
    assert ras[2]["group_name"] == "Science/Analytic"
    assert ras[2]["category_name"] == "Basic"

    # Profession costs.
    cost_by_prof = {p: c for p, c in data["profession_costs"]}
    assert cost_by_prof == {"Fighter": 32, "Magician": 56}
