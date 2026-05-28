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

def test_allocator_exposes_stat_bonus_fields(client) -> None:
    """Per RMSS, stat bonuses are a CATEGORY-level concept — skill rows
    don't carry stat / stat_bonus. The allocator surfaces:
      Category: stat_bonuses (codes), stat_bonus (value), class_bonus,
                special_bonus, total_bonus, plus progression strings the
                SPA mirrors for local recompute.
      Skill:    item_bonus, special_bonus, total_bonus (no stat / class
                — those are folded into category_total which the skill
                math cascades from).
    """
    _seed_minimal_fighter()
    _seed_skill_category("Athletic", "Athletic • Brawn",
                          stat_bonuses="St/Co/Ag",
                          skills_list="Adrenal Stabilization",
                          rank_progression="Standard",
                          category_progression="Standard")
    cid = _create_character_at_fighter(client)
    body = client.get(f"/api/v1/characters/{cid}/skill-allocator").json()
    by_cat = {(c["group_name"], c["category_name"]): c for c in body["categories"]}
    brawn = by_cat[("Athletic", "Athletic • Brawn")]
    # Category surfaces stat codes + computed integer value.
    assert brawn["stat_bonuses"] == "St/Co/Ag"
    assert brawn["stat_bonus"] == 0   # default 50/50 stats → T-2.1(50)=0
    assert brawn["category_progression"] == "Standard"
    assert brawn["skill_progression"] == "Standard"
    # Skills don't carry stat / class — they cascade via category_total.
    skill = next(s for s in brawn["skills"] if s["skill_name"] == "Adrenal Stabilization")
    assert "stat" not in skill          # removed
    assert "stat_bonus" not in skill    # removed
    assert "class_bonus" not in skill   # removed
    assert skill["item_bonus"] == 0
    assert skill["special_bonus"] == 0


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
    # RMSS T-2.2: Standard category at 0 ranks = -15 (untrained category).
    # Default 50/50 stats → St/Co/Ag bonuses = 0; class bonus = +5
    # (profession_category_bonus); special = 0. Total = -15 + 0 + 5 + 0 = -10.
    assert brawn["class_bonus"] == 5
    assert brawn["special_bonus"] == 0
    assert brawn["total_bonus"] == -10
    # current_ranks == ranks_bought (no adolescence/hobby/TP yet).
    assert brawn["current_ranks"] == 0
    assert brawn["ranks_bought"] == 0


def test_allocator_surfaces_costs_even_when_catalog_uses_different_naming(client) -> None:
    """Regression for the Phase-B-1 bug: skill_category names like
    "Communication" (singular) didn't match profession costs like
    "Communications" (plural), so the allocator showed `cost=""` for
    every such category and hid it as "untrainable". The fix drives the
    list from `profession_category_cost` and looks up the catalog
    leniently, so cost-bearing categories ALWAYS surface with their cost.
    """
    from web.db import connect_rw
    with connect_rw() as conn:
        # Seed a profession with two costs: one whose catalog name matches
        # (Artistic • Active) and one whose catalog name uses the singular
        # group form (Communication vs Communications).
        conn.execute("DELETE FROM profession WHERE slug = 'test_rogue'")
        cur = conn.execute(
            "INSERT INTO profession (slug, name, description, source) "
            "VALUES ('test_rogue', 'Test Rogue', 'sneaks', 'character_law') "
            "RETURNING profession_id",
        )
        pid = cur.fetchone()[0]
        for g, c, cost in [
            ("Artistic",       "Active",         "2/4"),
            ("Communications", "Communications", "1/1/1"),
        ]:
            conn.execute(
                "INSERT INTO profession_category_cost "
                "(profession_id, group_name, category_name, cost) "
                "VALUES (?, ?, ?, ?)", (pid, g, c, cost),
            )
        conn.commit()
    _seed_skill_category("Artistic • Active", "Artistic • Active",
                          stat_bonuses="Em/Pr/SD", skills_list="")
    # Catalog stores this group as "Communication" (singular) — the bug
    # was that this didn't match the profession's "Communications".
    _seed_skill_category("Communication", "Communication",
                          stat_bonuses="Pr/Re/Pr", skills_list="")

    r = client.post("/api/v1/characters", json={"name": "Rogue Tester"})
    cid = r.json()["character_id"]
    client.put(f"/api/v1/characters/{cid}/profession", json={"slug": "test_rogue"})
    body = client.get(f"/api/v1/characters/{cid}/skill-allocator").json()
    by_short = {(c["group_name"], _category_short(c)): c for c in body["categories"]}

    art = by_short[("Artistic", "Active")]
    assert art["cost"] == "2/4"
    assert art["rank_cap_per_level"] == 2

    comm = by_short[("Communications", "Communications")]
    assert comm["cost"] == "1/1/1"     # the old code returned "" here
    assert comm["rank_cap_per_level"] == 3


