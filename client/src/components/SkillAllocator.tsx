import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchSkillAllocator,
  fetchTrainingPackage,
  fetchTrainingPackagesAvailable,
  purchaseTrainingPackage,
  refundTrainingPackage,
  updateCategoryRanks,
  updateSkillRanks,
  type Character,
  type SkillAllocatorResponse,
  type SkillCategoryRow,
  type SkillRow,
  type TrainingPackageDetail,
  type TrainingPackageOption,
  type TrainingPackagesAvailableResponse,
} from "../api";
import { progressionBonus } from "../skillBonus";
import { TPDetailSections } from "./TrainingPackageDetailBody";

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

  const allocatorKey = ["characters", character.character_id, "skill-allocator"];
  const tpKey = ["characters", character.character_id, "training-packages-available"];

  // Stale-after-mutate reconciliation: the server is the source of truth,
  // but the SPA also recomputes optimistically (below) so totals update
  // immediately on +/- click. After the PUT settles we invalidate so any
  // server-side corrections flow back in.
  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: allocatorKey });
    qc.invalidateQueries({ queryKey: tpKey });
  };

  const catM = useMutation({
    mutationFn: ({ group_name, category_name, ranks_bought }: {
      group_name: string; category_name: string; ranks_bought: number;
    }) => updateCategoryRanks(character.character_id, group_name, category_name, ranks_bought),
    onMutate: async ({ group_name, category_name, ranks_bought }) => {
      await qc.cancelQueries({ queryKey: allocatorKey });
      const prev = qc.getQueryData<SkillAllocatorResponse>(allocatorKey);
      if (prev) {
        qc.setQueryData<SkillAllocatorResponse>(
          allocatorKey,
          (cur) => cur && applyCategoryRankChange(
            cur, group_name, stripGroupPrefix(group_name, category_name) === category_name
                  ? category_name : stripGroupPrefix(group_name, category_name),
            ranks_bought,
          ),
        );
      }
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(allocatorKey, ctx.prev);
    },
    onSettled: invalidateAll,
  });
  const skillM = useMutation({
    mutationFn: ({ group_name, category_name, skill_name, ranks_bought }: {
      group_name: string; category_name: string; skill_name: string; ranks_bought: number;
    }) => updateSkillRanks(character.character_id, group_name, category_name,
                            skill_name, ranks_bought),
    onMutate: async ({ group_name, category_name, skill_name, ranks_bought }) => {
      await qc.cancelQueries({ queryKey: allocatorKey });
      const prev = qc.getQueryData<SkillAllocatorResponse>(allocatorKey);
      if (prev) {
        qc.setQueryData<SkillAllocatorResponse>(
          allocatorKey,
          (cur) => cur && applySkillRankChange(
            cur, group_name, category_name, skill_name, ranks_bought,
          ),
        );
      }
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(allocatorKey, ctx.prev);
    },
    onSettled: invalidateAll,
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
        onChange={invalidateAll}
      />
    </section>
  );
}


