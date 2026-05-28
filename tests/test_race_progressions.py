"""Unit tests for the per-race Body Development / Power Point Development
progression helpers in core/chargen/race.py.

These exercise the pure functions in isolation — no DB, no API. The
allocator-level integration test (tests/test_skill_allocator_api.py)
covers the end-to-end wiring."""

from __future__ import annotations

from core.chargen.race import body_dev_progression, pp_dev_progression


def _race(**fields) -> dict:
    """Minimal race-row dict for the helpers (they only read four keys)."""
    base = {
        "body_dev_prog": "",
        "chan_pp_prog":  "",
        "ess_pp_prog":   "",
        "ment_pp_prog":  "",
    }
    base.update(fields)
    return base


# ---------------------------------------------------------------------------
# body_dev_progression
# ---------------------------------------------------------------------------

def test_body_dev_progression_strips_rank_zero_cell() -> None:
    """Race files store T-2.2 column order (rank-0 + 4 bands). The
    helper strips the rank-0 cell so the existing dispatcher reads it
    as a 4-band string. Dwarves "0 • 7 • 4 • 2 • 1" -> "7 • 4 • 2 • 1"."""
    race = _race(body_dev_prog="0 • 7 • 4 • 2 • 1")  # Dwarves
    assert body_dev_progression(race) == "7 • 4 • 2 • 1"


def test_body_dev_progression_passes_through_when_already_4_bands() -> None:
    """Defensive: if upstream ever stores a 4-band string already, don't
    over-strip it."""
    race = _race(body_dev_prog="7 • 4 • 2 • 1")
    assert body_dev_progression(race) == "7 • 4 • 2 • 1"


def test_body_dev_progression_none_race_returns_empty() -> None:
    """No race -> empty string; caller falls through to Standard."""
    assert body_dev_progression(None) == ""


def test_body_dev_progression_blank_field_returns_empty() -> None:
    """Race row exists but the field is blank (unloaded data) -> empty."""
    assert body_dev_progression(_race(body_dev_prog="")) == ""


# ---------------------------------------------------------------------------
# pp_dev_progression — single realm
# ---------------------------------------------------------------------------

def test_pp_dev_progression_single_realm_essence() -> None:
    """Dwarves + Essence (Magician). Race file has 5 cells "0•3•2•1•1";
    the helper strips the rank-0 cell leaving the 4-band "3•2•1•1"."""
    race = _race(
        chan_pp_prog="0 • 6 • 5 • 4 • 3",
        ess_pp_prog="0 • 3 • 2 • 1 • 1",
        ment_pp_prog="0 • 3 • 2 • 1 • 1",
    )
    assert pp_dev_progression(race, ["Essence"]) == "3 • 2 • 1 • 1"


def test_pp_dev_progression_single_realm_channeling() -> None:
    race = _race(
        chan_pp_prog="0 • 6 • 5 • 4 • 3",
        ess_pp_prog="0 • 3 • 2 • 1 • 1",
    )
    assert pp_dev_progression(race, ["Channeling"]) == "6 • 5 • 4 • 3"


# ---------------------------------------------------------------------------
# pp_dev_progression — hybrid spellcasters
# ---------------------------------------------------------------------------

def test_pp_dev_progression_hybrid_takes_per_rank_min() -> None:
    """Dwarf Healer (Channeling + Mentalism). After rank-0 strip,
    Chan=6/5/4/3, Ment=3/2/1/1 — the hybrid lands on the per-band
    minimum, matching the RMSS convention that hybrids get the worse
    PP progression."""
    race = _race(
        chan_pp_prog="0 • 6 • 5 • 4 • 3",
        ment_pp_prog="0 • 3 • 2 • 1 • 1",
    )
    out = pp_dev_progression(race, ["Channeling", "Mentalism"])
    assert out == "3 • 2 • 1 • 1"


def test_pp_dev_progression_hybrid_equal_progressions_returns_them() -> None:
    """Common Men Sorcerer (Chan+Ess) — both realms are 6/5/4/3 after
    the rank-0 strip, so the min is the same string."""
    race = _race(
        chan_pp_prog="0 • 6 • 5 • 4 • 3",
        ess_pp_prog="0 • 6 • 5 • 4 • 3",
    )
    out = pp_dev_progression(race, ["Channeling", "Essence"])
    assert out == "6 • 5 • 4 • 3"


def test_pp_dev_progression_hybrid_does_not_crash_on_short_realm() -> None:
    """Defensive: a too-short progression (≤4 tokens) bypasses the rank-0
    strip (we can't tell which interpretation the source intended). The
    helper still has to produce something rather than crashing — the
    practical race files always carry 5 tokens, so this is purely
    defensive."""
    race = _race(
        chan_pp_prog="0 • 6",
        ess_pp_prog="0 • 5 • 4 • 3 • 2",
    )
    out = pp_dev_progression(race, ["Channeling", "Essence"])
    # Whatever the merged string is, it should be a parseable dotted
    # form that doesn't raise — the exact value isn't policy because
    # the input is malformed.
    assert " • " in out
    for cell in out.split(" • "):
        assert cell.strip().lstrip("-").isdigit()


# ---------------------------------------------------------------------------
# pp_dev_progression — degenerate inputs
# ---------------------------------------------------------------------------

def test_pp_dev_progression_none_race_returns_empty() -> None:
    assert pp_dev_progression(None, ["Essence"]) == ""


def test_pp_dev_progression_empty_realms_returns_empty() -> None:
    """Non-spellcasters (no realm assigned) fall through. The catalog's
    placeholder progression will yield 0 PP — which is the right answer
    for a Fighter."""
    race = _race(ess_pp_prog="0 • 6 • 5 • 4 • 3")
    assert pp_dev_progression(race, []) == ""


def test_pp_dev_progression_unknown_realm_skipped() -> None:
    """Unknown realm names are ignored. If every realm is unknown, the
    helper returns empty so the caller falls back to Standard."""
    race = _race(ess_pp_prog="0 • 6 • 5 • 4 • 3")
    assert pp_dev_progression(race, ["Arcane"]) == ""


def test_pp_dev_progression_mixed_unknown_and_known_realm() -> None:
    """Unknown realm gets dropped; known realm's column survives. Used
    if a hybrid profession ever pairs a real realm with something the
    helper hasn't been told about."""
    race = _race(
        chan_pp_prog="0 • 6 • 5 • 4 • 3",
        ess_pp_prog="0 • 3 • 2 • 1 • 1",
    )
    assert pp_dev_progression(race, ["Essence", "Arcane"]) == "3 • 2 • 1 • 1"


def test_pp_dev_progression_blank_realm_field_falls_through() -> None:
    """Race has the realm column blank — same as not being in that realm
    at all. Return empty (caller falls back)."""
    race = _race(chan_pp_prog="", ess_pp_prog="")
    assert pp_dev_progression(race, ["Channeling"]) == ""
