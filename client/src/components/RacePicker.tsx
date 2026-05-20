import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchRaces,
  STAT_CODES,
  updateCharacterRace,
  type Character,
  type Race,
} from "../api";

interface Props {
  character: Character;
}

/**
 * Race picker for the chargen wizard.
 *
 * Lives below the stats editor on CharacterDetail. Picking a race PUTs the
 * slug to /api/v1/characters/:id/race, then we invalidate the character +
 * stats queries so the StatsEditor refetches with race_mod populated.
 *
 * The picker also previews the chosen race's stat / RR mods + progression
 * data inline, before commit, so the user can compare options without a
 * round-trip.
 */
export function RacePicker({ character }: Props) {
  const qc = useQueryClient();
  // Local draft = the slug currently visible in the dropdown. Starts at
  // whatever's saved; user picks a different race, then hits "Save".
  const [draft, setDraft] = useState<string | null>(character.race_slug);

  const racesQ = useQuery<Race[]>({
    queryKey: ["races"],
    queryFn: fetchRaces,
    // Race reference data rarely changes; one fetch per session is fine.
    staleTime: 1000 * 60 * 60,
  });

  const m = useMutation({
    mutationFn: (slug: string | null) =>
      updateCharacterRace(character.character_id, slug),
    onSuccess: (updated) => {
      qc.setQueryData(["characters", character.character_id], updated);
      qc.invalidateQueries({ queryKey: ["characters", character.character_id, "stats"] });
      qc.invalidateQueries({ queryKey: ["characters"] });
      setDraft(updated.race_slug);
    },
  });

  const racesByName = useMemo(
    () => (racesQ.data ?? []).slice().sort((a, b) => a.name.localeCompare(b.name)),
    [racesQ.data],
  );

  const draftRace = useMemo(
    () => (racesQ.data ?? []).find((r) => r.slug === draft) ?? null,
    [racesQ.data, draft],
  );

  const dirty = draft !== character.race_slug;

  return (
    <section>
      <header style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Race</h3>
        <span style={{ fontSize: 12, color: "#666" }}>
          RMSS Race Abilities Table T-1.1
        </span>
      </header>

      <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center" }}>
        <select
          value={draft ?? ""}
          onChange={(e) => setDraft(e.target.value || null)}
          disabled={racesQ.isLoading || m.isPending}
          style={{
            flex: 1,
            padding: "6px 8px",
            fontSize: 14,
            border: "1px solid #ccc",
            borderRadius: 4,
            background: "white",
          }}
        >
          <option value="">— Pick a race —</option>
          {racesByName.map((r) => (
            <option key={r.slug} value={r.slug}>{r.name}</option>
          ))}
        </select>
        <button
          className="btn"
          onClick={() => m.mutate(draft)}
          disabled={!dirty || m.isPending}
        >
          {m.isPending ? "Saving…" : (draft === null ? "Clear" : "Save")}
        </button>
      </div>

      {m.error && (
        <p style={{ color: "crimson", fontSize: 13, marginTop: 8 }}>
          {String(m.error)}
        </p>
      )}
      {racesQ.error && (
        <p style={{ color: "crimson", fontSize: 13, marginTop: 8 }}>
          Failed to load races: {String(racesQ.error)}
        </p>
      )}

      {draftRace && <RacePreview race={draftRace} />}
    </section>
  );
}

function RacePreview({ race }: { race: Race }) {
  // Helper: format an integer mod as +N / -N / —.
  const mod = (n: number) => (n === 0 ? "—" : n > 0 ? `+${n}` : `${n}`);
  const modColor = (n: number) =>
    n === 0 ? "#aaa" : n > 0 ? "#16a34a" : "#dc2626";

  return (
    <div style={{ marginTop: 16, fontSize: 13 }}>
      <h4 style={{ margin: "0 0 8px", fontSize: 14 }}>{race.name} — modifiers</h4>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div>
          <div style={{ color: "#888", fontSize: 12, marginBottom: 4 }}>STAT MODS</div>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <tbody>
              {STAT_CODES.map((code) => {
                const v = race.stat_mods[code];
                return (
                  <tr key={code}>
                    <td style={{ padding: "2px 4px", color: "#444" }}>{code}</td>
                    <td
                      style={{
                        padding: "2px 4px",
                        textAlign: "right",
                        fontVariantNumeric: "tabular-nums",
                        color: modColor(v),
                      }}
                    >
                      {mod(v)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div>
          <div style={{ color: "#888", fontSize: 12, marginBottom: 4 }}>RR MODS</div>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <tbody>
              {(
                [
                  ["Channeling",     race.rr_mods.channeling],
                  ["Essence",        race.rr_mods.essence],
                  ["Mentalism",      race.rr_mods.mentalism],
                  ["Chan / Ess",     race.rr_mods.chan_ess],
                  ["Chan / Ment",    race.rr_mods.chan_ment],
                  ["Ess / Ment",     race.rr_mods.ess_ment],
                  ["Arcane",         race.rr_mods.arcane],
                  ["Poison/Disease", race.rr_mods.poison_disease],
                  ["Fear",           race.rr_mods.fear],
                ] as const
              ).map(([label, v]) => (
                <tr key={label}>
                  <td style={{ padding: "2px 4px", color: "#444" }}>{label}</td>
                  <td
                    style={{
                      padding: "2px 4px",
                      textAlign: "right",
                      fontVariantNumeric: "tabular-nums",
                      color: modColor(v),
                    }}
                  >
                    {mod(v)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div style={{ marginTop: 12, color: "#666", fontSize: 12, lineHeight: 1.7 }}>
        <div><strong>Background opts:</strong> {race.bg_opts}</div>
        <div><strong>Body Dev DP cost:</strong> {race.body_dev_prog}</div>
        <div><strong>Channeling PP cost:</strong> {race.chan_pp_prog}</div>
        <div><strong>Essence PP cost:</strong> {race.ess_pp_prog}</div>
        <div><strong>Mentalism PP cost:</strong> {race.ment_pp_prog}</div>
      </div>
    </div>
  );
}
