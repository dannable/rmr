import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchSkillAllocator,
  fetchTrainingPackagesAvailable,
  purchaseTrainingPackage,
  refundTrainingPackage,
  updateCategoryRanks,
  updateSkillRanks,
  type Character,
  type SkillAllocatorResponse,
  type SkillCategoryRow,
  type TrainingPackageOption,
  type TrainingPackagesAvailableResponse,
} from "../api";

interface Props {
  character: Character;
}

/**
 * Step 6 — DP allocator. Browse every skill category, buy ranks at the
 * profession-determined cost, see the live DP budget update as you spend.
 *
 * Pulls /skill-allocator for the snapshot (every category + skill +
 * computed total bonus + per-rank cost), plus /training-packages-available
 * for the TP shop section. Both queries refresh on every mutation so
 * the rest of the builder (Adolescence, etc.) sees the new state too.
 *
 * Bonus math (server-computed): rank_progression(ranks) + stat bonus
 * (relevant stats summed) + profession category/group bonuses.
 */
export function SkillAllocator({ character }: Props) {
  const qc = useQueryClient();
  const q = useQuery<SkillAllocatorResponse>({
    queryKey: ["characters", character.character_id, "skill-allocator"],
    queryFn: () => fetchSkillAllocator(character.character_id),
  });
  const tpQ = useQuery<TrainingPackagesAvailableResponse>({
    queryKey: ["characters", character.character_id, "training-packages-available"],
    queryFn: () => fetchTrainingPackagesAvailable(character.character_id),
  });

  const invalidate = () => {
    qc.invalidateQueries({
      queryKey: ["characters", character.character_id, "skill-allocator"],
    });
    qc.invalidateQueries({
      queryKey: ["characters", character.character_id, "training-packages-available"],
    });
  };

  const catM = useMutation({
    mutationFn: ({ group_name, category_name, ranks_bought }: {
      group_name: string; category_name: string; ranks_bought: number;
    }) => updateCategoryRanks(character.character_id, group_name, category_name, ranks_bought),
    onSuccess: invalidate,
  });
  const skillM = useMutation({
    mutationFn: ({ group_name, category_name, skill_name, ranks_bought }: {
      group_name: string; category_name: string; skill_name: string; ranks_bought: number;
    }) => updateSkillRanks(character.character_id, group_name, category_name,
                            skill_name, ranks_bought),
    onSuccess: invalidate,
  });

  // Group filter so the list is browsable. Default: only categories
  // the profession can actually train (cost present).
  const [showUntrainable, setShowUntrainable] = useState(false);

  if (q.isLoading) return <p>Loading skill allocator…</p>;
  if (q.error) return <p style={{ color: "crimson" }}>Failed to load: {String(q.error)}</p>;
  if (!q.data) return null;

  const data = q.data;
  const visible = data.categories.filter(
    (c) => showUntrainable || c.cost !== "",
  );

  // Group categories by their group_name for accordion-style rendering.
  const byGroup = new Map<string, SkillCategoryRow[]>();
  for (const c of visible) {
    const arr = byGroup.get(c.group_name) ?? [];
    arr.push(c);
    byGroup.set(c.group_name, arr);
  }
  const sortedGroups = Array.from(byGroup.keys()).sort();

  const mutating = catM.isPending || skillM.isPending;
  const mutationError = catM.error ?? skillM.error;

  return (
    <section>
      <DPBudgetBanner budget={data.budget} />

      <div style={{ marginTop: 12, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <label style={{ fontSize: 13, color: "#444" }}>
          <input
            type="checkbox"
            checked={showUntrainable}
            onChange={(e) => setShowUntrainable(e.target.checked)}
            style={{ marginRight: 4 }}
          />
          Show categories with no profession cost (untrainable / restricted)
        </label>
      </div>

      {mutationError && (
        <p style={{ color: "crimson", fontSize: 13, marginTop: 8 }}>
          {String(mutationError)}
        </p>
      )}

      {sortedGroups.map((group) => (
        <GroupSection
          key={group}
          group={group}
          categories={byGroup.get(group)!}
          onCategoryChange={(c, ranks) => catM.mutate({
            group_name: c.group_name,
            category_name: stripGroupPrefix(c.group_name, c.category_name),
            ranks_bought: ranks,
          })}
          onSkillChange={(c, skillName, ranks) => skillM.mutate({
            group_name: c.group_name,
            category_name: stripGroupPrefix(c.group_name, c.category_name),
            skill_name: skillName,
            ranks_bought: ranks,
          })}
          disabled={mutating}
        />
      ))}

      <hr style={{ marginTop: 24 }} />
      <TPMarketSection
        characterId={character.character_id}
        purchased={data.training_packages_purchased}
        tpQ={tpQ}
        onChange={invalidate}
      />
    </section>
  );
}


function DPBudgetBanner({ budget }: { budget: SkillAllocatorResponse["budget"] }) {
  const over = budget.dp_remaining < 0;
  return (
    <div style={{
      padding: "10px 14px",
      background: over ? "#fff4f4" : "#f5f7fb",
      border: `1px solid ${over ? "#f5a3a3" : "#d8e0ef"}`,
      borderRadius: 4,
      fontSize: 14,
      display: "flex",
      gap: 18,
      flexWrap: "wrap",
      alignItems: "baseline",
    }}>
      <span><strong>DP budget:</strong>{" "}
        <span style={{ color: over ? "#c00" : "#222", fontVariantNumeric: "tabular-nums" }}>
          {budget.dp_spent} / {budget.dp_total}
        </span>
      </span>
      <span style={{
        color: over ? "#c00" : (budget.dp_remaining === 0 ? "#666" : "#16a34a"),
        fontVariantNumeric: "tabular-nums",
      }}>
        {budget.dp_remaining} remaining{over ? " (OVER)" : ""}
      </span>
      <span style={{ color: "#888", fontSize: 12 }}>
        DP total = (Ag + Co + Me + Re + SD) ÷ 5, round normally
      </span>
    </div>
  );
}


function GroupSection({
  group, categories, onCategoryChange, onSkillChange, disabled,
}: {
  group: string;
  categories: SkillCategoryRow[];
  onCategoryChange: (c: SkillCategoryRow, ranks: number) => void;
  onSkillChange: (c: SkillCategoryRow, skillName: string, ranks: number) => void;
  disabled: boolean;
}) {
  return (
    <section style={{ marginTop: 16 }}>
      <h3 style={{ margin: "0 0 6px", fontSize: 15, color: "#333" }}>{group}</h3>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "1px solid #ddd", color: "#666", fontSize: 12 }}>
            <th style={{ padding: "4px 0", width: "26%" }}>Category / Skill</th>
            <th style={{ padding: "4px 0", width: "10%", textAlign: "center" }}>Current Ranks</th>
            <th style={{ padding: "4px 0", width: "10%" }}>Cost</th>
            <th style={{ padding: "4px 0", width: "12%", textAlign: "center" }}>Buy</th>
            <th style={{ padding: "4px 0", width: "8%", textAlign: "right" }}>DP spent</th>
            <th style={{ padding: "4px 0", width: "8%", textAlign: "right" }}>Class</th>
            <th style={{ padding: "4px 0", width: "8%", textAlign: "right" }}>Special</th>
            <th style={{ padding: "4px 0", width: "8%", textAlign: "right" }}>Total</th>
          </tr>
        </thead>
        <tbody>
          {categories.map((c) => (
            <CategoryAndSkills
              key={`${c.group_name}|${c.category_name}`}
              category={c}
              onCategoryChange={(r) => onCategoryChange(c, r)}
              onSkillChange={(sn, r) => onSkillChange(c, sn, r)}
              disabled={disabled}
            />
          ))}
        </tbody>
      </table>
    </section>
  );
}