function DPBudgetBanner({ budget }: { budget: SkillAllocatorResponse["budget"] }) {
  const over = budget.dp_remaining < 0;
  return (
    <div style={{
      // Stick to the top of the viewport while the player scrolls the
      // (long) skill list, so the running DP total is always visible.
      // The app header scrolls away with the page, so top:0 is correct —
      // there's no fixed chrome to offset under. zIndex keeps the banner
      // above skill rows; the box-shadow gives a little lift once stuck.
      position: "sticky",
      top: 0,
      zIndex: 10,
      padding: "10px 14px",
      background: over ? "#fff4f4" : "#f5f7fb",
      border: `1px solid ${over ? "#f5a3a3" : "#d8e0ef"}`,
      borderRadius: 4,
      boxShadow: "0 2px 6px rgba(0,0,0,0.06)",
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
            <th style={{ padding: "4px 0", width: "20%" }}>Category / Skill</th>
            <th style={{ padding: "4px 0", width: "7%", textAlign: "center" }}
                title="Total ranks from all sources (DP purchase + adolescence + TP)">
              Current Ranks
            </th>
            <th style={{ padding: "4px 0", width: "9%" }}
                title="Stat codes that drive each category's stat bonus, e.g. St/Co/Ag. Per RMSS, stat bonuses apply at the category level only — skills inherit them via category_total.">
              Stat Bonuses
            </th>
            <th style={{ padding: "4px 0", width: "7%" }}>Cost</th>
            <th style={{ padding: "4px 0", width: "10%", textAlign: "center" }}>Buy</th>
            <th style={{ padding: "4px 0", width: "7%", textAlign: "right" }}>DP spent</th>
            <th style={{ padding: "4px 0", width: "7%", textAlign: "right" }}
                title="Numerical stat bonus (category-level only)">
              Stat
            </th>
            <th style={{ padding: "4px 0", width: "7%", textAlign: "right" }}
                title="Profession contribution (category-level only)">
              Class
            </th>
            <th style={{ padding: "4px 0", width: "7%", textAlign: "right" }}
                title="Magical-item / weapon contributions (skill-level only)">
              Item
            </th>
            <th style={{ padding: "4px 0", width: "7%", textAlign: "right" }}>Special</th>
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
        <td style={{ padding: "5px 0", color: c.stat_bonuses ? "#444" : "#bbb",
                       fontSize: 12 }}>
          {c.stat_bonuses || "—"}
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
        <td style={dimCell(c.stat_bonus)}>{fmt(c.stat_bonus)}</td>
        <td style={dimCell(c.class_bonus)}>{fmt(c.class_bonus)}</td>
        {/* Item bonus applies at the skill level only — categories show —. */}
        <td style={{ padding: "5px 0", textAlign: "right", color: "#bbb",
                       fontVariantNumeric: "tabular-nums" }}>—</td>
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
          </td>
          <td style={{ padding: "3px 0", textAlign: "center",
                         fontVariantNumeric: "tabular-nums",
                         color: s.current_ranks === 0 ? "#aaa" : "#222" }}>
            {s.current_ranks}
          </td>
          {/* Stat-bonus codes are a CATEGORY concept per RMSS. */}
          <td style={{ padding: "3px 0", color: "#bbb", fontSize: 11 }}>—</td>
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
          {/* Stat + Class are category-level — skills inherit via category_total. */}
          <td style={{ padding: "3px 0", textAlign: "right",
                         color: "#bbb", fontVariantNumeric: "tabular-nums",
                         fontSize: 11 }}>—</td>
          <td style={{ padding: "3px 0", textAlign: "right",
                         color: "#bbb", fontVariantNumeric: "tabular-nums",
                         fontSize: 11 }}>—</td>
          <td style={dimCell(s.item_bonus, 11)}>{fmt(s.item_bonus)}</td>
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
  const [modalOpen, setModalOpen] = useState(false);

  // Refund mutation for the compact purchased-summary list. Buying lives
  // in the modal; refund is offered both here and in the modal so the
  // player can drop a TP without re-opening the shop.
  const refundM = useMutation({
    mutationFn: (slug: string) => refundTrainingPackage(characterId, slug),
    onSuccess: onChange,
  });

  return (
    <section style={{ marginTop: 16 }}>
      <header style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Training Packages</h3>
        <span style={{ fontSize: 12, color: "#666" }}>
          Cost = profession-specific (or default_cost when no profession entry)
        </span>
      </header>

      {purchased.length > 0 ? (
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
      ) : (
        <p style={{ marginTop: 8, fontSize: 13, color: "#888" }}>
          No training packages purchased yet.
        </p>
      )}

      {refundM.error && (
        <p style={{ color: "crimson", fontSize: 13, marginTop: 6 }}>
          {String(refundM.error)}
        </p>
      )}

      <button
        className="btn"
        style={{ marginTop: 12 }}
        onClick={() => setModalOpen(true)}
      >
        Purchase Training Package
      </button>

      <p style={{ marginTop: 8, fontSize: 12, color: "#888" }}>
        Buying a TP deducts the listed DP from your budget and applies any
        fixed rank grants to the skill list above. Refunding restores the DP
        and removes those ranks.
      </p>

      {modalOpen && (
        <TPPurchaseModal
          characterId={characterId}
          purchased={purchased}
          tpQ={tpQ}
          onChange={onChange}
          onClose={() => {
            // Final reconcile so the skill list reflects everything bought
            // while the modal was open, then dismiss.
            onChange();
            setModalOpen(false);
          }}
        />
      )}
    </section>
  );
}


/**
 * Modal shop for browsing + buying training packages. Buying / refunding
 * fires `onChange` (the parent's invalidateAll) so the allocator query
 * refetches and the skill list behind the modal updates live. Closing
 * reconciles once more and dismisses.
 *
 * Dismissal: the Close button, a click on the backdrop, or the Escape key.
 */
function TPPurchaseModal({
  characterId, purchased, tpQ, onChange, onClose,
}: {
  characterId: number;
  purchased: SkillAllocatorResponse["training_packages_purchased"];
  tpQ: ReturnType<typeof useQuery<TrainingPackagesAvailableResponse>>;
  onChange: () => void;
  onClose: () => void;
}) {
  const [filter, setFilter] = useState("");
  // Slugs whose detail panel is expanded. A Set (not a single slug) so
  // the player can open several packages side-by-side to compare.
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const toggleExpanded = (slug: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug); else next.add(slug);
      return next;
    });

  const buyM = useMutation({
    mutationFn: (slug: string) => purchaseTrainingPackage(characterId, slug),
    onSuccess: onChange,
  });
  const refundM = useMutation({
    mutationFn: (slug: string) => refundTrainingPackage(characterId, slug),
    onSuccess: onChange,
  });

  // Escape-to-close. Registered once; onClose is stable enough (recreated
  // each render but the effect re-binds, which is fine for a key handler).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const owned = new Set(purchased.map((p) => p.slug));
  const options = tpQ.data?.options ?? [];
  const filtered = options.filter((o) =>
    !filter || o.name.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Purchase training package"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        padding: "5vh 16px",
        zIndex: 1000,
      }}
    >
      <div
        // Stop backdrop clicks that land on the dialog from closing it.
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff",
          borderRadius: 8,
          boxShadow: "0 10px 40px rgba(0,0,0,0.25)",
          width: "min(720px, 100%)",
          maxHeight: "90vh",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <header style={{
          display: "flex", alignItems: "baseline", justifyContent: "space-between",
          padding: "14px 18px", borderBottom: "1px solid #eee",
        }}>
          <h3 style={{ margin: 0 }}>Purchase Training Package</h3>
          <span style={{ fontSize: 13, color: "#444" }}>
            {tpQ.data
              ? <><strong>{tpQ.data.dp_remaining}</strong> DP remaining</>
              : null}
          </span>
        </header>

        <div style={{ padding: "12px 18px 0" }}>
          <input
            type="search"
            placeholder="Filter training packages…"
            value={filter}
            autoFocus
            onChange={(e) => setFilter(e.target.value)}
            style={{
              width: "100%", padding: "6px 10px",
              fontSize: 13, border: "1px solid #ccc", borderRadius: 4,
            }}
          />
        </div>

        <div style={{ overflowY: "auto", padding: "8px 18px 0", flex: 1 }}>
          {tpQ.isLoading && <p style={{ color: "#666" }}>Loading training packages…</p>}
          {tpQ.error && <p style={{ color: "crimson" }}>{String(tpQ.error)}</p>}
          {tpQ.data && filtered.length === 0 && (
            <p style={{ color: "#888", fontSize: 13 }}>No training packages match “{filter}”.</p>
          )}
          {tpQ.data && filtered.length > 0 && (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ textAlign: "left", borderBottom: "1px solid #ddd", color: "#666", fontSize: 12 }}>
                  <th style={{ padding: "4px 0", width: 28 }} />
                  <th style={{ padding: "4px 0", width: "38%" }}>Name</th>
                  <th style={{ padding: "4px 0", width: "20%" }}>Source</th>
                  <th style={{ padding: "4px 0", width: "12%", textAlign: "right" }}>Cost (DP)</th>
                  <th style={{ padding: "4px 0", width: "26%" }} />
                </tr>
              </thead>
              <tbody>
                {filtered.map((opt) => (
                  <TPRow
                    key={opt.slug}
                    opt={opt}
                    owned={owned.has(opt.slug)}
                    disabled={buyM.isPending || refundM.isPending}
                    expanded={expanded.has(opt.slug)}
                    onToggle={() => toggleExpanded(opt.slug)}
                    onBuy={() => buyM.mutate(opt.slug)}
                    onRefund={() => refundM.mutate(opt.slug)}
                  />
                ))}
              </tbody>
            </table>
          )}

          {(buyM.error || refundM.error) && (
            <p style={{ color: "crimson", fontSize: 13, marginTop: 6 }}>
              {String(buyM.error ?? refundM.error)}
            </p>
          )}
        </div>

        <footer style={{
          display: "flex", justifyContent: "flex-end", gap: 8,
          padding: "12px 18px", borderTop: "1px solid #eee",
        }}>
          <button className="btn btn-secondary" onClick={onClose}>
            Done
          </button>
        </footer>
      </div>
    </div>
  );
}


