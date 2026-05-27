import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchCharacterWeaponCosts,
  updateCharacterWeaponCosts,
  type Character,
  type WeaponCostsResponse,
} from "../api";

interface Props {
  character: Character;
}

/**
 * Weapon-cost reassignment picker (RMSS Character Law §6.2).
 *
 * A profession comes with a multiset of weapon costs — Fighter, for
 * example, has {1/5, 2/5, 2/7, 2/7, 2/7, 5, 5} across seven weapon
 * categories. RMSS lets the player swap which category gets which cost,
 * provided the multiset stays the same.
 *
 * This component renders one row per weapon category with a dropdown
 * containing every cost from the pool. The "Save assignment" button
 * fires the PUT when the draft is valid (every dropdown filled, costs
 * use up each pool slot exactly once). Selecting "Reset to defaults"
 * clears overrides server-side.
 *
 * Hidden when the character has no profession picked.
 */
export function WeaponCostPicker({ character }: Props) {
  const qc = useQueryClient();
  const q = useQuery<WeaponCostsResponse>({
    queryKey: ["characters", character.character_id, "weapon-costs"],
    queryFn: () => fetchCharacterWeaponCosts(character.character_id),
    enabled: !!character.profession_id,
  });

  // Local draft: weapon_category → cost. Initialised from the server
  // snapshot, mutated by the per-row dropdown.
  const [draft, setDraft] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!q.data) return;
    const next: Record<string, string> = {};
    for (const row of q.data.rows) next[row.weapon_category] = row.cost;
    setDraft(next);
  }, [q.data]);

  const m = useMutation({
    mutationFn: () =>
      updateCharacterWeaponCosts(
        character.character_id,
        Object.entries(draft).map(([weapon_category, cost]) => ({
          weapon_category, cost,
        })),
      ),
    onSuccess: (fresh) => {
      qc.setQueryData(
        ["characters", character.character_id, "weapon-costs"], fresh,
      );
      // The DP allocator (Phase B) will use these costs for hobby-rank
      // caps + skill purchases, so refresh anything that might depend
      // on them once they're rebuilt.
      qc.invalidateQueries({
        queryKey: ["characters", character.character_id, "adolescence-ranks"],
      });
    },
  });

  const resetM = useMutation({
    mutationFn: () => updateCharacterWeaponCosts(character.character_id, []),
    onSuccess: (fresh) => {
      qc.setQueryData(
        ["characters", character.character_id, "weapon-costs"], fresh,
      );
    },
  });

  // Live multiset validation: how many of each cost in the draft, vs
  // how many in the pool. If counts differ, save is disabled.
  const validation = useMemo(() => {
    if (!q.data) return { valid: false, used: new Map<string, number>(),
                          poolCounts: new Map<string, number>() };
    const poolCounts = new Map<string, number>();
    for (const c of q.data.pool) poolCounts.set(c, (poolCounts.get(c) ?? 0) + 1);
    const used = new Map<string, number>();
    for (const c of Object.values(draft)) used.set(c, (used.get(c) ?? 0) + 1);
    let valid = used.size === poolCounts.size;
    if (valid) {
      for (const [c, n] of poolCounts) {
        if (used.get(c) !== n) { valid = false; break; }
      }
    }
    return { valid, used, poolCounts };
  }, [draft, q.data]);

  // Drives the "Save" enabled/disabled. Also true while the multiset is
  // out-of-balance: the user can pick a cost in two slots at once mid-edit
  // and that's fine UI-wise, but PUT would 422.
  const dirty = useMemo(() => {
    if (!q.data) return false;
    return q.data.rows.some(
      (r) => draft[r.weapon_category] !== r.cost,
    );
  }, [q.data, draft]);

  // Render gate: nothing to show until the profession is set.
  if (!character.profession_id) return null;
  if (q.isLoading) {
    return <p style={{ color: "#666", fontSize: 13 }}>Loading weapon costs…</p>;
  }
  if (q.error) {
    return (
      <p style={{ color: "crimson", fontSize: 13 }}>
        Failed to load weapon costs: {String(q.error)}
      </p>
    );
  }
  if (!q.data || q.data.rows.length === 0) {
    return null;   // profession has no weapon costs (rare)
  }

  // Build the dropdown options — show each unique cost in the pool with
  // its multiplicity (so "2/7 (×3)" makes clear there are three slots).
  const uniqueCosts = Array.from(validation.poolCounts.keys()).sort();

  // Per-cost balance helper for the footer.
  const balanceRows = uniqueCosts.map((c) => {
    const used = validation.used.get(c) ?? 0;
    const need = validation.poolCounts.get(c) ?? 0;
    return { cost: c, used, need, balanced: used === need };
  });

  return (
    <section style={{ marginTop: 16 }}>
      <header style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Weapon-cost assignment</h3>
        <span style={{ fontSize: 12, color: "#666" }}>
          RMSS Character Law §6.2
        </span>
      </header>
      <p style={{ marginTop: 6, fontSize: 13, color: "#666" }}>
        Your profession's weapon-cost pool is fixed, but you choose which
        weapon category gets which cost. Swap freely — the totals
        (multiset) stay the same.
      </p>

      <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8, fontSize: 13 }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "1px solid #ddd", color: "#666", fontSize: 12 }}>
            <th style={{ padding: "4px 0", width: "40%" }}>Weapon category</th>
            <th style={{ padding: "4px 0", width: "30%" }}>Cost (DP / rank)</th>
            <th style={{ padding: "4px 0", width: "30%" }}>Ranks / level</th>
          </tr>
        </thead>
        <tbody>
          {q.data.rows.map((row) => {
            const value = draft[row.weapon_category] ?? row.cost;
            const overridden = value !== row.cost
                                ? value !== q.data!.rows.find(
                                    (r) => r.weapon_category === row.weapon_category,
                                  )?.cost
                                : row.is_override;
            return (
              <tr key={row.weapon_category} style={{ borderBottom: "1px solid #f3f3f3" }}>
                <td style={{ padding: "5px 0", fontWeight: 500 }}>
                  {row.weapon_category}
                </td>
                <td style={{ padding: "5px 0" }}>
                  <select
                    value={value}
                    onChange={(e) =>
                      setDraft((d) => ({ ...d, [row.weapon_category]: e.target.value }))
                    }
                    style={{
                      padding: "3px 6px",
                      fontSize: 13,
                      border: `1px solid ${overridden ? "#a16207" : "#ccc"}`,
                      borderRadius: 3,
                      background: overridden ? "#fff8e1" : "white",
                    }}
                  >
                    {uniqueCosts.map((c) => (
                      <option key={c} value={c}>
                        {c}
                        {(validation.poolCounts.get(c) ?? 0) > 1
                          ? ` (×${validation.poolCounts.get(c)})` : ""}
                      </option>
                    ))}
                  </select>
                </td>
                <td style={{
                  padding: "5px 0",
                  color: "#666",
                  fontVariantNumeric: "tabular-nums",
                }}>
                  {rankCapForCost(value)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {/* Pool balance footer */}
      <div style={{
        marginTop: 8,
        padding: "6px 10px",
        background: validation.valid ? "#f0f7ed" : "#fff4f4",
        border: `1px solid ${validation.valid ? "#bcd9ad" : "#f5a3a3"}`,
        borderRadius: 4,
        fontSize: 12,
        display: "flex",
        gap: 12,
        flexWrap: "wrap",
      }}>
        <strong>Pool:</strong>
        {balanceRows.map((b) => (
          <span key={b.cost} style={{
            color: b.balanced ? "#566" : "#c00",
            fontVariantNumeric: "tabular-nums",
          }}>
            {b.cost}: {b.used}/{b.need}
          </span>
        ))}
      </div>

      <div style={{ marginTop: 10, display: "flex", gap: 8, alignItems: "center" }}>
        <button
          className="btn"
          onClick={() => m.mutate()}
          disabled={!dirty || !validation.valid || m.isPending || resetM.isPending}
          title={!validation.valid
            ? "Pool isn't balanced — every cost must be used the right number of times."
            : undefined}
        >
          {m.isPending ? "Saving…" : "Save assignment"}
        </button>
        <button
          className="btn btn-secondary"
          onClick={() => resetM.mutate()}
          disabled={m.isPending || resetM.isPending
                    || q.data.rows.every((r) => !r.is_override)}
          title="Revert all overrides to the profession defaults"
        >
          {resetM.isPending ? "Resetting…" : "Reset to defaults"}
        </button>
        {(m.error || resetM.error) && (
          <span style={{ color: "crimson", fontSize: 13 }}>
            {String(m.error ?? resetM.error)}
          </span>
        )}
      </div>
    </section>
  );
}

/** Mirror of core.chargen.weapon_costs.rank_cap_for_cost — kept in sync
 *  manually. Cost "1/5" → 2 ranks/level; "2/2/2" → 3; "5" → 1. */
function rankCapForCost(cost: string): number {
  if (!cost.trim()) return 0;
  return cost.split("/").filter((t) => t.trim()).length;
}
