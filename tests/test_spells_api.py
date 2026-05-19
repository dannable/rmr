"""Tests for the spell explorer endpoints (web/api/spells.py) and the
underlying serializer (core/spell.py::write_spell_list_file).

The pytest schema-build fixture creates an empty DB — there's no spell
data loaded — so each test that needs spells seeds them via direct SQL.
Keeping the seeds inline (rather than running load.py) makes failures
debuggable: you see exactly what's in the table.

PUT endpoint tests monkeypatch web.api.spells._PROJECT_ROOT so the
write-back .txt files land in tmp_path instead of the real data dir.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# seeding helpers
# ---------------------------------------------------------------------------

def _seed_minimal_list(conn: sqlite3.Connection) -> dict:
    """Insert one realm, one class, one list, two spells. Return the IDs.

    The list is Channeling / Open so the .txt write-back path doesn't emit
    an @class line (keeps assertions simple — Base lists carry an extra
    owning-class lookup).
    """
    conn.execute("DELETE FROM spell")
    conn.execute("DELETE FROM class_spell_list")
    conn.execute("DELETE FROM spell_list")
    conn.execute("DELETE FROM spell_class")
    conn.execute("DELETE FROM spell_realm")

    realm_id = conn.execute(
        "INSERT INTO spell_realm (name) VALUES ('Channeling') RETURNING realm_id"
    ).fetchone()["realm_id"]

    class_id = conn.execute(
        "INSERT INTO spell_class (realm_id, name) VALUES (?, 'Cleric') RETURNING class_id",
        (realm_id,),
    ).fetchone()["class_id"]

    list_id = conn.execute(
        """INSERT INTO spell_list (realm_id, name, list_number, category)
           VALUES (?, 'Test Wall Law', '2.9.9', 'Open')
           RETURNING list_id""",
        (realm_id,),
    ).fetchone()["list_id"]

    conn.execute(
        "INSERT INTO class_spell_list (class_id, list_id) VALUES (?, ?)",
        (class_id, list_id),
    )

    # Two spells. Level 1 is plain; Level 2 is starred to confirm the flag
    # round-trips and surfaces in the .txt as " *".
    conn.execute(
        """INSERT INTO spell (list_id, level, name, area_effect, duration,
                              range_str, spell_type, starred, description)
           VALUES (?, 1, 'Light Wall', '10''x10''x1''', 'C', '50''', 'E', 0,
                   'Creates a wall of light.')""",
        (list_id,),
    )
    conn.execute(
        """INSERT INTO spell (list_id, level, name, area_effect, duration,
                              range_str, spell_type, starred, description)
           VALUES (?, 2, 'Stone Wall', '10''x10''x6"', '1 hour', '100''', 'F', 1,
                   'Creates a wall of stone.\n\nIf damaged, crumbles.')""",
        (list_id,),
    )
    conn.commit()

    return {"realm_id": realm_id, "class_id": class_id, "list_id": list_id}


@pytest.fixture
def seeded_list(fake_user) -> dict:
    """fake_user pulls in fresh_db, so app_user is clean; we then seed spells.

    The schema's spell tables aren't touched by fresh_db (it only clears
    character + app_user), so prior tests' spell data could leak. We delete
    + reinsert defensively at the top of _seed_minimal_list.
    """
    from web.db import connect_rw
    with connect_rw() as conn:
        ids = _seed_minimal_list(conn)
    return ids


# ---------------------------------------------------------------------------
# unit tests — write_spell_list_file serializer
# ---------------------------------------------------------------------------

def test_serializer_writes_canonical_format(seeded_list, tmp_path: Path) -> None:
    """Round-trip the seeded list through write_spell_list_file and inspect."""
    from core.spell import write_spell_list_file
    from web.db import connect_rw

    with connect_rw() as conn:
        out_path = write_spell_list_file(
            conn, list_id=seeded_list["list_id"], project_root=tmp_path,
        )

    # Path layout: <root>/data/spell_lists/<realm>/<slug>.txt
    assert out_path == tmp_path / "data" / "spell_lists" / "channeling" / "test_wall_law.txt"
    body = out_path.read_text(encoding="utf-8")

    # Header metadata
    assert "# Spell List 2.9.9 — Test Wall Law (Open)" in body
    assert "@realm:    Channeling" in body
    assert "@name:     Test Wall Law" in body
    assert "@number:   2.9.9" in body
    assert "@category: Open" in body
    # Open lists must not carry an @class line.
    assert "@class:" not in body

    # Chart rows
    assert " 1 | Light Wall | 10'x10'x1' | C | 50' | E" in body
    # Starred row should render with " *" after the name.
    assert " 2 | Stone Wall * | 10'x10'x6\" | 1 hour | 100' | F" in body

    # Description blocks
    assert "@@ 1\nCreates a wall of light." in body
    assert "@@ 2\nCreates a wall of stone." in body
    # Multi-paragraph descriptions preserve internal blank lines.
    assert "If damaged, crumbles." in body


def test_serializer_atomic_replace(seeded_list, tmp_path: Path) -> None:
    """If the rename succeeds, no .tmp file should be left behind."""
    from core.spell import write_spell_list_file
    from web.db import connect_rw

    with connect_rw() as conn:
        out = write_spell_list_file(
            conn, list_id=seeded_list["list_id"], project_root=tmp_path,
        )

    leftovers = list(out.parent.glob("*.tmp"))
    assert leftovers == []


def test_serializer_base_list_writes_class_line(fake_user, tmp_path: Path) -> None:
    """Base lists need an @class line naming the owning class."""
    from core.spell import write_spell_list_file
    from web.db import connect_rw

    with connect_rw() as conn:
        ids = _seed_minimal_list(conn)
        # Flip the seeded list to Base so the serializer's class-lookup path runs.
        conn.execute(
            "UPDATE spell_list SET category = 'Base' WHERE list_id = ?",
            (ids["list_id"],),
        )
        conn.commit()
        out_path = write_spell_list_file(
            conn, list_id=ids["list_id"], project_root=tmp_path,
        )

    body = out_path.read_text(encoding="utf-8")
    assert "@category: Base" in body
    assert "@class:    Cleric" in body


# ---------------------------------------------------------------------------
# API tests — reads
# ---------------------------------------------------------------------------

def test_get_classes(client, seeded_list) -> None:
    r = client.get("/api/v1/spells/classes")
    assert r.status_code == 200
    body = r.json()
    assert any(c["class_name"] == "Cleric" and c["realm_name"] == "Channeling" for c in body)


def test_get_class_lists(client, seeded_list) -> None:
    r = client.get("/api/v1/spells/classes/Cleric/lists")
    assert r.status_code == 200
    body = r.json()
    assert any(l["name"] == "Test Wall Law" and l["category"] == "Open" for l in body)


def test_get_class_lists_unknown_returns_empty(client, seeded_list) -> None:
    # No class called "Nobody" — endpoint returns [] (not 404, by design).
    r = client.get("/api/v1/spells/classes/Nobody/lists")
    assert r.status_code == 200
    assert r.json() == []


def test_get_lists(client, seeded_list) -> None:
    r = client.get("/api/v1/spells/lists")
    assert r.status_code == 200
    body = r.json()
    assert any(l["list_id"] == seeded_list["list_id"] for l in body)


def test_get_list_detail(client, seeded_list) -> None:
    r = client.get(f"/api/v1/spells/lists/{seeded_list['list_id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Test Wall Law"
    assert body["classes"] == ["Cleric"]


def test_get_list_detail_unknown_returns_404(client, seeded_list) -> None:
    r = client.get("/api/v1/spells/lists/999999")
    assert r.status_code == 404


def test_get_list_spells(client, seeded_list) -> None:
    r = client.get(f"/api/v1/spells/lists/{seeded_list['list_id']}/spells")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    levels = sorted(s["level"] for s in body)
    assert levels == [1, 2]
    # starred boolean survives the JSON serialisation (int 0/1 → bool).
    by_level = {s["level"]: s for s in body}
    assert by_level[1]["starred"] is False
    assert by_level[2]["starred"] is True


def test_get_one_spell(client, seeded_list) -> None:
    list_id = seeded_list["list_id"]
    r = client.get(f"/api/v1/spells/lists/{list_id}/spells/1")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Light Wall"
    assert body["description"] == "Creates a wall of light."
    # Pre-edit, audit fields are NULL.
    assert body["updated_at"] is None
    assert body["updated_by_user_id"] is None


def test_get_one_spell_unknown_returns_404(client, seeded_list) -> None:
    list_id = seeded_list["list_id"]
    r = client.get(f"/api/v1/spells/lists/{list_id}/spells/9")
    assert r.status_code == 404


def test_search_by_name(client, seeded_list) -> None:
    r = client.get("/api/v1/spells/search?q=wall")
    assert r.status_code == 200
    body = r.json()
    names = {h["name"] for h in body}
    assert names == {"Light Wall", "Stone Wall"}


def test_search_requires_q(client, seeded_list) -> None:
    r = client.get("/api/v1/spells/search")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# API tests — PUT (edit + write-back)
# ---------------------------------------------------------------------------

def test_put_updates_db_and_rewrites_file(
    client, seeded_list, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The PUT handler should update the row, stamp audit fields, and atomically
    rewrite the .txt file so it reflects the new state."""
    import web.api.spells as spells_mod
    monkeypatch.setattr(spells_mod, "_PROJECT_ROOT", tmp_path)

    list_id = seeded_list["list_id"]
    r = client.put(
        f"/api/v1/spells/lists/{list_id}/spells/1",
        json={"name": "Brilliant Wall", "duration": "C-edited"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Brilliant Wall"
    assert body["duration"] == "C-edited"
    # Audit fields populated.
    assert body["updated_at"] is not None
    assert body["updated_by_user_id"] > 0

    # DB row really did change.
    from web.db import connect_rw
    with connect_rw() as conn:
        row = conn.execute(
            "SELECT name, duration FROM spell WHERE list_id = ? AND level = 1",
            (list_id,),
        ).fetchone()
    assert row["name"] == "Brilliant Wall"
    assert row["duration"] == "C-edited"

    # File rewritten under tmp_path with the new state.
    out_file = tmp_path / "data" / "spell_lists" / "channeling" / "test_wall_law.txt"
    assert out_file.is_file()
    file_body = out_file.read_text(encoding="utf-8")
    assert "Brilliant Wall" in file_body
    assert "C-edited" in file_body
    # And the old name is gone.
    assert "Light Wall" not in file_body


def test_put_partial_update_leaves_other_fields(
    client, seeded_list, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import web.api.spells as spells_mod
    monkeypatch.setattr(spells_mod, "_PROJECT_ROOT", tmp_path)

    list_id = seeded_list["list_id"]
    # Only change starred; everything else should retain the seeded values.
    r = client.put(
        f"/api/v1/spells/lists/{list_id}/spells/1",
        json={"starred": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["starred"] is True
    assert body["name"] == "Light Wall"
    assert body["duration"] == "C"
    assert body["area_effect"] == "10'x10'x1'"


def test_put_unknown_spell_returns_404(
    client, seeded_list, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import web.api.spells as spells_mod
    monkeypatch.setattr(spells_mod, "_PROJECT_ROOT", tmp_path)

    list_id = seeded_list["list_id"]
    r = client.put(
        f"/api/v1/spells/lists/{list_id}/spells/99",
        json={"name": "Nope"},
    )
    assert r.status_code == 404


def test_put_unknown_keys_silently_dropped(
    client, seeded_list, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown keys outside EDITABLE_SPELL_FIELDS are stripped before UPDATE.

    Pydantic with the default model_config drops extras silently rather than
    422 — `level` and `list_id` are intentionally not in the schema, so
    they're never editable.
    """
    import web.api.spells as spells_mod
    monkeypatch.setattr(spells_mod, "_PROJECT_ROOT", tmp_path)

    list_id = seeded_list["list_id"]
    r = client.put(
        f"/api/v1/spells/lists/{list_id}/spells/1",
        json={"name": "Renamed", "level": 99, "list_id": 99},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Renamed"
    # level + list_id of the path params are unaffected.
    assert body["level"] == 1
    assert body["list_id"] == list_id


# ---------------------------------------------------------------------------
# auth gating
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/v1/spells/classes", None),
    ("GET", "/api/v1/spells/classes/Cleric/lists", None),
    ("GET", "/api/v1/spells/lists", None),
    ("GET", "/api/v1/spells/lists/1", None),
    ("GET", "/api/v1/spells/lists/1/spells", None),
    ("GET", "/api/v1/spells/lists/1/spells/1", None),
    ("PUT", "/api/v1/spells/lists/1/spells/1", {"name": "x"}),
    ("GET", "/api/v1/spells/search?q=test", None),
])
def test_endpoints_require_auth(anon_client, method: str, path: str, body) -> None:
    kwargs = {"json": body} if body is not None else {}
    r = anon_client.request(method, path, **kwargs)
    assert r.status_code == 401, f"{method} {path} expected 401, got {r.status_code}"
