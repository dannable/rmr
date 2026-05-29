"""Tests for the ERA-driven spell-list re-import.

Covers:
  * parse_spell_list_file picks up @source and the new @category values
  * the spell_list migration recreates the table with the new shape
  * the schema accepts inserts with all six legal category values plus
    every well-known source tag
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# parse_spell_list_file
# ---------------------------------------------------------------------------

def _write(tmp_path: Path, body: str) -> Path:
    """Drop a tiny spell-list .txt and return its path."""
    p = tmp_path / "scratch.txt"
    p.write_text(body, encoding="utf-8")
    return p


def test_parse_spell_list_file_extracts_source(tmp_path: Path) -> None:
    """@source survives the parse and lands in meta — the loader uses
    it to populate spell_list.source."""
    from load import parse_spell_list_file

    body = (
        "@source:    channeling_companion\n"
        "@realm:     Channeling\n"
        "@name:      Test List\n"
        "@category:  Base\n"
        "@class:     Mythic\n"
        " 1 | First Spell | caster | C | self | E\n"
    )
    out = parse_spell_list_file(_write(tmp_path, body))
    assert out["meta"]["source"] == "channeling_companion"
    assert out["meta"]["realm"] == "Channeling"
    assert out["meta"]["name"] == "Test List"
    assert out["meta"]["category"] == "Base"
    assert out["meta"]["class"] == "Mythic"
    assert len(out["spells"]) == 1
    assert out["spells"][0][1] == "First Spell"


def test_parse_spell_list_file_omits_source_defaults_in_loader(tmp_path: Path) -> None:
    """A list without @source parses fine (meta key absent); the loader
    then falls back to the spell_law default. This is the legacy-format
    safety net — old files without @source continue to work."""
    from load import parse_spell_list_file

    body = (
        "@realm:     Channeling\n"
        "@name:      Legacy List\n"
        "@category:  Open\n"
        " 1 | A Spell | caster | - | self | I\n"
    )
    out = parse_spell_list_file(_write(tmp_path, body))
    assert "source" not in out["meta"]


# ---------------------------------------------------------------------------
# spell_list migration
# ---------------------------------------------------------------------------

def _make_old_shape_db() -> sqlite3.Connection:
    """Build an in-memory DB in the pre-migration shape and seed one row."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE spell_realm (
            realm_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT    NOT NULL UNIQUE
        );
        CREATE TABLE spell_class (
            class_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT    NOT NULL UNIQUE,
            realm_id  INTEGER NOT NULL REFERENCES spell_realm(realm_id)
        );
        CREATE TABLE spell_list (
            list_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            realm_id     INTEGER NOT NULL REFERENCES spell_realm(realm_id) ON DELETE CASCADE,
            name         TEXT    NOT NULL,
            list_number  TEXT,
            category     TEXT    NOT NULL CHECK (category IN ('Open', 'Closed', 'Base')),
            UNIQUE (realm_id, name)
        );
        CREATE TABLE class_spell_list (
            class_id  INTEGER,
            list_id   INTEGER REFERENCES spell_list(list_id) ON DELETE CASCADE
        );
        CREATE TABLE spell (
            spell_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            list_id   INTEGER REFERENCES spell_list(list_id) ON DELETE CASCADE
        );
    """)
    conn.execute("INSERT INTO spell_realm (name) VALUES ('Channeling')")
    conn.execute(
        "INSERT INTO spell_list (realm_id, name, category) VALUES (1, 'Old List', 'Base')"
    )
    conn.commit()
    return conn


def test_migration_recreates_spell_list_with_source_column() -> None:
    """The migration adds the source column and broadens the CHECK to
    accept the new category values. Old data is wiped (reference data,
    repopulated from .txt on the loader's reload pass)."""
    from load import _migrate_spell_list_add_source_and_categories

    conn = _make_old_shape_db()
    _migrate_spell_list_add_source_and_categories(conn)

    # New shape:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(spell_list)").fetchall()}
    assert "source" in cols
    # Old row was dropped.
    assert conn.execute("SELECT COUNT(*) FROM spell_list").fetchone()[0] == 0


def test_migration_accepts_new_category_values_after_migration() -> None:
    """All six legal categories must insert without raising. Pre-migration
    only the first three would survive the CHECK."""
    from load import _migrate_spell_list_add_source_and_categories

    conn = _make_old_shape_db()
    _migrate_spell_list_add_source_and_categories(conn)

    for cat in ("Open", "Closed", "Base", "Evil",
                "Training Package", "Divine Alchemy"):
        conn.execute(
            "INSERT INTO spell_list (realm_id, name, category, source) "
            "VALUES (1, ?, ?, 'spell_law')",
            (f"List-{cat}", cat),
        )
    # All six accepted.
    n = conn.execute("SELECT COUNT(*) FROM spell_list").fetchone()[0]
    assert n == 6


def test_migration_rejects_unknown_category_after_migration() -> None:
    """A typo shouldn't slip past — the CHECK is still enforced."""
    from load import _migrate_spell_list_add_source_and_categories

    conn = _make_old_shape_db()
    _migrate_spell_list_add_source_and_categories(conn)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO spell_list (realm_id, name, category, source) "
            "VALUES (1, 'Bad', 'Misspelled', 'spell_law')"
        )


def test_migration_is_idempotent() -> None:
    """A second call on an already-migrated DB is a no-op (detection
    short-circuits on the new CHECK signature)."""
    from load import _migrate_spell_list_add_source_and_categories

    conn = _make_old_shape_db()
    _migrate_spell_list_add_source_and_categories(conn)
    # Seed a row in the new shape, then re-run — it should NOT be wiped.
    conn.execute(
        "INSERT INTO spell_list (realm_id, name, category, source) "
        "VALUES (1, 'Survivor', 'Evil', 'channeling_companion')"
    )
    _migrate_spell_list_add_source_and_categories(conn)
    survivor = conn.execute(
        "SELECT name, source FROM spell_list WHERE name = 'Survivor'"
    ).fetchone()
    assert survivor == ("Survivor", "channeling_companion")


def test_migration_same_name_different_source_coexists() -> None:
    """The UNIQUE constraint is now (realm, name, source), so two books
    introducing the same list-name on the same realm both insert."""
    from load import _migrate_spell_list_add_source_and_categories

    conn = _make_old_shape_db()
    _migrate_spell_list_add_source_and_categories(conn)

    conn.execute(
        "INSERT INTO spell_list (realm_id, name, category, source) "
        "VALUES (1, 'Animal Mastery', 'Base', 'spell_law')"
    )
    # Same name + realm, different source → no UNIQUE violation.
    conn.execute(
        "INSERT INTO spell_list (realm_id, name, category, source) "
        "VALUES (1, 'Animal Mastery', 'Base', 'channeling_companion')"
    )
    n = conn.execute(
        "SELECT COUNT(*) FROM spell_list WHERE name = 'Animal Mastery'"
    ).fetchone()[0]
    assert n == 2
