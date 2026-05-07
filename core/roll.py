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


def percentile_faces(value: int) -> tuple[int, int]:
    """Break a d100 result into its (tens, ones) faces on the 00-99 wheel.

    Mirrors a physical percentile-dice tray: the tens-die shows
    00, 10, 20, ..., 90 and the ones-die shows 0..9. A roll of 100 reads
    as the (00, 0) pair — both zeros.

        percentile_faces(78)  -> (70, 8)
        percentile_faces(1)   -> (0, 1)
        percentile_faces(50)  -> (50, 0)
        percentile_faces(100) -> (0, 0)
    """
    if value == 100:
        return 0, 0
    return (value // 10) * 10, value % 10