def _category_short(cat: dict) -> str:
    """Helper: pull the short category name from a full label."""
    label = cat["category_name"]
    prefix = cat["group_name"] + " • "
    return label[len(prefix):] if label.startswith(prefix) else label


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
    # RMSS T-2.2 standard category: 2 ranks = +4 (2×2). Stat bonus 0 (50/50
    # → St/Co/Ag all 0). Class bonus +5. Total = 4 + 0 + 5 = 9.
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
    # RMSS T-2.2:
    #   Category 1-H Edged at 0 ranks: -15 (untrained); cat stat 0;
    #     class bonus 0 (no Weapon group bonus on test_fighter). cat_total = -15.
    #   Skill Broadsword at 1 rank: +3 (Standard skill); skill stat 0 (St=0).
    #     skill_total = cat_total + skill_rank_bonus + skill_stat = -15 + 3 + 0 = -12.
    assert bsword["total_bonus"] == -12


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


def test_applied_adolescence_category_ranks_surface_in_allocator(client) -> None:
    """User-reported bug: applied adolescence ranks didn't show up as
    Current Ranks in Step 6. Categories with adolescence-granted ranks
    are now written with kind='category' to character_skill, and the
    allocator sums them in."""
    from web.db import connect_rw
    from datetime import datetime, timezone

    _seed_minimal_fighter()
    _seed_skill_category("Athletic", "Athletic • Brawn",
                          stat_bonuses="St/Co/Ag", skills_list="")
    cid = _create_character_at_fighter(client)
    # Pretend adolescence applied 2 ranks of the Athletic • Brawn category.
    with connect_rw() as conn:
        conn.execute(
            "INSERT INTO character_skill "
            "(character_id, skill, kind, rank, source) "
            "VALUES (?, 'Athletic • Brawn', 'category', 2, 'adolescence')",
            (cid,),
        )
        conn.commit()

    body = client.get(f"/api/v1/characters/{cid}/skill-allocator").json()
    by_cat = {(c["group_name"], c["category_name"]): c for c in body["categories"]}
    brawn = by_cat[("Athletic", "Athletic • Brawn")]
    # current_ranks includes the adolescence-applied 2 (ranks_bought is 0).
    assert brawn["current_ranks"] == 2
    assert brawn["ranks_bought"] == 0
    # Bonus uses TOTAL ranks: 2 ranks Standard category = +4; class bonus +5;
    # stat 0; special 0. Total = 4 + 0 + 5 + 0 = 9.
    assert brawn["total_bonus"] == 9


def test_applied_adolescence_skill_ranks_surface_in_allocator(client) -> None:
    """Same for leaf skills — adolescence-applied skill ranks land in
    character_skill with kind='skill', and the allocator sums them."""
    from web.db import connect_rw

    _seed_minimal_fighter()
    _seed_skill_category("Athletic", "Athletic • Brawn",
                          stat_bonuses="St/Co/Ag",
                          skills_list="Adrenal Stabilization",
                          skill_stat="Co")
    cid = _create_character_at_fighter(client)
    with connect_rw() as conn:
        conn.execute(
            "INSERT INTO character_skill "
            "(character_id, skill, kind, rank, source) "
            "VALUES (?, 'Adrenal Stabilization', 'skill', 3, 'adolescence')",
            (cid,),
        )
        conn.commit()

    body = client.get(f"/api/v1/characters/{cid}/skill-allocator").json()
    by_cat = {(c["group_name"], c["category_name"]): c for c in body["categories"]}
    brawn = by_cat[("Athletic", "Athletic • Brawn")]
    skill = next(s for s in brawn["skills"]
                  if s["skill_name"] == "Adrenal Stabilization")
    assert skill["current_ranks"] == 3
    assert skill["ranks_bought"] == 0