function CategoryAndSkills({
  category, onCategoryChange, onSkillChange, disabled,
}: {
  category: SkillCategoryRow;
  onCategoryChange: (ranks: number) => void;
  onSkillChange: (skillName: string, ranks: number) => void;
  disabled: boolean;
}) {
  const c = category;
  const untrainable = c.cost === "";
  return (
    <>
      <tr style={{ borderBottom: "1px solid #f3f3f3", background: "#fafafa" }}>
        <td style={{ padding: "5px 0", fontWeight: 500 }}>
          {stripGroupPrefix(c.group_name, c.category_name)}
          {c.classification && (
            <span style={{ color: "#999", fontSize: 11, marginLeft: 6 }}>
              ({c.classification})
            </span>
          )}
        </td>
        <td style={{ padding: "5px 0", textAlign: "center",
                       fontVariantNumeric: "tabular-nums",
                       color: c.current_ranks === 0 ? "#aaa" : "#222",
                       fontWeight: 500 }}>
          {c.current_ranks}
        </td>
        <td style={{ padding: "5px 0", fontVariantNumeric: "tabular-nums",
                       color: untrainable ? "#aaa" : "#444" }}>
          {untrainable ? "—" : c.cost}
        </td>
        <td style={{ padding: "5px 0", textAlign: "center" }}>
          <RankAdjuster
            value={c.ranks_bought}
            max={c.rank_cap_per_level}
            disabled={disabled || untrainable}
            onChange={onCategoryChange}
          />
        </td>
        <td style={{ padding: "5px 0", textAlign: "right",
                       fontVariantNumeric: "tabular-nums", color: "#666" }}>
          {c.dp_spent}
        </td>
        <td style={dimCell(c.class_bonus)}>{fmt(c.class_bonus)}</td>
        <td style={dimCell(c.special_bonus)}>{fmt(c.special_bonus)}</td>
        <td style={{ padding: "5px 0", textAlign: "right",
                       fontVariantNumeric: "tabular-nums", fontWeight: 600 }}>
          {fmt(c.total_bonus)}
        </td>
      </tr>
      {c.skills.map((s) => (
        <tr key={s.skill_name} style={{ borderBottom: "1px solid #f3f3f3" }}>
          <td style={{ padding: "3px 0 3px 18px", color: "#444" }}>
            {s.skill_name}
            {s.stat && (
              <span style={{ color: "#999", fontSize: 11, marginLeft: 6 }}>
                [{s.stat}]
              </span>
            )}
          </td>
          <td style={{ padding: "3px 0", textAlign: "center",
                         fontVariantNumeric: "tabular-nums",
                         color: s.current_ranks === 0 ? "#aaa" : "#222" }}>
            {s.current_ranks}
          </td>
          <td style={{ padding: "3px 0", color: "#888",
                         fontVariantNumeric: "tabular-nums" }}>
            {untrainable ? "—" : c.cost}
          </td>
          <td style={{ padding: "3px 0", textAlign: "center" }}>
            <RankAdjuster
              value={s.ranks_bought}
              max={c.rank_cap_per_level}
              disabled={disabled || untrainable}
              onChange={(r) => onSkillChange(s.skill_name, r)}
            />
          </td>
          <td style={{ padding: "3px 0", textAlign: "right",
                         fontVariantNumeric: "tabular-nums", color: "#666" }}>
            {s.dp_spent}
          </td>
          <td style={dimCell(s.class_bonus, 11)}>{fmt(s.class_bonus)}</td>
          <td style={dimCell(s.special_bonus, 11)}>{fmt(s.special_bonus)}</td>
          <td style={{ padding: "3px 0", textAlign: "right",
                         fontVariantNumeric: "tabular-nums", fontWeight: 500 }}>
            {fmt(s.total_bonus)}
          </td>
        </tr>
      ))}
    </>
  );
}


