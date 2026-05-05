"""CLI: roll d100 (open-ended) + OB → attack chart → crit chain → fumble chain.

Usage:
    python roll.py <weapon> <AT> <OB> [--attack-size 1-4] [--seed N] [--no-open-ended]
"""

from __future__ import annotations

import argparse
import random
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core import (
    connect, d100, format_rolls,
    get_weapon, attack_lookup, size_cap,
    resolve_crit_table_id, crit_lookup, crit_lookup_by_name,
    fumble_lookup, parse_fumble_crit_chain,
    CRIT_TYPE_NAMES, SIZE_NAMES,
)
from effects import pretty_effect


def _band(row: dict) -> str:
    return (str(row["roll_min"]) if row["roll_min"] == row["roll_max"]
            else f"{row['roll_min']}-{row['roll_max']}")


def print_crit_block(crit: dict, indent: str = "  ") -> None:
    """Render a crit_lookup result. Shared by attack→crit and fumble→crit chains."""
    narrative = crit["narrative"] or "[narrative TODO — fill in from your copy]"
    print(f"{indent}→ {crit['crit_table_name']} {crit['severity']}, "
          f"band {_band(crit)}:")
    print(f"{indent}   {narrative}")
    if crit["effects"]:
        print()
    for eff in crit["effects"]:
        cond = f"[{eff['condition']}] " if eff["condition"] else ""
        pretty = pretty_effect(eff["raw_code"])
        print(f"{indent}   {cond}{pretty}")


def fumble_resolve(conn, weapon: dict, reason: str) -> None:
    """Roll on the weapon's fumble table; if the cell narrative names a
    "'<sev>' <type> critical", roll d100 on that crit chart and chain.
    """
    print(f"  → FUMBLE  ({reason})")
    table_name = weapon.get("fumble_table_name")
    col_idx = weapon.get("fumble_column_index")
    if not table_name or not col_idx:
        print("     weapon has no fumble routing — roll on the appropriate "
              "Fumble Table manually")
        return

    fumble_die = d100()
    print(f"\nFumble roll: d100 = {fumble_die}  ({table_name} / col {col_idx})")
    row = fumble_lookup(conn, table_name, col_idx, fumble_die)
    if row is None:
        print(f"  → no entry on {table_name} col {col_idx} at {fumble_die}")
        return

    narrative = row["narrative"] or "[narrative TODO]"
    print(f"  → {row['table_name']} / {row['col_name']}, band {_band(row)}:")
    print(f"     {narrative}")

    chain = parse_fumble_crit_chain(narrative)
    if not chain:
        return
    sev, chart_name = chain
    crit_die = d100()
    crit = crit_lookup_by_name(conn, chart_name, sev, crit_die)
    if crit is None:
        print(f"\n  (could not chain: {chart_name!r} crit chart not loaded "
              f"or no entry at {sev}/{crit_die})")
        return
    print(f"\nAuto-chained crit: {chart_name} {sev}, d100 = {crit_die}")
    print_crit_block(crit)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("weapon")
    p.add_argument("at", type=int, help="armor type 1-20")
    p.add_argument("ob", type=int, help="offensive bonus")
    p.add_argument("--attack-size", type=int, choices=[1, 2, 3, 4],
                   help="for sweeps-style charts: 1=Small, 2=Medium, 3=Large, 4=Huge")
    p.add_argument("--seed", type=int, help="seed RNG for reproducible rolls")
    p.add_argument("--no-open-ended", action="store_true",
                   help="disable open-ended d100 (use plain 1-100 roll)")
    args = p.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    conn = connect()
    try:
        weapon = get_weapon(conn, args.weapon)
        if weapon is None:
            raise SystemExit(f"Weapon {args.weapon!r} not found in DB")

        # ----- attack roll -----
        raw_roll = d100()
        rolls = [raw_roll]
        direction = None

        is_um_fumble = (
            weapon["fumble_unmodified"]
            and weapon["fumble_min"] is not None
            and weapon["fumble_min"] <= raw_roll <= weapon["fumble_max"]
        )

        if not args.no_open_ended and not is_um_fumble:
            if raw_roll >= 96:
                direction = "high"
                while True:
                    r = d100()
                    rolls.append(r)
                    if r < 96:
                        break
                roll_value = sum(rolls)
            elif raw_roll <= 5:
                direction = "low"
                while True:
                    r = d100()
                    rolls.append(r)
                    if r < 96:
                        break
                roll_value = rolls[0] - sum(rolls[1:])
            else:
                roll_value = raw_roll
        else:
            roll_value = raw_roll

        attack_total = roll_value + args.ob
        print(f"=== {args.weapon} vs AT{args.at}, OB +{args.ob} ===")
        oe_tag = f"  (open-ended {direction})" if direction else ""
        print(f"d100: [{format_rolls(rolls, direction)}] = {roll_value}"
              f"{oe_tag},  + OB {args.ob}  =  attack total {attack_total}")

        if is_um_fumble:
            fumble_resolve(
                conn, weapon,
                reason=f"unmodified roll {raw_roll} in fumble range "
                       f"{weapon['fumble_min']:02d}-{weapon['fumble_max']:02d} UM",
            )
            return

        if args.attack_size:
            cap = size_cap(conn, weapon["weapon_id"], args.attack_size)
            if cap is not None and attack_total > cap:
                print(f"  → {SIZE_NAMES[args.attack_size]} attacker cap "
                      f"({cap}) — using {cap} instead of {attack_total}")
                attack_total = cap

        res, was_capped = attack_lookup(conn, weapon["weapon_id"],
                                         args.at, attack_total)
        if res is None:
            print(f"  → no entry on chart at total {attack_total} — too low (miss)")
            return
        cap_tag = "  (capped to chart max)" if was_capped else ""
        print(f"  → band {_band(res)}{cap_tag}: {res['raw']}", end="")

        if res["is_fumble"]:
            print("")
            fumble_resolve(conn, weapon,
                           reason=f"chart cell 'F' at total {attack_total}")
            return
        if res["raw"] == "-":
            print("  →  MISS (no damage)")
            return

        parts = [f"{res['hits']} hits"]
        if res["crit_severity"]:
            if res["crit_type"]:
                parts.append(f"severity {res['crit_severity']} "
                             f"{CRIT_TYPE_NAMES.get(res['crit_type'], res['crit_type'])} crit")
            else:
                parts.append(f"severity {res['crit_severity']} crit")
        print(f"  →  {', '.join(parts)}")

        if not res["crit_severity"]:
            return
        ct_id = resolve_crit_table_id(conn, res, weapon["default_crit_table_id"])
        if ct_id is None:
            print("\n  (could not resolve crit table — chart may not be loaded)")
            return
        crit_die = d100()
        print(f"\nCrit roll: d100 = {crit_die}")
        crit = crit_lookup(conn, ct_id, res["crit_severity"], crit_die)
        if crit is None:
            print(f"  → no entry on {res['crit_severity']} column at {crit_die}")
            return
        print_crit_block(crit)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
