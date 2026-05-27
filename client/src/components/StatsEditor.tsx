import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  applyFixedPotentials,
  fetchCharacterStats,
  raisePrimesTo90,
  rollCharacterPotentials,
  STAT_CODES,
  updateCharacterStats,
  type CharacterStats,
  type StatCode,
  type StatRow,
} from "../api";

interface Props {
  characterId: number;
}

// Local working copy: editable temp/potential per code, plus the dirty flag.
type Draft = Record<StatCode, { temp: number; potential: number }>;

/**
 * The five RMSS "Development stats" (Ag, Co, Me, Re, SD) whose temporary
 * values feed the per-level Development Point budget. Mirror of
 * core.chargen.stats.DEV_STAT_CODES — kept in sync manually.
 */
const DEV_STAT_CODE_LIST: readonly StatCode[] = ["Ag", "Co", "Me", "Re", "SD"];
const DEV_STAT_CODES: ReadonlySet<StatCode> = new Set(DEV_STAT_CODE_LIST);

function draftFromServer(rows: StatRow[]): Draft {
  return Object.fromEntries(
    rows.map((r) => [r.code, { temp: r.temp, potential: r.potential }]),
  ) as Draft;
}

export function StatsEditor({ characterId }: Props) {
  const qc = useQueryClient();
  const q = useQuery<CharacterStats>({
    queryKey: ["characters", characterId, "stats"],
    queryFn: () => fetchCharacterStats(characterId),
  });

  const [draft, setDraft] = useState<Draft | null>(null);

  // Initialize / re-init the draft whenever the server data lands.
  useEffect(() => {
    if (q.data) setDraft(draftFromServer(q.data.stats));
  }, [q.data]);

  const m = useMutation({
    mutationFn: () => {
      if (!draft) throw new Error("no draft");
      return updateCharacterStats(
        characterId,
        STAT_CODES.map((code) => ({
          code,
          temp: draft[code].temp,
          potential: draft[code].potential,
        })),
      );
    },
    onSuccess: (fresh) => {
      qc.setQueryData(["characters", characterId, "stats"], fresh);
      setDraft(draftFromServer(fresh.stats));
    },
  });

  const dirty = useMemo(() => {
    if (!q.data || !draft) return false;
    return q.data.stats.some(
      (s) => draft[s.code].temp !== s.temp || draft[s.code].potential !== s.potential,
    );
  }, [q.data, draft]);

  if (q.isLoading || !draft || !q.data) return <p>Loading stats…</p>;
  if (q.error) return <p style={{ color: "crimson" }}>Failed to load stats: {String(q.error)}</p>;

  return (
    <section>
      <header style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Stats</h3>
        <span style={{ fontSize: 12, color: "#666" }}>
          RMSS Basic Stat Bonus Table T-2.1
        </span>
      </header>

      <StatBudgetBanner
        stats={q.data.stats}
        budget={q.data.budget}
        draft={draft}
        savedDevPoints={q.data.development_points}
      />

      <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 12, fontSize: 14 }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "1px solid #ddd" }}>
            <th style={{ padding: "6px 4px", width: "26%" }}>Stat</th>
            <th style={{ padding: "6px 4px", width: "14%" }}>Temp</th>
            <th style={{ padding: "6px 4px", width: "14%" }}>Potential</th>
            <th style={{ padding: "6px 4px", width: "14%", textAlign: "right" }}
                title="T-2.1 basic stat bonus from temp alone, before racial modifier.">
              Stat Bonus
            </th>
            <th style={{ padding: "6px 4px", width: "14%", textAlign: "right" }}
                title="RMSS T-1.1 racial stat modifier. Added to temp before the T-2.1 bonus lookup.">
              Race
            </th>
            <th style={{ padding: "6px 4px", width: "18%", textAlign: "right" }}
                title="Final stat bonus: T-2.1 lookup on (Temp + Race). This is what gets added to all rolls using this stat.">
              Total
            </th>
          </tr>
        </thead>
        <tbody>
          {q.data.stats.map((row) => (
            <StatInputRow
              key={row.code}
              row={row}
              draft={draft[row.code]}
              isDevStat={DEV_STAT_CODES.has(row.code)}
              onChange={(next) =>
                setDraft((d) => (d ? { ...d, [row.code]: next } : d))
              }
            />
          ))}
        </tbody>
      </table>

      <div style={{ marginTop: 16, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <button
          className="btn"
          onClick={() => m.mutate()}
          disabled={!dirty || m.isPending}
        >
          {m.isPending ? "Saving…" : "Save stats"}
        </button>
        {dirty && (
          <button
            className="btn btn-secondary"
            onClick={() => setDraft(draftFromServer(q.data!.stats))}
            disabled={m.isPending}
          >
            Discard changes
          </button>
        )}
        {!dirty && !m.isPending && q.dataUpdatedAt > 0 && (
          <span style={{ fontSize: 13, color: "#666" }}>All changes saved.</span>
        )}
        {m.error && (
          <span style={{ color: "crimson", fontSize: 13 }}>
            {String(m.error)}
          </span>
        )}
      </div>

      <StatActionsRow
        characterId={characterId}
        hasPrimesBelow90={q.data.stats.some((s) => s.is_prime && (draft[s.code]?.temp ?? s.temp) < q.data!.budget.prime_min)}
      />

      <RRPanel rr={q.data.resistance_rolls} raceMods={q.data.race_rr_mods} />
    </section>
  );
}