/** Compact +/- buttons that adjust the rank count on the fly. Replaces
 *  the old dropdown — clicking + buys the next rank (POST happens via
 *  the parent's onChange); clicking - refunds the last rank. */
function RankAdjuster({
  value, max, disabled, onChange,
}: {
  value: number; max: number; disabled: boolean;
  onChange: (newValue: number) => void;
}) {
  if (max === 0) {
    return <span style={{ color: "#aaa" }}>—</span>;
  }
  const canDec = !disabled && value > 0;
  const canInc = !disabled && value < max;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      <button
        type="button"
        onClick={() => onChange(value - 1)}
        disabled={!canDec}
        title="Refund this rank"
        style={btn(canDec)}
      >
        −
      </button>
      <span style={{
        minWidth: 20, textAlign: "center",
        fontVariantNumeric: "tabular-nums",
        color: value === 0 ? "#999" : "#222",
        fontWeight: 500,
      }}>{value}</span>
      <button
        type="button"
        onClick={() => onChange(value + 1)}
        disabled={!canInc}
        title={canInc ? "Buy next rank" : "At per-level rank cap"}
        style={btn(canInc)}
      >
        +
      </button>
    </span>
  );
}

function btn(enabled: boolean): React.CSSProperties {
  return {
    padding: "0 6px",
    fontSize: 14,
    lineHeight: 1.2,
    minWidth: 22,
    border: "1px solid " + (enabled ? "#999" : "#ddd"),
    borderRadius: 3,
    background: enabled ? "white" : "#fafafa",
    color: enabled ? "#222" : "#bbb",
    cursor: enabled ? "pointer" : "default",
  };
}

