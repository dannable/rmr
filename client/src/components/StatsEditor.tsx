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
            <th style={{ padding: "6px 4px", width: "40%" }}>Stat</th>
            <th style={{ padding: "6px 4px", width: "20%" }}>Temp</th>
            <th style={{ padding: "6px 4px", width: "20%" }}>Potential</th>
            <th style={{ padding: "6px 4px", width: "20%", textAlign: "right" }}>Bonus</th>
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

      <RRPanel rr={q.data.resistance_rolls} />
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
  // Recompute bonus locally so the user gets instant feedback as they type.
  // The server is still the source of truth on save.
  const bonus = basicStatBonusLocal(draft.temp);
  const tempPotentialMismatch = draft.potential < draft.temp;

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
      <td style={{ padding: "6px 4px", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
        {bonus >= 0 ? `+${bonus}` : bonus}
      </td>
    </tr>
  );
}

function RRPanel({ rr }: { rr: CharacterStats["resistance_rolls"] }) {
  const rows: { label: string; value: number; formula: string }[] = [
    { label: "Channeling",      value: rr.channeling,     formula: "3 × In" },
    { label: "Essence",         value: rr.essence,        formula: "3 × Em" },
    { label: "Mentalism",       value: rr.mentalism,      formula: "3 × Pr" },
    { label: "Chan / Ess",      value: rr.chan_ess,       formula: "In + Em" },
    { label: "Chan / Ment",     value: rr.chan_ment,      formula: "In + Pr" },
    { label: "Ess / Ment",      value: rr.ess_ment,       formula: "Em + Pr" },
    { label: "Arcane",          value: rr.arcane,         formula: "Em + In + Pr" },
    { label: "Poison / Disease", value: rr.poison_disease, formula: "3 × Co" },
    { label: "Fear",            value: rr.fear,           formula: "3 × SD" },
  ];

  return (
    <div style={{ marginTop: 24 }}>
      <h4 style={{ margin: 0, fontSize: 14 }}>Resistance Rolls (from saved stats)</h4>
      <p style={{ fontSize: 12, color: "#888", marginTop: 4 }}>
        Updates after you save. Racial RR mods will layer on once race is picked.
      </p>
      <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8, fontSize: 13 }}>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} style={{ borderBottom: "1px solid #f3f3f3" }}>
              <td style={{ padding: "4px 0", width: "40%" }}>{r.label}</td>
              <td style={{ padding: "4px 0", width: "30%", color: "#888" }}>{r.formula}</td>
              <td style={{ padding: "4px 0", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                {r.value}
              </td>
            </tr>
          ))}
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
