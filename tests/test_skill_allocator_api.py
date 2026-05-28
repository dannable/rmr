"""Tests for the DP allocator (skill / category ranks + TP purchases)."""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _seed_skill_category(group: str, category: str, **fields) -> None:
    """Insert a skill_category (with its group) into the test DB."""
    from web.db import connect_rw
    with connect_rw() as conn:
        gid = conn.execute(
            "INSERT INTO skill_category_group (slug, section, name, page_div, page_content) "
            "VALUES (?, '', ?, 0, 0) "
            "ON CONFLICT(slug) DO UPDATE SET name = excluded.name "
            "RETURNING group_id",
            (group.lower().replace(" ", "_"), group),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO skill_category "
            "(group_id, name, skills_list, stat_bonuses, rank_progression, "
            " category_progression, classification) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (gid, category, fields.get("skills_list", ""),
             fields.get("stat_bonuses", ""),
             fields.get("rank_progression", "Standard"),
             fields.get("category_progression", "Standard"),
             fields.get("classification", "Static Maneuver")),
        )
        for skill_name in [s.strip() for s in fields.get("skills_list", "").split(",")
                            if s.strip() and s.strip() != "-"]:
            conn.execute(
                "INSERT INTO skill (group_id, name, stat) "
                "VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                (gid, skill_name, fields.get("skill_stat", "St")),
            )
        conn.commit()


def _seed_minimal_fighter() -> int:
    """Fighter-ish profession with one cheap category and a couple of weapon costs."""
    from web.db import connect_rw
    with connect_rw() as conn:
        existing = conn.execute(
            "SELECT profession_id FROM profession WHERE slug = ?", ("test_fighter",),
        ).fetchone()
        if existing:
            conn.execute("DELETE FROM profession WHERE slug = ?", ("test_fighter",))
        cur = conn.execute(
            "INSERT INTO profession (slug, name, description, source) "
            "VALUES (?, ?, ?, ?) RETURNING profession_id",
            ("test_fighter", "Test Fighter", "Hits things.", "character_law"),
        )
        pid = cur.fetchone()[0]
        # Two category costs: Athletic/Brawn = "1/2" (cheap, 2 ranks/level)
        # and Weapon/1-H Edged = "2/5" (Fighter's signature).
        for g, c, cost in [
            ("Athletic", "Brawn", "1/2"),
            ("Weapon",   "1-H Edged", "2/5"),
        ]:
            conn.execute(
                "INSERT INTO profession_category_cost "
                "(profession_id, group_name, category_name, cost) "
                "VALUES (?, ?, ?, ?)", (pid, g, c, cost),
            )
        # A category bonus for Athletic/Brawn.
        conn.execute(
            "INSERT INTO profession_category_bonus "
            "(profession_id, group_name, category_name, bonus) "
            "VALUES (?, 'Athletic', 'Brawn', 5)", (pid,),
        )
        conn.commit()
    return pid


def _create_character_at_fighter(client) -> int:
    """Make a character + assign Test Fighter + raise stats so DP > 0."""
    r = client.post("/api/v1/characters", json={"name": "DP Tester"})
    cid = r.json()["character_id"]
    client.put(f"/api/v1/characters/{cid}/profession", json={"slug": "test_fighter"})
    # Default 50/50 stats → DP per level = 50 (5×50/5 = 50). That's plenty for tests.
    return cid


# ---------------------------------------------------------------------------
# GET skill-allocator
# ---------------------------------------------------------------------------