def test_tp_purchase_applies_fixed_rank_grants(client) -> None:
    """A bought TP writes character_skill rows for its FIXED assignments
    (reference_label is None, single skill_option), tagged source='tp:<slug>'.
    The allocator's current_ranks reflects them immediately."""
    from web.db import connect_rw

    _seed_minimal_fighter()
    _seed_skill_category("Athletic", "Athletic • Brawn",
                          stat_bonuses="St/Co/Ag",
                          skills_list="Adrenal Stabilization",
                          skill_stat="Co")
    _seed_tp_with_profession_cost("test_tp", "Test TP", 30,
                                    prof_name="Test Fighter", prof_cost=20)
    # Add a fixed rank assignment: 1 category rank + 1 skill rank to a
    # single skill_option. The TP-apply path materialises both.
    with connect_rw() as conn:
        tpid = conn.execute(
            "SELECT training_package_id FROM training_package WHERE slug = 'test_tp'",
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO training_package_rank_assignment "
            "(training_package_id, sort_order, reference_label, "
            " group_name, category_name, cat_ranks, skill_ranks) "
            "VALUES (?, 0, NULL, 'Athletic', 'Brawn', 1, 1)", (tpid,),
        )
        conn.execute(
            "INSERT INTO training_package_ra_skill_option "
            "(training_package_id, sort_order, option_index, skill_name, classification) "
            "VALUES (?, 0, 0, 'Adrenal Stabilization', 'Static Maneuver')", (tpid,),
        )
        conn.commit()

    cid = _create_character_at_fighter(client)
    client.post(f"/api/v1/characters/{cid}/training-packages/test_tp")

    body = client.get(f"/api/v1/characters/{cid}/skill-allocator").json()
    by_cat = {(c["group_name"], c["category_name"]): c for c in body["categories"]}
    brawn = by_cat[("Athletic", "Athletic • Brawn")]
    assert brawn["current_ranks"] == 1     # category rank from the TP
    skill = next(s for s in brawn["skills"]
                  if s["skill_name"] == "Adrenal Stabilization")
    assert skill["current_ranks"] == 1     # skill rank from the TP


def test_tp_refund_removes_applied_rank_grants(client) -> None:
    """Refunding a TP wipes its 'tp:<slug>' rows from character_skill,
    bringing current_ranks back down."""
    from web.db import connect_rw

    _seed_minimal_fighter()
    _seed_skill_category("Athletic", "Athletic • Brawn",
                          stat_bonuses="St/Co/Ag",
                          skills_list="Adrenal Stabilization", skill_stat="Co")
    _seed_tp_with_profession_cost("test_tp", "Test TP", 30,
                                    prof_name="Test Fighter", prof_cost=20)
    with connect_rw() as conn:
        tpid = conn.execute(
            "SELECT training_package_id FROM training_package WHERE slug = 'test_tp'",
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO training_package_rank_assignment "
            "(training_package_id, sort_order, reference_label, "
            " group_name, category_name, cat_ranks, skill_ranks) "
            "VALUES (?, 0, NULL, 'Athletic', 'Brawn', 1, 0)", (tpid,),
        )
        conn.commit()

    cid = _create_character_at_fighter(client)
    client.post(f"/api/v1/characters/{cid}/training-packages/test_tp")
    body = client.get(f"/api/v1/characters/{cid}/skill-allocator").json()
    by_cat = {(c["group_name"], c["category_name"]): c for c in body["categories"]}
    assert by_cat[("Athletic", "Athletic • Brawn")]["current_ranks"] == 1

    client.delete(f"/api/v1/characters/{cid}/training-packages/test_tp")
    body = client.get(f"/api/v1/characters/{cid}/skill-allocator").json()
    by_cat = {(c["group_name"], c["category_name"]): c for c in body["categories"]}
    assert by_cat[("Athletic", "Athletic • Brawn")]["current_ranks"] == 0


