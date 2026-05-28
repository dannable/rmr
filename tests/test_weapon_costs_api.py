"""Tests for the weapon-cost reassignment sub-resource.

RMSS Character Law §6.2 — a profession comes with a multiset of weapon
costs (e.g. Fighter: {1/5, 2/5, 2/7, 2/7, 2/7, 5, 5}) and the player
swaps which weapon CATEGORY gets which cost at character creation.

GET /api/v1/characters/{id}/weapon-costs
PUT /api/v1/characters/{id}/weapon-costs
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

# Fighter-ish multiset: 1/5 + 2/5 + 2/7×3 + 5×2. Each category gets a
# distinct cost in the default assignment; the test mutates these.
_DEFAULT_FIGHTER_WEAPON_COSTS = [
    ("Weapon", "1-H Concussion",     "1/5"),
    ("Weapon", "1-H Edged",          "2/5"),
    ("Weapon", "2-Handed",           "2/7"),
    ("Weapon", "Missile",            "2/7"),
    ("Weapon", "Missile Artillery",  "2/7"),
    ("Weapon", "Pole Arms",          "5"),
    ("Weapon", "Thrown",             "5"),
]


def _seed_profession_with_weapons(slug: str = "test_fighter") -> int:
    """Insert a minimal profession plus the Fighter weapon-cost pool."""
    from web.db import connect_rw
    with connect_rw() as conn:
        existing = conn.execute(
            "SELECT profession_id FROM profession WHERE slug = ?", (slug,),
        ).fetchone()
        if existing:
            conn.execute("DELETE FROM profession WHERE slug = ?", (slug,))
        cur = conn.execute(
            "INSERT INTO profession (slug, name, description, source) "
            "VALUES (?, ?, ?, ?) RETURNING profession_id",
            (slug, "Test Fighter", "Cleaves things.", "character_law"),
        )
        pid = cur.fetchone()[0]
        for g, c, cost in _DEFAULT_FIGHTER_WEAPON_COSTS:
            conn.execute(
                "INSERT INTO profession_category_cost "
                "(profession_id, group_name, category_name, cost) "
                "VALUES (?, ?, ?, ?)", (pid, g, c, cost),
            )
        conn.commit()
    return pid


def _create_character_with_profession(client, prof_slug: str = "test_fighter") -> int:
    r = client.post("/api/v1/characters", json={"name": "Weapon Tester"})
    assert r.status_code == 201
    cid = r.json()["character_id"]
    r = client.put(f"/api/v1/characters/{cid}/profession", json={"slug": prof_slug})
    assert r.status_code == 200
    return cid


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------

def test_get_weapon_costs_no_profession_returns_empty(client) -> None:
    """Unprofessioned character: empty rows + empty pool, no 404."""
    r = client.post("/api/v1/characters", json={"name": "No-Prof"})
    cid = r.json()["character_id"]
    r = client.get(f"/api/v1/characters/{cid}/weapon-costs")
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == []
    assert body["pool"] == []
    assert body["profession_slug"] is None


def test_get_weapon_costs_default_uses_profession_costs(client) -> None:
    """Fighter with no overrides — defaults flow through, is_override False."""
    _seed_profession_with_weapons("test_fighter")
    cid = _create_character_with_profession(client, "test_fighter")
    body = client.get(f"/api/v1/characters/{cid}/weapon-costs").json()
    assert body["profession_slug"] == "test_fighter"
    by_cat = {r["weapon_category"]: r for r in body["rows"]}
    assert by_cat["1-H Concussion"]["cost"] == "1/5"
    assert by_cat["Pole Arms"]["cost"] == "5"
    assert all(not r["is_override"] for r in body["rows"])
    # Pool reflects the multiset, sorted cheap-first (1/5, 2/5, 2/7×3, 5×2).
    assert body["pool"] == ["1/5", "2/5", "2/7", "2/7", "2/7", "5", "5"]


def test_get_weapon_costs_rank_cap_derived_from_cost(client) -> None:
    """'1/5' → 2 ranks/level; '5' → 1 rank/level — sanity check the derivation."""
    _seed_profession_with_weapons("test_fighter")
    cid = _create_character_with_profession(client, "test_fighter")
    by_cat = {r["weapon_category"]: r
              for r in client.get(f"/api/v1/characters/{cid}/weapon-costs").json()["rows"]}
    assert by_cat["1-H Concussion"]["rank_cap_per_level"] == 2
    assert by_cat["Pole Arms"]["rank_cap_per_level"] == 1
    assert by_cat["2-Handed"]["rank_cap_per_level"] == 2


# ---------------------------------------------------------------------------
# PUT (reassign)
# ---------------------------------------------------------------------------

def _swap(assignments: list[tuple[str, str]]) -> dict:
    """Build a PUT body from a list of (category, cost) tuples."""
    return {"assignments": [{"weapon_category": c, "cost": k}
                             for c, k in assignments]}


def test_put_swap_1H_with_2H_changes_effective_costs(client) -> None:
    """The user's example: Fighter moves 1/5 from 1-H Concussion to 2-Handed
    and the 2/7 the other way. End state: 2-Handed=1/5 (cheap!), 1-H Concussion=2/7."""
    _seed_profession_with_weapons("test_fighter")
    cid = _create_character_with_profession(client, "test_fighter")

    swapped = [
        ("1-H Concussion",    "2/7"),  # was 1/5
        ("1-H Edged",         "2/5"),  # unchanged
        ("2-Handed",          "1/5"),  # was 2/7
        ("Missile",           "2/7"),  # unchanged
        ("Missile Artillery", "2/7"),  # unchanged
        ("Pole Arms",         "5"),    # unchanged
        ("Thrown",            "5"),    # unchanged
    ]
    r = client.put(f"/api/v1/characters/{cid}/weapon-costs", json=_swap(swapped))
    assert r.status_code == 200
    by_cat = {r["weapon_category"]: r for r in r.json()["rows"]}
    assert by_cat["2-Handed"]["cost"] == "1/5"
    assert by_cat["1-H Concussion"]["cost"] == "2/7"
    assert by_cat["2-Handed"]["is_override"] is True
    assert by_cat["1-H Concussion"]["is_override"] is True
    # The swapped pair changed; 1-H Edged stayed default.
    assert by_cat["1-H Edged"]["is_override"] is False


def test_put_persists_across_get(client) -> None:
    _seed_profession_with_weapons("test_fighter")
    cid = _create_character_with_profession(client, "test_fighter")
    swapped = [
        ("1-H Concussion",    "5"),
        ("1-H Edged",         "2/5"),
        ("2-Handed",          "2/7"),
        ("Missile",           "2/7"),
        ("Missile Artillery", "2/7"),
        ("Pole Arms",         "1/5"),
        ("Thrown",            "5"),
    ]
    client.put(f"/api/v1/characters/{cid}/weapon-costs", json=_swap(swapped))
    by_cat = {r["weapon_category"]: r
              for r in client.get(f"/api/v1/characters/{cid}/weapon-costs").json()["rows"]}
    assert by_cat["Pole Arms"]["cost"] == "1/5"


def test_put_empty_assignments_clears_overrides(client) -> None:
    """Sending an empty list reverts to profession defaults."""
    _seed_profession_with_weapons("test_fighter")
    cid = _create_character_with_profession(client, "test_fighter")
    # Apply a swap, then clear.
    client.put(f"/api/v1/characters/{cid}/weapon-costs", json=_swap([
        ("1-H Concussion",    "2/7"),  ("1-H Edged",         "2/5"),
        ("2-Handed",          "1/5"),  ("Missile",           "2/7"),
        ("Missile Artillery", "2/7"),  ("Pole Arms",         "5"),
        ("Thrown",            "5"),
    ]))
    r = client.put(f"/api/v1/characters/{cid}/weapon-costs", json={"assignments": []})
    assert r.status_code == 200
    body = r.json()
    by_cat = {r["weapon_category"]: r for r in body["rows"]}
    # Back to defaults — no overrides.
    assert by_cat["1-H Concussion"]["cost"] == "1/5"
    assert all(not r["is_override"] for r in body["rows"])


def test_put_rejects_wrong_multiset(client) -> None:
    """Sending 7 costs that don't match the multiset → 422 with a useful detail."""
    _seed_profession_with_weapons("test_fighter")
    cid = _create_character_with_profession(client, "test_fighter")
    # Three 5s instead of two — wrong multiset.
    bad = [
        ("1-H Concussion",    "1/5"),
        ("1-H Edged",         "2/5"),
        ("2-Handed",          "2/7"),
        ("Missile",           "2/7"),
        ("Missile Artillery", "5"),    # was 2/7
        ("Pole Arms",         "5"),
        ("Thrown",            "5"),
    ]
    r = client.put(f"/api/v1/characters/{cid}/weapon-costs", json=_swap(bad))
    assert r.status_code == 422
    assert "multiset" in r.json()["detail"].lower()


