"""Translate Rolemaster effect-code strings into readable English.

The chart key:
    ßπ  = must parry ß rounds        ß∏  = no parry for ß rounds
    ß∑  = stunned for ß rounds       ß∫  = bleed ß hits per round
    +NH = N extra hits               (-N) = foe has -N penalty
    (+N) = attacker gets +N next     —   = no mechanical effect

A few compound forms also appear in practice:
    N∑∏      = stunned AND no parry, both for N rounds
    (π-N)    = must parry next round, with the parry rolled at -N
    N(-M)    = foe at -M penalty for N rounds

Anything not recognised is passed through verbatim.
"""

from __future__ import annotations

import re

# Symbols → durative-effect names. Order matters: ∑∏ must be checked before ∑/∏.
DURATIVE_NAMES = [
    ("∑∏", "stunned and no parry"),
    ("∑",  "stunned"),
    ("∏",  "no parry"),
    ("π",  "must parry"),
    ("∫",  "bleed {n} hit{s}/round"),  # special-cased below
]


def _plural(n: int) -> str:
    return "" if n == 1 else "s"


def _translate_token(tok: str) -> str:
    """Translate one ' – '-separated token. Falls back to the raw token
    if no rule matches."""
    t = tok.strip()
    if not t or t in ("—", "-"):
        return ""

    # +NH or +N hits
    m = re.match(r"^\+\s*(\d+)\s*(?:H|hits)$", t)
    if m:
        return f"+{m.group(1)} hits"

    # (π-N): must parry next round at -N
    m = re.match(r"^\(π\s*-\s*(\d+)\)$", t)
    if m:
        return f"must parry next round at -{m.group(1)}"

    # (+N) attacker bonus next round
    m = re.match(r"^\(\+\s*(\d+)\)$", t)
    if m:
        return f"attacker +{m.group(1)} next round"

    # (-N) foe penalty
    m = re.match(r"^\(-\s*(\d+)\)$", t)
    if m:
        return f"foe at -{m.group(1)}"

    # N(-M): foe at -M for N rounds
    m = re.match(r"^(\d+)\(-\s*(\d+)\)$", t)
    if m:
        n, mod = int(m.group(1)), m.group(2)
        return f"foe at -{mod} for {n} round{_plural(n)}"

    # Compound stun+no-parry: N∑∏
    m = re.match(r"^(\d*)∑∏$", t)
    if m:
        n = int(m.group(1)) if m.group(1) else 1
        return f"stunned and no parry for {n} round{_plural(n)}"

    # Single durative symbols: Nπ, N∏, N∑
    for sym, name in (("π", "must parry"), ("∏", "no parry"), ("∑", "stunned")):
        m = re.match(rf"^(\d*){re.escape(sym)}$", t)
        if m:
            n = int(m.group(1)) if m.group(1) else 1
            if sym == "∏":
                return f"no parry for {n} round{_plural(n)}"
            return f"{name} {n} round{_plural(n)}"

    # Bleed: N∫
    m = re.match(r"^(\d*)∫$", t)
    if m:
        n = int(m.group(1)) if m.group(1) else 1
        return f"bleed {n} hit{_plural(n)}/round"

    # Unknown — pass through with a marker so it's visible
    return f"[{t}]"


def _split_top_level(s: str) -> list[str]:
    """Split on hyphen/en-dash separators while respecting parentheses."""
    s = s.replace("–", "-").replace("—", "-")
    parts: list[str] = []
    depth = 0
    cur = ""
    for ch in s:
        if ch == "(":
            depth += 1
            cur += ch
        elif ch == ")":
            depth -= 1
            cur += ch
        elif ch == "-" and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    parts.append(cur.strip())
    return [p for p in parts if p]


def pretty_effect(code: str | None) -> str:
    """Translate an effect-code string into readable English."""
    if code is None:
        return ""
    s = code.strip()
    if not s or s in ("—", "-"):
        return "no effect"
    parts = _split_top_level(s)
    pretty = [p for p in (_translate_token(t) for t in parts) if p]
    return ", ".join(pretty) if pretty else "no effect"


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    # quick smoke tests
    cases = [
        "+0H",
        "+5H – ∑",
        "+6H – 2∑∏",
        "+10H – ∑∏ – (-10)",
        "+18H – 3∑ – 6(-60)",
        "+6H – (π-25)",
        "+8H – ∑ – 4(-20)",
        "+10H – 2∑ – ∏",
        "+18H – ∫ – 2∑∏",
        "+30 hits – ∫ – (+20)",
        "(+10)",
        "—",
        "",
        "+15H – (-60)",
    ]
    for c in cases:
        print(f"  {c!r:40s} → {pretty_effect(c)}")