function TPRow({
  opt, owned, disabled, expanded, onToggle, onBuy, onRefund,
}: {
  opt: TrainingPackageOption;
  owned: boolean;
  disabled: boolean;
  expanded: boolean;
  onToggle: () => void;
  onBuy: () => void;
  onRefund: () => void;
}) {
  return (
    <>
      <tr style={{ borderBottom: expanded ? "none" : "1px solid #f3f3f3" }}>
        <td style={{ padding: "5px 0" }}>
          <button
            onClick={onToggle}
            aria-expanded={expanded}
            aria-label={expanded ? `Hide ${opt.name} details` : `Show ${opt.name} details`}
            title={expanded ? "Hide details" : "Show details"}
            style={{
              width: 20, height: 20, lineHeight: "18px", textAlign: "center",
              padding: 0, border: "1px solid #ccc", borderRadius: 3,
              background: "#fafafa", cursor: "pointer", fontSize: 13,
              fontFamily: "monospace", color: "#555",
            }}
          >
            {expanded ? "−" : "+"}
          </button>
        </td>
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
      {expanded && (
        <tr style={{ borderBottom: "1px solid #f3f3f3" }}>
          <td />
          <td colSpan={4} style={{ padding: "0 0 12px" }}>
            <div style={{
              background: "#fafafa",
              border: "1px solid #eee",
              borderRadius: 4,
              padding: "8px 12px",
            }}>
              <TPDetailPanel slug={opt.slug} />
            </div>
          </td>
        </tr>
      )}
    </>
  );
}