def test_put_rejects_missing_category(client) -> None:
    """Partial assignment (only 6 categories) is rejected — all-or-nothing."""
    _seed_profession_with_weapons("test_fighter")
    cid = _create_character_with_profession(client, "test_fighter")
    partial = [
        ("1-H Concussion",    "1/5"),
        ("1-H Edged",         "2/5"),
        ("2-Handed",          "2/7"),
        ("Missile",           "2/7"),
        ("Missile Artillery", "2/7"),
        ("Pole Arms",         "5"),
        # Thrown missing on purpose.
    ]
    r = client.put(f"/api/v1/characters/{cid}/weapon-costs", json=_swap(partial))
    assert r.status_code == 422
    assert "missing" in r.json()["detail"].lower()


def test_put_rejects_unknown_category(client) -> None:
    """Including a weapon category the profession doesn't have → 422."""
    _seed_profession_with_weapons("test_fighter")
    cid = _create_character_with_profession(client, "test_fighter")
    bad = [
        ("1-H Concussion",    "1/5"),
        ("1-H Edged",         "2/5"),
        ("2-Handed",          "2/7"),
        ("Missile",           "2/7"),
        ("Missile Artillery", "2/7"),
        ("Pole Arms",         "5"),
        ("Underwater Basket Weaving", "5"),   # not a real category
    ]
    r = client.put(f"/api/v1/characters/{cid}/weapon-costs", json=_swap(bad))
    assert r.status_code == 422
    assert "unknown" in r.json()["detail"].lower()


def test_put_requires_profession(client) -> None:
    """Unprofessioned character: PUT 409s."""
    r = client.post("/api/v1/characters", json={"name": "No-Prof"})
    cid = r.json()["character_id"]
    r = client.put(f"/api/v1/characters/{cid}/weapon-costs", json={"assignments": []})
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# auth gating
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,body", [
    ("GET", None),
    ("PUT", {"assignments": []}),
])
def test_weapon_costs_require_auth(anon_client, method: str, body) -> None:
    kwargs = {"json": body} if body is not None else {}
    r = anon_client.request(method, "/api/v1/characters/1/weapon-costs", **kwargs)
    assert r.status_code == 401


def test_get_weapon_costs_404_for_other_users_character(client, other_user) -> None:
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
    r = client.get(f"/api/v1/characters/{their_id}/weapon-costs")
    assert r.status_code == 404