def test_tp_ranks_stack_with_adolescence_ranks(client) -> None:
    """Bonus math should use the SUM of ranks across sources. If
    adolescence applied 2 category ranks and a TP grants 1 more, current
    is 3 and the bonus reflects 3 ranks."""
    from web.db import connect_rw

    _seed_minimal_fighter()
    _seed_skill_category("Athletic", "Athletic • Brawn",
                          stat_bonuses="St/Co/Ag", skills_list="")
    _seed_tp_with_profession_cost("test_tp", "Test TP", 30,
                                    prof_name="Test Fighter", prof_cost=15)
    with connect_rw() as conn:
        tpid = conn.execute(
            "SELECT training_package_id FROM training_package WHERE slug = 'test_tp'",
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO training_package_rank_assignment "
            "(training_package_id, sort_order, reference_label, "
            " group_name, category_name, cat_ranks, skill_ranks) "
            "VALUES (?, 0, NULL, 'Athletic', 'Brawn', 1, 0)", (tpid,),
        )
        conn.commit()

    cid = _create_character_at_fighter(client)
    # Pre-seed an adolescence row for the same category.
    with connect_rw() as conn:
        conn.execute(
            "INSERT INTO character_skill "
            "(character_id, skill, kind, rank, source) "
            "VALUES (?, 'Athletic • Brawn', 'category', 2, 'adolescence')",
            (cid,),
        )
        conn.commit()
    client.post(f"/api/v1/characters/{cid}/training-packages/test_tp")

    body = client.get(f"/api/v1/characters/{cid}/skill-allocator").json()
    by_cat = {(c["group_name"], c["category_name"]): c for c in body["categories"]}
    brawn = by_cat[("Athletic", "Athletic • Brawn")]
    # Adolescence:2 + TP:1 = 3 current ranks. Standard category at 3 ranks = +6.
    # class +5, stat 0, special 0. Total = 6 + 0 + 5 + 0 = 11.
    assert brawn["current_ranks"] == 3
    assert brawn["total_bonus"] == 11


def test_purchase_tp_requires_profession(client) -> None:
    _seed_tp_with_profession_cost("test_knight", "Test Knight", 60, None, None)
    r = client.post("/api/v1/characters", json={"name": "ProfLess"})
    cid = r.json()["character_id"]
    r = client.post(f"/api/v1/characters/{cid}/training-packages/test_knight")
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Per-race Body Development / PP Development progressions
# ---------------------------------------------------------------------------

def _seed_race_with_progressions(
    slug: str, *, body: str, chan: str, ess: str, ment: str,
) -> int:
    """Insert (or replace) a race row with custom progressions. Returns
    race_id. Only the columns this test needs are populated — stat / RR
    mods left at zero."""
    from web.db import connect_rw
    with connect_rw() as conn:
        conn.execute("DELETE FROM race WHERE slug = ?", (slug,))
        conn.execute(
            "INSERT INTO race (slug, name, "
            "stat_ag, stat_co, stat_me, stat_re, stat_sd, "
            "stat_em, stat_in, stat_pr, stat_qu, stat_st, "
            "rr_ess, rr_chan, rr_ment, rr_pois, rr_dis, bg_opts, "
            "body_dev_prog, chan_pp_prog, ess_pp_prog, ment_pp_prog) "
            "VALUES (?, ?, 0,0,0,0,0,0,0,0,0,0, 0,0,0,0,0,5, ?, ?, ?, ?)",
            (slug, slug.replace("_", " ").title(), body, chan, ess, ment),
        )
        rid = conn.execute(
            "SELECT race_id FROM race WHERE slug = ?", (slug,),
        ).fetchone()[0]
        conn.commit()
    return rid


def _assign_race(cid: int, race_id: int, culture_slug: str | None = None) -> None:
    from web.db import connect_rw
    with connect_rw() as conn:
        conn.execute(
            "UPDATE character SET race_id = ?, culture_slug = ? "
            "WHERE character_id = ?",
            (race_id, culture_slug, cid),
        )
        conn.commit()