/**
 * Quick-action row beneath the stats grid: roll potentials (RMSS T-1.3
 * dice formulas), apply Fixed Mod (the alternative footnote on T-1.3),
 * and raise prime stats to 90 (RMSS-required minimum for primes).
 *
 * Each action mutates server state and invalidates the cached stats
 * query so the editor re-renders against the new authoritative values.
 */
function StatActionsRow({
  characterId,
  hasPrimesBelow90,
}: {
  characterId: number;
  hasPrimesBelow90: boolean;
}) {
  const qc = useQueryClient();
  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["characters", characterId, "stats"] });

  const rollM = useMutation({
    mutationFn: () => rollCharacterPotentials(characterId),
    onSuccess: invalidate,
  });
  const fixedM = useMutation({
    mutationFn: () => applyFixedPotentials(characterId),
    onSuccess: invalidate,
  });
  const primeM = useMutation({
    mutationFn: () => raisePrimesTo90(characterId),
    onSuccess: invalidate,
  });

  const busy = rollM.isPending || fixedM.isPending || primeM.isPending;
  return (
    <div style={{
      marginTop: 12,
      display: "flex",
      gap: 8,
      alignItems: "center",
      flexWrap: "wrap",
      fontSize: 13,
    }}>
      <button
        type="button"
        className="btn btn-secondary"
        onClick={() => rollM.mutate()}
        disabled={busy}
        title="Roll each potential per RMSS T-1.3 dice formulas"
        style={{ padding: "4px 10px" }}
      >
        {rollM.isPending ? "Rolling…" : "🎲 Roll potentials"}
      </button>
      <button
        type="button"
        className="btn btn-secondary"
        onClick={() => fixedM.mutate()}
        disabled={busy}
        title="Apply T-1.3 Fixed Mod (the no-dice alternative)"
        style={{ padding: "4px 10px" }}
      >
        {fixedM.isPending ? "Applying…" : "Apply fixed mod"}
      </button>
      <button
        type="button"
        className="btn btn-secondary"
        onClick={() => primeM.mutate()}
        disabled={busy || !hasPrimesBelow90}
        title="Bump each prime stat below 90 up to 90"
        style={{ padding: "4px 10px" }}
      >
        {primeM.isPending ? "Raising…" : "Raise primes to 90"}
      </button>
      {(rollM.error || fixedM.error || primeM.error) && (
        <span style={{ color: "crimson" }}>
          {String(rollM.error || fixedM.error || primeM.error)}
        </span>
      )}
    </div>
  );
}