def test_get_allocator_baseline(client) -> None:
    """No purchases yet → 0 DP spent, all categories listed (the ones the
    profession has a cost for), category bonuses include profession contribution."""
    _seed_minimal_fighter()
    _seed_skill_category("Athletic", "Athletic • Brawn",
                          stat_bonuses="St/Co/Ag", skills_list="Adrenal Stabilization")
    _seed_skill_category("Weapon", "Weapon • 1-H Edged",
                          stat_bonuses="St/Ag/St", skills_list="Broadsword, Falchion")
    cid = _create_character_at_fighter(client)

    r = client.get(f"/api/v1/characters/{cid}/skill-allocator")
    assert r.status_code == 200
    body = r.json()
    assert body["budget"]["dp_total"] == 50   # default 50/50 stats → 250/5 = 50
    assert body["budget"]["dp_spent"] == 0
    assert body["budget"]["dp_remaining"] == 50

    by_cat = {(c["group_name"], c["category_name"]): c for c in body["categories"]}
    brawn = by_cat[("Athletic", "Athletic • Brawn")]
    assert brawn["cost"] == "1/2"
    assert brawn["rank_cap_per_level"] == 2
    assert brawn["next_rank_cost_dp"] == 1
    # Profession category bonus = +5; default 50/50 stats → St=0/Co=0/Ag=0 → 0;
    # rank bonus at 0 ranks → 0. Total = 5.
    assert brawn["total_bonus"] == 5