def _add_profession_cost(prof_slug: str, group: str, category: str, cost: str) -> None:
    """Slot in a profession_category_cost row so Pass 1 picks up the
    catalog (and its skills_list) for `category`. Without this, Pass 2's
    list_skill_categories projection is missing skills_list — fine in
    production where every profession lists Body Dev / PP Dev, but our
    minimal test_fighter doesn't out of the box."""
    from web.db import connect_rw
    with connect_rw() as conn:
        pid = conn.execute(
            "SELECT profession_id FROM profession WHERE slug = ?", (prof_slug,),
        ).fetchone()[0]
        conn.execute(
            "INSERT OR REPLACE INTO profession_category_cost "
            "(profession_id, group_name, category_name, cost) "
            "VALUES (?, ?, ?, ?)", (pid, group, category, cost),
        )
        conn.commit()


def _assign_profession_realm(prof_slug: str, *realms: str) -> None:
    from web.db import connect_rw
    with connect_rw() as conn:
        pid = conn.execute(
            "SELECT profession_id FROM profession WHERE slug = ?", (prof_slug,),
        ).fetchone()[0]
        conn.execute("DELETE FROM profession_realm WHERE profession_id = ?", (pid,))
        for r in realms:
            conn.execute(
                "INSERT INTO profession_realm (profession_id, realm_name) "
                "VALUES (?, ?)", (pid, r),
            )
        conn.commit()


def test_body_dev_progression_uses_race(client) -> None:
    """Per RMSS T-2.2, Body Development's skill progression is race-
    specific. A Dwarf-like race with 0•7•4•2•1 must surface that string
    on the Body Development category (so the SPA's optimistic mirror and
    the server's bonus math both use it)."""
    _seed_minimal_fighter()
    _add_profession_cost("test_fighter", "Concepts", "Body Development", "2/5")
    _seed_skill_category("Concepts", "Body Development",
                          stat_bonuses="Co/SD/Co",
                          skills_list="BODY DEVELOPMENT",
                          skill_stat="Co",
                          rank_progression="",
                          category_progression="0 • 0 • 0 • 0 • 0")
    rid = _seed_race_with_progressions(
        "dwarves_test",
        body="0 • 7 • 4 • 2 • 1",
        chan="0 • 6 • 5 • 4 • 3",
        ess="0 • 3 • 2 • 1 • 1",
        ment="0 • 3 • 2 • 1 • 1",
    )
    cid = _create_character_at_fighter(client)
    _assign_race(cid, rid)

    body = client.get(f"/api/v1/characters/{cid}/skill-allocator").json()
    by_cat = {(c["group_name"], c["category_name"]): c for c in body["categories"]}
    body_dev = by_cat.get(("Concepts", "Concepts • Body Development"))
    assert body_dev is not None
    # The CATEGORY now carries the race progression — the user buys
    # ranks via the category +/- buttons (where the cost lives), and
    # those clicks now drive the bonus.
    assert body_dev["category_progression"] == "7 • 4 • 2 • 1"
    # The skill row is a passthrough — its own rank track contributes
    # 0 so cat + skill ranks don't double-count (they're SUMMED into
    # the category's rank_b computation).
    assert body_dev["skill_progression"] == "0 • 0 • 0 • 0 • 0"
    # At 0 ranks the dotted progression sum is 0 (loop doesn't enter
    # for remaining=0). No -15 malus. Correct floor for untrained.
    assert body_dev["total_bonus"] == 0
    sk = body_dev["skills"][0]
    assert sk["current_ranks"] == 0
    assert sk["total_bonus"] == 0