function StatInputRow({
  row,
  draft,
  isDevStat,
  onChange,
}: {
  row: StatRow;
  draft: { temp: number; potential: number };
  /** When true, paints the row with a grey background to visually group
   *  the 5 Development stats (Ag, Co, Me, Re, SD) that feed the DP pool. */
  isDevStat: boolean;
  onChange: (next: { temp: number; potential: number }) => void;
}) {
  // Three displayed bonuses, all computed locally so they update live as
  // the user types. The server is still the source of truth on save.
  //   * statBonus = T-2.1(temp)               — bonus from temp alone
  //   * race      = row.race_mod              — racial stat-bonus modifier (T-1.1)
  //   * total     = statBonus + race_mod      — RMSS T-1.1: race mods apply
  //                                             to the bonus, not the stat
  const statBonus = basicStatBonusLocal(draft.temp);
  const total = statBonus + row.race_mod;
  const tempPotentialMismatch = draft.potential < draft.temp;
  const raceTitle = row.race_mod !== 0
    ? `T-2.1(${draft.temp}) = ${fmt(statBonus)}; race ${fmt(row.race_mod)} → ${fmt(total)}`
    : undefined;
  const totalTitle = `T-2.1(${draft.temp}) = ${fmt(statBonus)}${row.race_mod ? ` + race ${fmt(row.race_mod)}` : ""} = ${fmt(total)}`;

  const nextTier = nextBonusTier(draft.temp);

  // Grey-stripe the 5 development stats (Ag, Co, Me, Re, SD) to visually
  // tie them to the DP banner. Subtle — same hue as the budget banner so
  // the eye groups them without making the editor feel busy.
  const rowBg = isDevStat ? "#f3f4f6" : undefined;

  return (
    <tr style={{ borderBottom: "1px solid #f3f3f3", background: rowBg }}>
      <td style={{ padding: "6px 4px" }}>
        <span style={{ fontWeight: 500 }}>
          {row.name}
          {row.is_prime && (
            <span style={{
              marginLeft: 4,
              color: "#16a34a",
              fontSize: 10,
              verticalAlign: "super",
            }} title="Profession prime stat">★</span>
          )}
        </span>
        <span style={{ color: "#888", marginLeft: 6, fontSize: 12 }}>{row.code}</span>
      </td>
      <td style={{ padding: "6px 4px" }}>
        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
          <input
            type="number"
            min={1}
            max={102}
            value={draft.temp}
            onChange={(e) =>
              onChange({ ...draft, temp: clamp(parseInt(e.target.value, 10) || 0) })
            }
            style={{ width: 64, padding: "4px 6px" }}
          />
          <button
            type="button"
            onClick={() => nextTier !== null && onChange({ ...draft, temp: nextTier })}
            disabled={nextTier === null}
            title={nextTier !== null
              ? `Raise to ${nextTier} (next T-2.1 bonus tier)`
              : "Already at the top T-2.1 tier"}
            style={{
              padding: "2px 6px",
              fontSize: 11,
              border: "1px solid #ccc",
              borderRadius: 3,
              background: "white",
              cursor: nextTier === null ? "default" : "pointer",
              color: nextTier === null ? "#999" : "#446",
            }}
          >
            +tier
          </button>
        </div>
      </td>
      <td style={{ padding: "6px 4px" }}>
        <input
          type="number"
          min={1}
          max={102}
          value={draft.potential}
          onChange={(e) =>
            onChange({ ...draft, potential: clamp(parseInt(e.target.value, 10) || 0) })
          }
          style={{
            width: 64,
            padding: "4px 6px",
            borderColor: tempPotentialMismatch ? "#dc2626" : undefined,
          }}
          title={tempPotentialMismatch ? "Potential is usually >= temp" : undefined}
        />
      </td>
      <td
        style={{
          padding: "6px 4px",
          textAlign: "right",
          fontVariantNumeric: "tabular-nums",
          color: "#666",
        }}
      >
        {fmt(statBonus)}
      </td>
      <td
        style={{
          padding: "6px 4px",
          textAlign: "right",
          fontVariantNumeric: "tabular-nums",
          color: row.race_mod === 0 ? "#aaa" : (row.race_mod > 0 ? "#16a34a" : "#dc2626"),
        }}
        title={raceTitle}
      >
        {row.race_mod === 0 ? "—" : fmt(row.race_mod)}
      </td>
      <td
        style={{
          padding: "6px 4px",
          textAlign: "right",
          fontVariantNumeric: "tabular-nums",
          fontWeight: 500,
        }}
        title={totalTitle}
      >
        {fmt(total)}
      </td>
    </tr>
  );
}

// Format a signed integer as "+N" / "-N" / "0".
function fmt(n: number): string {
  if (n === 0) return "0";
  return n > 0 ? `+${n}` : `${n}`;
}

