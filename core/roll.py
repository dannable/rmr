"""Open-ended d100 helpers for Rolemaster attack rolls."""

from __future__ import annotations

import random


def d100() -> int:
    return random.randint(1, 100)


def open_ended_d100() -> tuple[int, list[int], str | None]:
    """Standard RM open-ended d100.

    Returns (final_value, individual_rolls, direction_or_None).
    - First roll 96-100 → "high": keep rolling and adding while rolls ≥ 96.
    - First roll 01-05  → "low":  keep rolling and subtracting while rolls ≥ 96.
    - Otherwise         → single roll, direction None.
    """
    rolls = [d100()]
    if rolls[0] >= 96:
        while True:
            r = d100()
            rolls.append(r)
            if r < 96:
                break
        return sum(rolls), rolls, "high"
    if rolls[0] <= 5:
        while True:
            r = d100()
            rolls.append(r)
            if r < 96:
                break
        return rolls[0] - sum(rolls[1:]), rolls, "low"
    return rolls[0], rolls, None


def format_rolls(rolls: list[int], direction: str | None) -> str:
    """Render the dice for display: '82' or '99 + 47' or '3 - 12'."""
    if direction == "low":
        return f"{rolls[0]}" + "".join(f" - {r}" for r in rolls[1:])
    return " + ".join(str(r) for r in rolls)