function dimCell(value: number, fontSize: number = 13): React.CSSProperties {
  return {
    padding: "5px 0",
    textAlign: "right" as const,
    fontVariantNumeric: "tabular-nums",
    color: value === 0 ? "#bbb" : (value > 0 ? "#16a34a" : "#dc2626"),
    fontSize,
  };
}


function TPMarketSection({
  characterId, purchased, tpQ, onChange,
}: {
  characterId: number;
  purchased: SkillAllocatorResponse["training_packages_purchased"];
  tpQ: ReturnType<typeof useQuery<TrainingPackagesAvailableResponse>>;
  onChange: () => void;
}) {
  const buyM = useMutation({
    mutationFn: (slug: string) => purchaseTrainingPackage(characterId, slug),
    onSuccess: onChange,
  });
  const refundM = useMutation({
    mutationFn: (slug: string) => refundTrainingPackage(characterId, slug),
    onSuccess: onChange,
  });
  const [filter, setFilter] = useState("");

  if (tpQ.isLoading) return <p style={{ color: "#666" }}>Loading training packages…</p>;
  if (tpQ.error) return <p style={{ color: "crimson" }}>{String(tpQ.error)}</p>;
  if (!tpQ.data) return null;

  const owned = new Set(purchased.map((p) => p.slug));
  const filtered = tpQ.data.options.filter((o) =>
    !filter || o.name.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <section style={{ marginTop: 16 }}>
      <header style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Training Packages</h3>
        <span style={{ fontSize: 12, color: "#666" }}>
          Cost = profession-specific (or default_cost when no profession entry)
        </span>
      </header>

      {purchased.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <strong style={{ fontSize: 13 }}>Purchased:</strong>
          <ul style={{ margin: "4px 0 0 18px", padding: 0, fontSize: 13 }}>
            {purchased.map((tp) => (
              <li key={tp.slug} style={{ marginTop: 2 }}>
                {tp.name} — {tp.dp_paid} DP{" "}
                <button
                  className="btn btn-secondary"
                  style={{ padding: "1px 6px", fontSize: 11, marginLeft: 6 }}
                  onClick={() => refundM.mutate(tp.slug)}
                  disabled={refundM.isPending}
                >
                  Refund
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div style={{ marginTop: 10 }}>
        <input
          type="search"
          placeholder="Filter training packages…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          style={{
            width: "60%", maxWidth: 320, padding: "4px 8px",
            fontSize: 13, border: "1px solid #ccc", borderRadius: 3,
          }}
        />
      </div>

      <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8, fontSize: 13 }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "1px solid #ddd", color: "#666", fontSize: 12 }}>
            <th style={{ padding: "4px 0", width: "40%" }}>Name</th>
            <th style={{ padding: "4px 0", width: "20%" }}>Source</th>
            <th style={{ padding: "4px 0", width: "10%", textAlign: "right" }}>Cost (DP)</th>
            <th style={{ padding: "4px 0", width: "30%" }} />
          </tr>
        </thead>
        <tbody>
          {filtered.map((opt) => (
            <TPRow
              key={opt.slug}
              opt={opt}
              owned={owned.has(opt.slug)}
              disabled={buyM.isPending || refundM.isPending}
              onBuy={() => buyM.mutate(opt.slug)}
              onRefund={() => refundM.mutate(opt.slug)}
            />
          ))}
        </tbody>
      </table>

      {(buyM.error || refundM.error) && (
        <p style={{ color: "crimson", fontSize: 13, marginTop: 6 }}>
          {String(buyM.error ?? refundM.error)}
        </p>
      )}

      <p style={{ marginTop: 8, fontSize: 12, color: "#888" }}>
        Buying a TP deducts the listed DP from your budget. Refunding restores it.
        Purchased TPs don't yet auto-apply their granted ranks / stat gains —
        that's a follow-up. For now you can see what you've paid for and refund
        anything you change your mind about.
      </p>
    </section>
  );
}