def test_pp_dev_progression_uses_race_and_realm(client) -> None:
    """Power Point Development pulls from race × profession realm.
    A Dwarf-like race with Essence chosen (Fighter coerced to Essence
    here for the test) should land on the dwarves' Essence column."""
    _seed_minimal_fighter()
    _add_profession_cost("test_fighter", "Concepts", "Power Point Development", "4")
    _assign_profession_realm("test_fighter", "Essence")
    _seed_skill_category("Concepts", "Power Point Development",
                          stat_bonuses="Realm stat",
                          skills_list="Power Point Development",
                          skill_stat="",
                          rank_progression="",
                          category_progression="0 • 0 • 0 • 0 • 0")
    rid = _seed_race_with_progressions(
        "dwarves_test_pp",
        body="0 • 7 • 4 • 2 • 1",
        chan="0 • 6 • 5 • 4 • 3",
        ess="0 • 3 • 2 • 1 • 1",
        ment="0 • 3 • 2 • 1 • 1",
    )
    cid = _create_character_at_fighter(client)
    _assign_race(cid, rid)

    body = client.get(f"/api/v1/characters/{cid}/skill-allocator").json()
    by_cat = {(c["group_name"], c["category_name"]): c for c in body["categories"]}
    pp_dev = by_cat.get(("Concepts", "Concepts • Power Point Development"))
    assert pp_dev is not None
    # ess_pp_prog "0•3•2•1•1" with rank-0 cell stripped -> "3 • 2 • 1 • 1",
    # placed on the CATEGORY (where the cost / +/- buttons live).
    assert pp_dev["category_progression"] == "3 • 2 • 1 • 1"
    # Skill row is a passthrough — no double-count when ranks sum.
    assert pp_dev["skill_progression"] == "0 • 0 • 0 • 0 • 0"


def test_pp_dev_progression_hybrid_takes_per_rank_min(client) -> None:
    """Channeling + Mentalism hybrid (e.g. Healer) on a dwarf-like race
    should land on the per-band MIN — Chan=6/5/4/3, Ment=3/2/1/1 -> 3/2/1/1."""
    _seed_minimal_fighter()
    _add_profession_cost("test_fighter", "Concepts", "Power Point Development", "4")
    _assign_profession_realm("test_fighter", "Channeling", "Mentalism")
    _seed_skill_category("Concepts", "Power Point Development",
                          stat_bonuses="Realm stat",
                          skills_list="Power Point Development",
                          rank_progression="",
                          category_progression="0 • 0 • 0 • 0 • 0")
    rid = _seed_race_with_progressions(
        "dwarves_hybrid_pp",
        body="0 • 7 • 4 • 2 • 1",
        chan="0 • 6 • 5 • 4 • 3",
        ess="0 • 6 • 5 • 4 • 3",
        ment="0 • 3 • 2 • 1 • 1",
    )
    cid = _create_character_at_fighter(client)
    _assign_race(cid, rid)

    body = client.get(f"/api/v1/characters/{cid}/skill-allocator").json()
    by_cat = {(c["group_name"], c["category_name"]): c for c in body["categories"]}
    pp_dev = by_cat[("Concepts", "Concepts • Power Point Development")]
    # After rank-0 strip: Chan=[6,5,4,3], Ment=[3,2,1,1]. Per-band min
    # -> "3 • 2 • 1 • 1", placed on the CATEGORY.
    assert pp_dev["category_progression"] == "3 • 2 • 1 • 1"


def test_body_dev_progression_uses_culture_when_umbrella_race(client) -> None:
    """Umbrella races (Common Men, Mixed Men) defer to the picked
    sub-culture. A character with race=Common Men + culture=High Men
    should pick up High-Men's body_dev_prog, not Common Men's."""
    _seed_minimal_fighter()
    _add_profession_cost("test_fighter", "Concepts", "Body Development", "2/5")
    _seed_skill_category("Concepts", "Body Development",
                          stat_bonuses="Co/SD/Co",
                          skills_list="BODY DEVELOPMENT",
                          skill_stat="Co",
                          rank_progression="",
                          category_progression="0 • 0 • 0 • 0 • 0")
    umbrella_rid = _seed_race_with_progressions(
        "common_men_test",
        body="0 • 6 • 4 • 2 • 1",        # Common Men
        chan="0 • 6 • 5 • 4 • 3",
        ess="0 • 6 • 5 • 4 • 3",
        ment="0 • 7 • 6 • 5 • 4",
    )
    _seed_race_with_progressions(
        "high_men_test",
        body="0 • 7 • 5 • 3 • 1",        # High Men — distinctly stronger
        chan="0 • 6 • 5 • 4 • 3",
        ess="0 • 6 • 5 • 4 • 3",
        ment="0 • 7 • 6 • 5 • 4",
    )
    cid = _create_character_at_fighter(client)
    _assign_race(cid, umbrella_rid, culture_slug="high_men_test")

    body = client.get(f"/api/v1/characters/{cid}/skill-allocator").json()
    by_cat = {(c["group_name"], c["category_name"]): c for c in body["categories"]}
    body_dev = by_cat[("Concepts", "Concepts • Body Development")]
    # High Men progression wins through culture_slug.
    # After rank-0 strip: "0 • 7 • 5 • 3 • 1" -> "7 • 5 • 3 • 1", placed
    # on the CATEGORY.
    assert body_dev["category_progression"] == "7 • 5 • 3 • 1"


