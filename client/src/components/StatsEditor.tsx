import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchCharacterStats,
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
              onChange={(next) =>
                setDraft((d) => (d ? { ...d, [row.code]: next } : d))
              }
            />
          ))}
        </tbody>
      </table>

      <div style={{ marginTop: 16, display: "flex", gap: 8, alignItems: "center" }}>
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

      <RRPanel rr={q.data.resistance_rolls} raceMods={q.data.race_rr_mods} />
    </section>
  );
}

function StatInputRow({
  row,
  draft,
  onChange,
}: {
  row: StatRow;
  draft: { temp: number; potential: number };
  onChange: (next: { temp: number; potential: number }) => void;
}) {
  // Three displayed bonuses, all computed locally so they update live as
  // the user types. The server is still the source of truth on save.
  //   * statBonus = T-2.1(temp)              — bonus from temp alone
  //   * race      = row.race_mod             — racial stat modifier (T-1.1)
  //   * total     = T-2.1(temp + race_mod)   — final stat bonus used in play
  // Note: race is a modifier to the STAT, not to the bonus, so total can
  // differ from statBonus by more or less than `race` depending on which
  // T-2.1 bands the temp and effective temp fall into.
  const effectiveTemp = draft.temp + row.race_mod;
  const statBonus = basicStatBonusLocal(draft.temp);
  const total = basicStatBonusLocal(effectiveTemp);
  const tempPotentialMismatch = draft.potential < draft.temp;
  const raceTitle = row.race_mod !== 0
    ? `Effective stat: ${draft.temp} ${row.race_mod >= 0 ? "+" : "−"} ${Math.abs(row.race_mod)} = ${effectiveTemp}`
    : undefined;
  const totalTitle = row.race_mod !== 0
    ? `T-2.1(${draft.temp}) = ${fmt(statBonus)};  T-2.1(${effectiveTemp}) = ${fmt(total)}`
    : `T-2.1(${draft.temp}) = ${fmt(total)}`;

  return (
    <tr style={{ borderBottom: "1px solid #f3f3f3" }}>
      <td style={{ padding: "6px 4px" }}>
        <span style={{ fontWeight: 500 }}>{row.name}</span>
        <span style={{ color: "#888", marginLeft: 6, fontSize: 12 }}>{row.code}</span>
      </td>
      <td style={{ padding: "6px 4px" }}>
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