function RRPanel({
  rr,
  raceMods,
}: {
  rr: CharacterStats["resistance_rolls"];
  raceMods: CharacterStats["race_rr_mods"];
}) {
  type Key = keyof CharacterStats["resistance_rolls"];
  const rows: { label: string; key: Key; formula: string }[] = [
    { label: "Channeling",       key: "channeling",     formula: "3 × In" },
    { label: "Essence",          key: "essence",        formula: "3 × Em" },
    { label: "Mentalism",        key: "mentalism",      formula: "3 × Pr" },
    { label: "Chan / Ess",       key: "chan_ess",       formula: "In + Em" },
    { label: "Chan / Ment",      key: "chan_ment",      formula: "In + Pr" },
    { label: "Ess / Ment",       key: "ess_ment",       formula: "Em + Pr" },
    { label: "Arcane",           key: "arcane",         formula: "Em + In + Pr" },
    { label: "Poison / Disease", key: "poison_disease", formula: "3 × Co" },
    { label: "Fear",             key: "fear",           formula: "3 × SD" },
  ];

  return (
    <div style={{ marginTop: 24 }}>
      <h4 style={{ margin: 0, fontSize: 14 }}>Resistance Rolls (from saved stats)</h4>
      <p style={{ fontSize: 12, color: "#888", marginTop: 4 }}>
        Stat-derived <strong>base</strong> + race <strong>RR mods</strong> = total. Updates after Save.
      </p>
      <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8, fontSize: 13 }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "1px solid #ddd", color: "#666", fontSize: 12 }}>
            <th style={{ padding: "4px 0" }}>RR</th>
            <th style={{ padding: "4px 0" }}>Formula</th>
            <th style={{ padding: "4px 0", textAlign: "right" }}>Base</th>
            <th style={{ padding: "4px 0", textAlign: "right" }}>Race</th>
            <th style={{ padding: "4px 0", textAlign: "right" }}>Total</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const total = rr[r.key];
            const race = raceMods[r.key];
            const base = total - race;
            return (
              <tr key={r.label} style={{ borderBottom: "1px solid #f3f3f3" }}>
                <td style={{ padding: "4px 0" }}>{r.label}</td>
                <td style={{ padding: "4px 0", color: "#888" }}>{r.formula}</td>
                <td style={{
                  padding: "4px 0", textAlign: "right",
                  fontVariantNumeric: "tabular-nums", color: "#666",
                }}>
                  {base}
                </td>
                <td style={{
                  padding: "4px 0", textAlign: "right",
                  fontVariantNumeric: "tabular-nums",
                  color: race === 0 ? "#aaa" : (race > 0 ? "#16a34a" : "#dc2626"),
                }}>
                  {race === 0 ? "—" : fmt(race)}
                </td>
                <td style={{
                  padding: "4px 0", textAlign: "right",
                  fontVariantNumeric: "tabular-nums", fontWeight: 500,
                }}>
                  {total}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---- helpers -----------------------------------------------------------

function clamp(n: number): number {
  if (!Number.isFinite(n)) return 1;
  return Math.max(1, Math.min(102, Math.trunc(n)));
}

/**
 * Mirror of RMSS T-2.1 used for live "as you type" bonus preview only —
 * the server recomputes from authoritative storage on save. Keeping this
 * tiny lookup in sync with core/chargen/stats.py is a known duplication;
 * the alternative is a debounced server call per keystroke.
 */
function basicStatBonusLocal(stat: number): number {
  if (stat >= 102) return (stat - 95) * 2;
  if (stat === 101) return 12;
  if (stat === 100) return 10;
  if (stat >= 98) return 9;
  if (stat >= 96) return 8;
  if (stat >= 94) return 7;
  if (stat >= 92) return 6;
  if (stat >= 90) return 5;
  if (stat >= 85) return 4;
  if (stat >= 80) return 3;
  if (stat >= 75) return 2;
  if (stat >= 70) return 1;
  if (stat >= 31) return 0;
  if (stat >= 26) return -1;
  if (stat >= 21) return -2;
  if (stat >= 16) return -3;
  if (stat >= 11) return -4;
  if (stat === 10) return -5;
  if (stat >= 8) return -6;
  if (stat >= 6) return -7;
  if (stat >= 4) return -8;
  if (stat >= 2) return -9;
  return -10;
}


/**
 * Local mirror of core.chargen.stats.stat_cost (RMSS T-1.2). Kept in
 * sync with the server-side table so the SPA can recompute spent
 * points live as the user types.
 */
/**
 * RMSS T-2.1 bonus-tier thresholds (the LOW edge of each band where the
 * printed bonus increases). The "+tier" button raises a stat to the
 * next entry strictly greater than its current value. Kept in sync with
 * core.chargen.stats.STAT_BONUS_TIERS — see that constant for the
 * source-of-truth list.
 */
const BONUS_TIERS = [
  1, 2, 4, 6, 8, 10, 11, 16, 21, 26, 31,
  70, 75, 80, 85, 90, 91, 92, 94, 96, 98, 100, 101, 102,
];

function nextBonusTier(value: number): number | null {
  for (const t of BONUS_TIERS) {
    if (t > value) return t;
  }
  return null;
}


function statCostLocal(value: number): number {
  if (value < 1) return 0;
  if (value <= 90) return value;
  const ramp: Record<number, number> = {
    91: 92, 92: 94, 93: 97, 94: 100, 95: 104,
    96: 108, 97: 113, 98: 118, 99: 124, 100: 130,
  };
  if (value <= 100) return ramp[value];
  return 130 + (value - 100) * 8;
}


function StatBudgetBanner({
  stats,
  budget,
  draft,
  savedDevPoints,
}: {
  stats: import("../api").StatRow[];
  budget: import("../api").StatsBudget;
  draft: Draft;
  /** Server-confirmed DP from the last save; rendered alongside the live
   *  draft DP so the user can tell when the draft is ahead of the server. */
  savedDevPoints: number;
}) {
  // Live recompute from the draft so the counter updates as the user
  // types, without waiting for a server round-trip.
  const spent = stats.reduce(
    (s, row) => s + statCostLocal(draft[row.code]?.temp ?? row.temp),
    0,
  );
  const remaining = budget.budget - spent;
  const overBudget = remaining < 0;

  // Prime stat warnings: any prime stat that's below the RMSS minimum.
  const primeWarnings = stats
    .filter((s) => s.is_prime && (draft[s.code]?.temp ?? s.temp) < budget.prime_min)
    .map((s) => s.code);

  // Development Points: (Ag + Co + Me + Re + SD) ÷ 5, rounded half-up.
  // Mirror of core.chargen.stats.development_points; recomputed live
  // from the draft so the badge updates as the user types.
  const devSum = DEV_STAT_CODE_LIST.reduce(
    (s, code) => s + (draft[code]?.temp ?? 0),
    0,
  );
  const devPoints = Math.floor((devSum + 2) / 5);
  const devDrifted = devPoints !== savedDevPoints;

  return (
    <div
      style={{
        marginTop: 8,
        padding: "8px 12px",
        background: overBudget ? "#fff4f4" : "#f5f7fb",
        border: `1px solid ${overBudget ? "#f5a3a3" : "#d8e0ef"}`,
        borderRadius: 4,
        fontSize: 13,
        display: "flex",
        gap: 16,
        flexWrap: "wrap",
        alignItems: "center",
      }}
    >
      <span>
        <strong>RMSS T-1.2 budget:</strong>{" "}
        <span style={{ color: overBudget ? "#c00" : "#222", fontVariantNumeric: "tabular-nums" }}>
          {spent} / {budget.budget}
        </span>
        {remaining > 0 && (
          <span style={{ color: "#666", marginLeft: 6 }}>
            ({remaining} unspent)
          </span>
        )}
        {overBudget && (
          <span style={{ color: "#c00", marginLeft: 6 }}>
            ({-remaining} over)
          </span>
        )}
      </span>
      <span
        title="Development Points per level = (Ag + Co + Me + Re + SD) ÷ 5, rounded normally. The five Development stats are highlighted in the table below."
        style={{ fontVariantNumeric: "tabular-nums" }}
      >
        <strong>DPs / level:</strong>{" "}
        <span style={{ color: "#222", fontWeight: 600 }}>{devPoints}</span>
        <span style={{ color: "#888", marginLeft: 6, fontSize: 12 }}>
          ({devSum} ÷ 5)
        </span>
        {devDrifted && (
          <span
            style={{ color: "#a16207", marginLeft: 6, fontSize: 12 }}
            title={`Saved: ${savedDevPoints}. Save your changes to confirm.`}
          >
            • saved {savedDevPoints}
          </span>
        )}
      </span>
      {budget.prime_stats.length > 0 && (
        <span style={{ color: primeWarnings.length > 0 ? "#c00" : "#666" }}>
          Primes ({budget.prime_stats.join(", ")}) must be ≥ {budget.prime_min}
          {primeWarnings.length > 0 && (
            <span style={{ fontWeight: 600 }}>
              {" "}— below: {primeWarnings.join(", ")}
            </span>
          )}
        </span>
      )}
    </div>
  );
}