def test_buy_category_ranks_charges_dp_and_updates_bonus(client) -> None:
    """Buy 2 ranks of Athletic/Brawn (cost 1/2) → 3 DP spent (1+2), bonus = 4 (rank) + 0 (stat) + 5 (prof) = 9."""
    _seed_minimal_fighter()
    _seed_skill_category("Athletic", "Athletic • Brawn",
                          stat_bonuses="St/Co/Ag", skills_list="")
    cid = _create_character_at_fighter(client)

    r = client.put(f"/api/v1/characters/{cid}/category-ranks", json={
        "group_name": "Athletic", "category_name": "Brawn", "ranks_bought": 2,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["budget"]["dp_spent"] == 3   # 1 + 2 = 3
    by_cat = {(c["group_name"], c["category_name"]): c for c in body["categories"]}
    brawn = by_cat[("Athletic", "Athletic • Brawn")]
    assert brawn["ranks_bought"] == 2
    # Standard category progression: 2 ranks = 2×2 = 4 bonus; +5 prof = 9.
    assert brawn["total_bonus"] == 9
    assert brawn["next_rank_cost_dp"] is None   # cap reached (2/2)


def test_buy_category_ranks_rejects_over_cap(client) -> None:
    _seed_minimal_fighter()
    _seed_skill_category("Athletic", "Athletic • Brawn",
                          stat_bonuses="", skills_list="")
    cid = _create_character_at_fighter(client)
    r = client.put(f"/api/v1/characters/{cid}/category-ranks", json={
        "group_name": "Athletic", "category_name": "Brawn", "ranks_bought": 3,
    })
    assert r.status_code == 422
    assert "rank" in r.json()["detail"].lower()


def test_buy_skill_ranks(client) -> None:
    """Buy 1 rank of Broadsword (cost 2/5 → 1st rank = 2 DP)."""
    _seed_minimal_fighter()
    _seed_skill_category("Weapon", "Weapon • 1-H Edged",
                          stat_bonuses="St/Ag/St",
                          skills_list="Broadsword",
                          skill_stat="St")
    cid = _create_character_at_fighter(client)

    r = client.put(f"/api/v1/characters/{cid}/skill-ranks", json={
        "group_name": "Weapon", "category_name": "1-H Edged",
        "skill_name": "Broadsword", "ranks_bought": 1,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["budget"]["dp_spent"] == 2   # 1 rank @ 2 DP

    by_cat = {(c["group_name"], c["category_name"]): c for c in body["categories"]}
    edged = by_cat[("Weapon", "Weapon • 1-H Edged")]
    bsword = next(s for s in edged["skills"] if s["skill_name"] == "Broadsword")
    assert bsword["ranks_bought"] == 1
    # Skill total = category total + skill rank bonus (5 @ 1 rank) + skill stat (St=0 @ temp 50).
    # Category total = category ranks (0) + cat stat (St/Ag/St → 0) + prof bonus (0 for Weapon) = 0.
    # → 0 + 5 + 0 = 5.
    assert bsword["total_bonus"] == 5


def test_buy_uses_reassigned_weapon_cost(client) -> None:
    """If the player reassigned 1-H Edged from 2/5 → 5, the new cost applies."""
    _seed_minimal_fighter()
    _seed_skill_category("Weapon", "Weapon • 1-H Edged",
                          stat_bonuses="St/Ag/St", skills_list="Broadsword")
    cid = _create_character_at_fighter(client)
    # Wait — _seed_minimal_fighter only has 2 weapon costs, not 7, so reassign
    # using its 2-cost pool. Swap: 1-H Edged gets "1/2" (was 2/5),
    # nothing else to swap because Athletic/Brawn isn't a weapon.
    # We need ANOTHER weapon to swap with; let's add one.
    from web.db import connect_rw
    with connect_rw() as conn:
        pid = conn.execute("SELECT profession_id FROM profession WHERE slug = 'test_fighter'").fetchone()[0]
        conn.execute(
            "INSERT INTO profession_category_cost (profession_id, group_name, category_name, cost) "
            "VALUES (?, 'Weapon', 'Pole Arms', '5')", (pid,),
        )
        conn.commit()
    # Now Weapon pool = {2/5, 5}. Swap: 1-H Edged gets 5; Pole Arms gets 2/5.
    r = client.put(f"/api/v1/characters/{cid}/weapon-costs", json={
        "assignments": [
            {"weapon_category": "1-H Edged", "cost": "5"},
            {"weapon_category": "Pole Arms", "cost": "2/5"},
        ],
    })
    assert r.status_code == 200, r.text

    # Now 1-H Edged is single-rank-per-level @ 5 DP.
    r = client.put(f"/api/v1/characters/{cid}/skill-ranks", json={
        "group_name": "Weapon", "category_name": "1-H Edged",
        "skill_name": "Broadsword", "ranks_bought": 1,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["budget"]["dp_spent"] == 5   # New cost is 5, not 2.


# ---------------------------------------------------------------------------
# Training packages
# ---------------------------------------------------------------------------

def _seed_tp_with_profession_cost(slug: str, name: str, default_cost: int,
                                    prof_name: str | None, prof_cost: int | None) -> int:
    """Insert a TP with optional per-profession cost row."""
    from web.db import connect_rw
    with connect_rw() as conn:
        existing = conn.execute(
            "SELECT training_package_id FROM training_package WHERE slug = ?",
            (slug,),
        ).fetchone()
        if existing:
            conn.execute("DELETE FROM training_package WHERE slug = ?", (slug,))
        cur = conn.execute(
            "INSERT INTO training_package (slug, name, category, description, "
            " default_cost, source) "
            "VALUES (?, ?, 'RMFRP Test', '', ?, 'character_law') "
            "RETURNING training_package_id",
            (slug, name, default_cost),
        )
        tpid = cur.fetchone()[0]
        if prof_name is not None and prof_cost is not None:
            conn.execute(
                "INSERT INTO training_package_profession_cost "
                "(training_package_id, profession_name, cost) "
                "VALUES (?, ?, ?)", (tpid, prof_name, prof_cost),
            )
        conn.commit()
    return tpid


def test_tp_available_uses_per_profession_cost(client) -> None:
    """A TP with a Fighter-specific cost shows that cost, not default_cost."""
    _seed_minimal_fighter()
    _seed_tp_with_profession_cost("test_knight", "Test Knight", 60,
                                    prof_name="Test Fighter", prof_cost=42)
    cid = _create_character_at_fighter(client)

    r = client.get(f"/api/v1/characters/{cid}/training-packages-available")
    body = r.json()
    knight = next(o for o in body["options"] if o["slug"] == "test_knight")
    assert knight["effective_cost"] == 42
    assert knight["affordable"] is True   # 42 ≤ 50 (DP remaining)


def test_tp_available_falls_back_to_default_cost(client) -> None:
    """No per-profession row → use TP.default_cost."""
    _seed_minimal_fighter()
    _seed_tp_with_profession_cost("test_obscure", "Obscure TP", 80,
                                    prof_name=None, prof_cost=None)
    cid = _create_character_at_fighter(client)

    body = client.get(f"/api/v1/characters/{cid}/training-packages-available").json()
    tp = next(o for o in body["options"] if o["slug"] == "test_obscure")
    assert tp["effective_cost"] == 80
    assert tp["affordable"] is False   # 80 > 50 DP


def test_purchase_tp_deducts_dp(client) -> None:
    _seed_minimal_fighter()
    _seed_tp_with_profession_cost("test_knight", "Test Knight", 60,
                                    prof_name="Test Fighter", prof_cost=42)
    cid = _create_character_at_fighter(client)
    r = client.post(f"/api/v1/characters/{cid}/training-packages/test_knight")
    assert r.status_code == 201
    body = r.json()
    assert body["budget"]["dp_spent"] == 42
    assert body["budget"]["dp_remaining"] == 8
    assert len(body["training_packages_purchased"]) == 1
    assert body["training_packages_purchased"][0]["dp_paid"] == 42


def test_purchase_tp_double_buy_is_conflict(client) -> None:
    _seed_minimal_fighter()
    _seed_tp_with_profession_cost("test_knight", "Test Knight", 60,
                                    prof_name="Test Fighter", prof_cost=42)
    cid = _create_character_at_fighter(client)
    client.post(f"/api/v1/characters/{cid}/training-packages/test_knight")
    r = client.post(f"/api/v1/characters/{cid}/training-packages/test_knight")
    assert r.status_code == 409


def test_refund_tp_restores_dp(client) -> None:
    _seed_minimal_fighter()
    _seed_tp_with_profession_cost("test_knight", "Test Knight", 60,
                                    prof_name="Test Fighter", prof_cost=42)
    cid = _create_character_at_fighter(client)
    client.post(f"/api/v1/characters/{cid}/training-packages/test_knight")
    r = client.delete(f"/api/v1/characters/{cid}/training-packages/test_knight")
    assert r.status_code == 200
    body = r.json()
    assert body["budget"]["dp_spent"] == 0
    assert body["training_packages_purchased"] == []


def test_refund_unknown_tp_404(client) -> None:
    _seed_minimal_fighter()
    cid = _create_character_at_fighter(client)
    r = client.delete(f"/api/v1/characters/{cid}/training-packages/never_bought")
    assert r.status_code == 404


def test_purchase_unknown_tp_404(client) -> None:
    _seed_minimal_fighter()
    cid = _create_character_at_fighter(client)
    r = client.post(f"/api/v1/characters/{cid}/training-packages/never_existed")
    assert r.status_code == 404


def test_purchase_tp_requires_profession(client) -> None:
    _seed_tp_with_profession_cost("test_knight", "Test Knight", 60, None, None)
    r = client.post("/api/v1/characters", json={"name": "ProfLess"})
    cid = r.json()["character_id"]
    r = client.post(f"/api/v1/characters/{cid}/training-packages/test_knight")
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,path,body", [
    ("GET",    "/api/v1/characters/1/skill-allocator", None),
    ("PUT",    "/api/v1/characters/1/category-ranks",
       {"group_name": "g", "category_name": "c", "ranks_bought": 0}),
    ("PUT",    "/api/v1/characters/1/skill-ranks",
       {"group_name": "g", "category_name": "c", "skill_name": "s", "ranks_bought": 0}),
    ("GET",    "/api/v1/characters/1/training-packages-available", None),
    ("POST",   "/api/v1/characters/1/training-packages/foo", None),
    ("DELETE", "/api/v1/characters/1/training-packages/foo", None),
])
def test_skill_allocator_endpoints_require_auth(anon_client, method, path, body) -> None:
    kwargs = {"json": body} if body is not None else {}
    r = anon_client.request(method, path, **kwargs)
    assert r.status_code == 401