/**
 * Lazy-loaded detail panel for one TP, shown when its row is expanded
 * in the purchase modal. Fetches the full TP record (description, stat
 * gains, rank assignments, special outfitting) from the catalog
 * endpoint — character-independent, so it caches per-slug and is shared
 * with the standalone TP detail page via TPDetailSections.
 */
function TPDetailPanel({ slug }: { slug: string }) {
  const q = useQuery<TrainingPackageDetail>({
    queryKey: ["training-package", slug],
    queryFn: () => fetchTrainingPackage(slug),
  });

  if (q.isLoading) return <p style={{ margin: 0, color: "#666", fontSize: 13 }}>Loading details…</p>;
  if (q.error) return <p style={{ margin: 0, color: "crimson", fontSize: 13 }}>{String(q.error)}</p>;
  if (!q.data) return null;

  const tp = q.data;
  const hasBody =
    tp.description ||
    tp.stat_gains.length > 0 ||
    tp.rank_assignments.length > 0 ||
    tp.specials.length > 0;

  if (!hasBody) {
    return <p style={{ margin: 0, color: "#888", fontSize: 13 }}>No further details recorded.</p>;
  }
  return <TPDetailSections tp={tp} />;
}


// ----- optimistic update helpers --------------------------------------

/** Walk the cached allocator response, find the category, rebuild it
 *  with the new rank count, and recompute its + each child skill's
 *  totals. This is the optimistic equivalent of the server-side
 *  _build_skill_allocator pass — same math, just over cached data.
 *
 *  `categoryShort` matches what the server expects in `/category-ranks`
 *  body (e.g. "Active", not "Artistic • Active"). The cached row's
 *  `category_name` is the full label, so we strip when comparing. */
function applyCategoryRankChange(
  snap: SkillAllocatorResponse,
  groupName: string,
  categoryShort: string,
  newRanksBought: number,
): SkillAllocatorResponse {
  const nextCategories = snap.categories.map((c) => {
    if (c.group_name !== groupName) return c;
    const short = stripGroupPrefix(c.group_name, c.category_name);
    if (short !== categoryShort) return c;
    return recomputeCategory(c, { ranks_bought: newRanksBought });
  });
  return {
    ...snap,
    budget: recomputeBudget(snap, nextCategories, snap.training_packages_purchased),
    categories: nextCategories,
  };
}

function applySkillRankChange(
  snap: SkillAllocatorResponse,
  groupName: string,
  categoryShort: string,
  skillName: string,
  newRanksBought: number,
): SkillAllocatorResponse {
  const nextCategories = snap.categories.map((c) => {
    if (c.group_name !== groupName) return c;
    const short = stripGroupPrefix(c.group_name, c.category_name);
    if (short !== categoryShort) return c;
    return recomputeCategory(c, { skill: { name: skillName, ranks_bought: newRanksBought } });
  });
  return {
    ...snap,
    budget: recomputeBudget(snap, nextCategories, snap.training_packages_purchased),
    categories: nextCategories,
  };
}

/** Rebuild a SkillCategoryRow with the new rank count (category- and/or
 *  skill-level) applied. Mirrors the math in web/api/characters.py
 *  _build_skill_allocator. */
