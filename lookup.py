"""CLI for static lookups (no dice rolling).

Usage:
    python lookup.py attack <weapon> <armor_type> <attack_roll> [crit_roll]
    python lookup.py crit   <chart>  <severity>     <roll>
    python lookup.py fumble <table>  <col_index>    <roll>
"""

from __future__ import annotations

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core import (
    connect, get_weapon, attack_lookup,
    crit_lookup, crit_lookup_by_name, resolve_crit_table_id,
    fumble_lookup,
    CRIT_TYPE_NAMES,
)
from effects import pretty_effect


# ---------------------------------------------------------------------------
# rendering helpers (CLI-only; bot has its own embed renderer)
# ---------------------------------------------------------------------------

def describe_attack(result: dict) -> str:
    if result["is_fumble"]:
        return "FUMBLE — roll on the appropriate Fumble Table"
    raw = result["raw"]
    if raw == "-":
        return "miss (no damage)"
    parts = [f"{result['hits']} hits"]
    if result["crit_severity"]:
        if result["crit_type"]:
            ctype = CRIT_TYPE_NAMES.get(result["crit_type"], result["crit_type"])
            parts.append(f"severity {result['crit_severity']} {ctype} crit")
        else:
            parts.append(f"severity {result['crit_severity']} crit "
                         f"(chart from weapon default)")
    return ", ".join(parts)


def _band(row: dict) -> str:
    return (str(row["roll_min"]) if row["roll_min"] == row["roll_max"]
            else f"{row['roll_min']}-{row['roll_max']}")


# ---------------------------------------------------------------------------
# subcommand handlers
# ---------------------------------------------------------------------------

def cmd_attack(args, conn) -> None:
    weapon = get_weapon(conn, args.weapon)
    if weapon is None:
        print(f"Weapon {args.weapon!r} not found")
        return
    res, _capped = attack_lookup(conn, weapon["weapon_id"],
                                  args.armor_type, args.attack_roll)
    if res is None:
        print(f"{args.weapon} vs AT{args.armor_type} on roll {args.attack_roll}: "
              f"no entry (roll too low for the chart)")
        return
    print(f"{args.weapon} vs AT{args.armor_type}, roll {args.attack_roll} "
          f"(band {_band(res)}): {res['raw']}  ({describe_attack(res)})")

    if not (res["crit_severity"] and args.crit_roll is not None):
        return
    ct_id = resolve_crit_table_id(conn, res, weapon["default_crit_table_id"])
    if ct_id is None:
        print("  (no crit table resolvable — load the named crit table)")
        return
    crit = crit_lookup(conn, ct_id, res["crit_severity"], args.crit_roll)
    if crit is None:
        print(f"  crit roll {args.crit_roll} on {res['crit_severity']}: no entry on chart")
        return
    narrative = crit["narrative"] or "[narrative TODO — fill in from your copy]"
    print(f"  -> {crit['crit_table_name']} {crit['severity']} crit, "
          f"roll {args.crit_roll} (band {_band(crit)}):")
    print(f"     {narrative}")
    for eff in crit["effects"]:
        cond = f" [{eff['condition']}]" if eff["condition"] else ""
        pretty = pretty_effect(eff["raw_code"])
        print(f"     effect{cond}: {eff['raw_code']}  ({pretty})")


def cmd_crit(args, conn) -> None:
    res = crit_lookup_by_name(conn, args.table, args.severity, args.roll)
    if res is None:
        print(f"crit table {args.table!r} not loaded, or roll {args.roll} "
              f"has no entry on column {args.severity}")
        return
    narrative = res["narrative"] or "[narrative TODO — fill in from your copy]"
    print(f"{res['crit_table_name']} {res['severity']}, roll {args.roll} "
          f"(band {_band(res)}):")
    print(f"  {narrative}")
    for eff in res["effects"]:
        cond = f" [{eff['condition']}]" if eff["condition"] else ""
        pretty = pretty_effect(eff["raw_code"])
        print(f"  effect{cond}: {eff['raw_code']}  ({pretty})")


def cmd_fumble(args, conn) -> None:
    res = fumble_lookup(conn, args.table, args.col_index, args.roll)
    if res is None:
        print(f"{args.table} col {args.col_index}, roll {args.roll}: no entry")
        return
    narrative = res["narrative"] or "[narrative TODO — fill in from your copy]"
    print(f"{res['table_name']} / {res['col_name']}, roll {args.roll} "
          f"(band {_band(res)}):")
    print(f"  {narrative}")


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("attack")
    a.add_argument("weapon")
    a.add_argument("armor_type", type=int)
    a.add_argument("attack_roll", type=int)
    a.add_argument("crit_roll", type=int, nargs="?", default=None)

    c = sub.add_parser("crit")
    c.add_argument("table", help='e.g. "Brawling", "Krush", "Slash"')
    c.add_argument("severity", help="A | B | C | D | E (or attack-type label)")
    c.add_argument("roll", type=int)

    f = sub.add_parser("fumble")
    f.add_argument("table")
    f.add_argument("col_index", type=int)
    f.add_argument("roll", type=int)

    args = p.parse_args()

    conn = connect()
    try:
        if args.cmd == "attack":
            cmd_attack(args, conn)
        elif args.cmd == "crit":
            cmd_crit(args, conn)
        elif args.cmd == "fumble":
            cmd_fumble(args, conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