def test_body_dev_skill_bonus_with_ranks(client) -> None:
    """3 ranks of Body Dev on a 0•7•4•2•1 race gives 21 — whether the
    ranks live on the category, the skill, or split between them. The
    server SUMS them and applies the race progression once on the
    category total; the skill row cascades from that."""
    from web.db import connect_rw

    _seed_minimal_fighter()
    _add_profession_cost("test_fighter", "Concepts", "Body Development", "2/5")
    _seed_skill_category("Concepts", "Body Development",
                          stat_bonuses="Co/SD/Co",
                          skills_list="BODY DEVELOPMENT",
                          skill_stat="Co",
                          rank_progression="",
                          category_progression="0 • 0 • 0 • 0 • 0")
    rid = _seed_race_with_progressions(
        "dwarves_with_ranks",
        body="0 • 7 • 4 • 2 • 1",
        chan="0 • 6 • 5 • 4 • 3",
        ess="0 • 3 • 2 • 1 • 1",
        ment="0 • 3 • 2 • 1 • 1",
    )
    cid = _create_character_at_fighter(client)
    _assign_race(cid, rid)
    # Adolescence lands ranks on the SKILL (kind='skill'). The server's
    # rank-summing for Body Dev / PP Dev folds those into the category's
    # rank_b computation, so the bonus shows up on the category total.
    with connect_rw() as conn:
        conn.execute(
            "INSERT INTO character_skill "
            "(character_id, skill, kind, rank, source) "
            "VALUES (?, 'BODY DEVELOPMENT', 'skill', 3, 'adolescence')",
            (cid,),
        )
        conn.commit()

    body = client.get(f"/api/v1/characters/{cid}/skill-allocator").json()
    by_cat = {(c["group_name"], c["category_name"]): c for c in body["categories"]}
    body_dev = by_cat[("Concepts", "Concepts • Body Development")]
    # 3 skill ranks summed into effective_cat_ranks=3, race prog at first
    # band gives 3 * 7 = 21. Category total: 21.
    assert body_dev["total_bonus"] == 21
    # Skill row cascades from cat_total; sk_rank_b is 0 (passthrough),
    # so sk_total == cat_total == 21.
    sk = next(s for s in body_dev["skills"] if s["skill_name"] == "BODY DEVELOPMENT")
    assert sk["current_ranks"] == 3
    assert sk["total_bonus"] == 21


def test_body_dev_progression_falls_through_when_unraced(client) -> None:
    """No race set -> catalog's progression is used as-is (placeholder
    or otherwise). We don't want the helper to invent a progression
    from thin air for an unraced character."""
    _seed_minimal_fighter()
    _add_profession_cost("test_fighter", "Concepts", "Body Development", "2/5")
    _seed_skill_category("Concepts", "Body Development",
                          stat_bonuses="Co/SD/Co",
                          skills_list="BODY DEVELOPMENT",
                          skill_stat="Co",
                          rank_progression="",
                          category_progression="0 • 0 • 0 • 0 • 0")
    cid = _create_character_at_fighter(client)
    # No _assign_race call.
    body = client.get(f"/api/v1/characters/{cid}/skill-allocator").json()
    by_cat = {(c["group_name"], c["category_name"]): c for c in body["categories"]}
    body_dev = by_cat[("Concepts", "Concepts • Body Development")]
    # Skill progression stays at the catalog default (empty -> Standard
    # in the dispatcher), category at the placeholder. Both are
    # explicitly NOT overridden when there's no race to source from.
    assert body_dev["skill_progression"] == ""
    assert body_dev["category_progression"] == "0 • 0 • 0 • 0 • 0"


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