function TPRow({
  opt, owned, disabled, onBuy, onRefund,
}: {
  opt: TrainingPackageOption;
  owned: boolean;
  disabled: boolean;
  onBuy: () => void;
  onRefund: () => void;
}) {
  return (
    <tr style={{ borderBottom: "1px solid #f3f3f3" }}>
      <td style={{ padding: "5px 0" }}>{opt.name}</td>
      <td style={{ padding: "5px 0", color: "#888", fontSize: 12 }}>
        {prettySource(opt.source)}
      </td>
      <td style={{ padding: "5px 0", textAlign: "right",
                     fontVariantNumeric: "tabular-nums",
                     color: opt.affordable ? "#222" : "#c00",
                     fontWeight: 500 }}>
        {opt.effective_cost}
      </td>
      <td style={{ padding: "5px 0", textAlign: "right" }}>
        {owned ? (
          <button
            className="btn btn-secondary"
            style={{ padding: "2px 8px", fontSize: 12 }}
            onClick={onRefund}
            disabled={disabled}
          >
            Refund
          </button>
        ) : (
          <button
            className="btn"
            style={{ padding: "2px 8px", fontSize: 12 }}
            onClick={onBuy}
            disabled={disabled || !opt.affordable}
            title={!opt.affordable ? "Not enough DP remaining" : "Buy this TP"}
          >
            Buy ({opt.effective_cost} DP)
          </button>
        )}
      </td>
    </tr>
  );
}


// ----- helpers --------------------------------------------------------

function fmt(n: number): string {
  if (n === 0) return "0";
  return n > 0 ? `+${n}` : `${n}`;
}

/** "Weapon" + "Weapon • 1-H Edged" → "1-H Edged". */
function stripGroupPrefix(group: string, categoryName: string): string {
  for (const sep of [" • ", " · "]) {
    const p = group + sep;
    if (categoryName.startsWith(p)) return categoryName.slice(p.length);
  }
  return categoryName;
}

function prettySource(src: string): string {
  switch (src) {
    case "character_law":       return "Character Law";
    case "essence_companion":   return "Essence Companion";
    case "channeling_companion":return "Channeling Companion";
    case "mentalism_companion": return "Mentalism Companion";
    case "sohk":                return "School of Hard Knocks";
    default:                     return src;
  }
}