function recomputeCategory(
  cat: SkillCategoryRow,
  change: { ranks_bought?: number; skill?: { name: string; ranks_bought: number } },
): SkillCategoryRow {
  const nextCatBought = change.ranks_bought ?? cat.ranks_bought;
  // Adolescence-derived ranks are baked into (current_ranks - ranks_bought)
  // on every server snapshot. We preserve that delta when bumping the
  // bought count: new current = (current - bought) + new_bought.
  const catNonDp = cat.current_ranks - cat.ranks_bought;
  const nextCatCurrent = catNonDp + nextCatBought;

  const tokens = cat.cost.split("/").filter((t) => t.trim());
  const nextCatDpSpent = tokens.slice(0, nextCatBought)
                                .map((t) => parseInt(t, 10) || 0)
                                .reduce((a, b) => a + b, 0);
  const nextCatNextRankCost =
    nextCatBought < tokens.length
      ? (parseInt(tokens[nextCatBought], 10) || 0)
      : null;

  // Body Development and Power Point Development are conceptually
  // single-row skills in RMSS. The server puts the race progression
  // on the CATEGORY and a passthrough "0 • 0 • 0 • 0 • 0" on the SKILL,
  // and sums category + skill ranks before applying the progression.
  // Mirror that here so the optimistic UI matches what the server
  // returns after refetch (no flash from 0 to the right number when
  // the user clicks the skill-row +/-).
  const isBodyOrPpDev = cat.skill_progression === "0 • 0 • 0 • 0 • 0";

  // Pre-compute next-skill currentRanks so we can sum them for the
  // race-progression case below.
  const nextSkillCurrents = cat.skills.map((s) => {
    const isTouched = change.skill?.name === s.skill_name;
    const skBought = isTouched ? change.skill!.ranks_bought : s.ranks_bought;
    return s.current_ranks - s.ranks_bought + skBought;
  });
  const effectiveCatRanks = isBodyOrPpDev
    ? nextCatCurrent + nextSkillCurrents.reduce((a, b) => a + b, 0)
    : nextCatCurrent;

  const catRankB = progressionBonus(cat.category_progression, effectiveCatRanks, true);
  const catTotal = Math.round(catRankB + cat.stat_bonus + cat.class_bonus + cat.special_bonus);

  const nextSkills = cat.skills.map((s, i) => {
    const isTouched = change.skill?.name === s.skill_name;
    const skBought = isTouched ? change.skill!.ranks_bought : s.ranks_bought;
    const skCurrent = nextSkillCurrents[i];
    const skRankB = progressionBonus(cat.skill_progression, skCurrent, false);
    // Per RMSS: skill_total = skill_rank_bonus + category_total
    //                       + item_bonus + special_bonus.
    // Stat + Class are absorbed into catTotal; no skill-level stat/class.
    const skTotal = Math.round(skRankB + catTotal + s.item_bonus + s.special_bonus);
    const skDpSpent = tokens.slice(0, skBought)
                              .map((t) => parseInt(t, 10) || 0)
                              .reduce((a, b) => a + b, 0);
    const skNextRankCost =
      skBought < tokens.length
        ? (parseInt(tokens[skBought], 10) || 0)
        : null;
    return {
      ...s,
      ranks_bought: skBought,
      current_ranks: skCurrent,
      dp_spent: skDpSpent,
      next_rank_cost_dp: skNextRankCost,
      total_bonus: skTotal,
      // class/special/stat unchanged from server snapshot.
    } satisfies SkillRow;
  });

  return {
    ...cat,
    ranks_bought: nextCatBought,
    current_ranks: nextCatCurrent,
    dp_spent: nextCatDpSpent,
    next_rank_cost_dp: nextCatNextRankCost,
    total_bonus: catTotal,
    skills: nextSkills,
  };
}

function recomputeBudget(
  snap: SkillAllocatorResponse,
  categories: SkillCategoryRow[],
  tpsPurchased: SkillAllocatorResponse["training_packages_purchased"],
): SkillAllocatorResponse["budget"] {
  let dpSpent = 0;
  for (const c of categories) {
    dpSpent += c.dp_spent;
    for (const s of c.skills) dpSpent += s.dp_spent;
  }
  for (const tp of tpsPurchased) dpSpent += tp.dp_paid;
  return {
    dp_total: snap.budget.dp_total,
    dp_spent: dpSpent,
    dp_remaining: snap.budget.dp_total - dpSpent,
  };
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
