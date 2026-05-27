import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  applyAdolescenceRanks,
  fetchCharacterAdolescence,
  updateAdolescenceChoices,
  type AdolescenceApplyResult,
  type AdolescenceSkill,
  type CharacterAdolescence,
} from "../api";

interface Props {
  characterId: number;
  /** raceSlug is in the query key so picking a different race triggers a refetch. */
  raceSlug: string | null;
  /** cultureSlug is also in the query key — for umbrella races (Common Men /
   *  Mixed Men) changing the culture sub-pick must re-fetch T-1.6 data. */
  cultureSlug: string | null;
  /** True when the race is one of the RMSS umbrella categories. Drives the
   *  empty-state message: "pick a culture" vs. "pick a race". */
  raceIsUmbrella: boolean;
}

/**
 * Starting skill ranks granted by race/culture during adolescence
 * (RMSS T-1.6). Rows with `choice_kind` set ("text" for Riding, "select"
 * for the 6 "1 Weapon Based on Culture/Race" rows) render an input next
 * to the rank — picks auto-save. The "Apply" button at the bottom
 * transfers the current view into the character's actual skill list
 * (character_skill table, source='adolescence').
 */
export function AdolescenceRanks({
  characterId,
  raceSlug,
  cultureSlug,
  raceIsUmbrella,
}: Props) {
  const qc = useQueryClient();
  const q = useQuery<CharacterAdolescence>({
    queryKey: ["characters", characterId, "adolescence-ranks", raceSlug, cultureSlug],
    queryFn: () => fetchCharacterAdolescence(characterId),
  });

  // Local draft of pending choices — keyed by t16_row. Initialised from
  // the server's saved picks; user edits update local state and we
  // PUT in a debounced batch.
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!q.data) return;
    const next: Record<string, string> = {};
    for (const g of q.data.groups) {
      for (const s of g.skills) {
        if (s.choice_kind != null) {
          next[s.name] = s.choice ?? "";
        }
      }
    }
    setDrafts(next);
  }, [q.data]);

  const saveChoices = useMutation({
    mutationFn: (choices: { t16_row: string; choice: string }[]) =>
      updateAdolescenceChoices(characterId, choices),
    onSuccess: (fresh) => {
      qc.setQueryData(
        ["characters", characterId, "adolescence-ranks", raceSlug, cultureSlug],
        fresh,
      );
    },
  });

  const applyRanks = useMutation({
    mutationFn: () => applyAdolescenceRanks(characterId),
    onSuccess: () => {
      // Refresh character_skill consumers when they show up later.
      qc.invalidateQueries({ queryKey: ["characters", characterId, "skills"] });
    },
  });

  // Persist a single picked row to the server (auto-save on change).
  function commitChoice(t16_row: string, value: string) {
    setDrafts((d) => ({ ...d, [t16_row]: value }));
    saveChoices.mutate([{ t16_row, choice: value }]);
  }

  const allChoiceRows = useMemo(() => {
    if (!q.data) return [] as AdolescenceSkill[];
    return q.data.groups.flatMap((g) =>
      g.skills.filter((s) => s.choice_kind != null),
    );
  }, [q.data]);

  // Count how many specifier rows are still unfilled — the Apply button
  // is enabled regardless (we just skip pending rows), but the count is
  // surfaced so the user can see what's missing.
  const pendingCount = allChoiceRows.filter(
    (s) => !(drafts[s.name] ?? "").trim() && Number(s.value) > 0,
  ).length;

  return (
    <section>
      <header style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Starting skill ranks</h3>
        <span style={{ fontSize: 12, color: "#666" }}>
          RMSS Adolescence Rank Table T-1.6
        </span>
      </header>

      {q.isLoading && <p style={{ color: "#666", marginTop: 12 }}>Loading…</p>}
      {q.error && (
        <p style={{ color: "crimson", fontSize: 13, marginTop: 8 }}>
          {String(q.error)}
        </p>
      )}

      {q.data && q.data.culture_slug === null && (
        <p style={{ marginTop: 12, color: "#888", fontSize: 13 }}>
          Pick a race in Step 2 to see the starting skill ranks granted
          during adolescence.
        </p>
      )}

      {q.data && q.data.culture_slug && q.data.groups.length === 0 && (
        <UmbrellaRaceNotice
          cultureName={q.data.culture_name ?? q.data.culture_slug}
          raceIsUmbrella={raceIsUmbrella}
        />
      )}

      {q.data && q.data.culture_slug && q.data.groups.length > 0 && (
        <>
          <p style={{ marginTop: 8, fontSize: 13, color: "#666" }}>
            Ranks below are what your character starts with as a{" "}
            <strong>{q.data.culture_name}</strong>. Pick a mount for Riding and
            one weapon per weapon category, then click Apply to write these
            into your character's skill list.
          </p>
          <RanksTable
            data={q.data}
            drafts={drafts}
            onChange={commitChoice}
          />

          <div style={{ marginTop: 16, display: "flex", gap: 12, alignItems: "center" }}>
            <button
              className="btn"
              onClick={() => applyRanks.mutate()}
              disabled={applyRanks.isPending}
            >
              {applyRanks.isPending ? "Applying…" : "Apply Adolescent Ranks"}
            </button>
            {pendingCount > 0 && (
              <span style={{ fontSize: 13, color: "#a16207" }}>
                {pendingCount} row{pendingCount === 1 ? "" : "s"} still need a pick — Apply will skip them.
              </span>
            )}
            {applyRanks.error && (
              <span style={{ color: "crimson", fontSize: 13 }}>
                {String(applyRanks.error)}
              </span>
            )}
            <ApplyResultBanner result={applyRanks.data} />
          </div>
        </>
      )}
    </section>
  );
}


/**
 * Shown when the character's race has no T-1.6 row in the source data —
 * Two flavors:
 *   raceIsUmbrella=true  → "you need to pick a culture in Step 2"; the
 *                          Culture sub-picker is already rendered there.
 *   raceIsUmbrella=false → "this race has no T-1.6 data" (e.g. a custom
 *                          race added without source-table entries).
 */
function UmbrellaRaceNotice({
  cultureName,
  raceIsUmbrella,
}: {
  cultureName: string;
  raceIsUmbrella: boolean;
}) {
  return (
    <div
      style={{
        marginTop: 12,
        padding: "12px 16px",
        background: "#fff8e1",
        border: "1px solid #f0d486",
        borderRadius: 4,
        fontSize: 13,
        lineHeight: 1.5,
        color: "#5a4a1a",
      }}
    >
      {raceIsUmbrella ? (
        <>
          <strong>{cultureName}</strong> is an umbrella category in RMSS — the
          Cultures &amp; Races appendix doesn't print T-1.6 adolescence ranks
          for it directly. Pick one of the 7 specific Men cultures from the{" "}
          <strong>Culture</strong> dropdown in Step 2 to see your starting
          skill ranks.
        </>
      ) : (
        <>
          No T-1.6 adolescence data on file for{" "}
          <strong>{cultureName}</strong>. If you expect ranks here, the
          reference data may need a reload.
        </>
      )}
    </div>
  );
}

function ApplyResultBanner({ result }: { result: AdolescenceApplyResult | undefined }) {
  if (!result) return null;
  return (
    <span style={{ fontSize: 13, color: "#16a34a" }}>
      Applied {result.applied} rank{result.applied === 1 ? "" : "s"}.
      {result.skipped_pending.length > 0 && (
        <span style={{ color: "#a16207", marginLeft: 8 }}>
          Skipped {result.skipped_pending.length} pending pick{result.skipped_pending.length === 1 ? "" : "s"}.
        </span>
      )}
    </span>
  );
}

interface TableProps {
  data: CharacterAdolescence;
  drafts: Record<string, string>;
  onChange: (t16_row: string, value: string) => void;
}

function RanksTable({ data, drafts, onChange }: TableProps) {
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 12, fontSize: 13 }}>
      <thead>
        <tr style={{ textAlign: "left", borderBottom: "1px solid #ddd", color: "#666", fontSize: 12 }}>
          <th style={{ padding: "4px 0" }}>Skill / Category</th>
          <th style={{ padding: "4px 0" }}>Specify</th>
          <th style={{ padding: "4px 0", textAlign: "right", width: 60 }}>Ranks</th>
        </tr>
      </thead>
      <tbody>
        {data.groups.map((g, gi) => (
          <GroupRows
            key={`${g.category}-${gi}`}
            group={g}
            drafts={drafts}
            onChange={onChange}
          />
        ))}
      </tbody>
    </table>
  );
}

interface GroupRowsProps {
  group: { category: string; value: string; skills: AdolescenceSkill[] };
  drafts: Record<string, string>;
  onChange: (t16_row: string, value: string) => void;
}

function GroupRows({ group, drafts, onChange }: GroupRowsProps) {
  const isSummary = group.category === "Summary";
  const isOther = group.category === "Other";

  return (
    <>
      <tr style={{ background: isSummary || isOther ? "#fafafa" : "transparent" }}>
        <td style={{
          padding: "5px 0",
          fontWeight: 500,
          color: isSummary || isOther ? "#888" : "#222",
        }}>
          {prettify(group.category)}
        </td>
        <td style={{ padding: "5px 0" }} />
        <td style={{
          padding: "5px 0",
          textAlign: "right",
          fontVariantNumeric: "tabular-nums",
          color: zero(group.value) ? "#bbb" : "#222",
        }}>
          {zero(group.value) ? "—" : group.value}
        </td>
      </tr>
      {group.skills.map((s, i) => (
        <SkillRow
          key={`${group.category}-${s.name}-${i}`}
          skill={s}
          draft={drafts[s.name] ?? ""}
          onChange={onChange}
        />
      ))}
    </>
  );
}

function SkillRow({
  skill,
  draft,
  onChange,
}: {
  skill: AdolescenceSkill;
  draft: string;
  onChange: (t16_row: string, value: string) => void;
}) {
  const hasRank = !zero(skill.value);
  const needsChoice = skill.choice_kind != null && hasRank;
  const isMissing = needsChoice && !draft.trim();

  return (
    <tr style={{ borderBottom: "1px solid #f3f3f3" }}>
      <td style={{ padding: "3px 0 3px 24px", color: "#444" }}>
        {prettify(skill.name)}
      </td>
      <td style={{ padding: "3px 0" }}>
        {skill.choice_kind === "text" && (
          <input
            type="text"
            value={draft}
            placeholder={placeholderFor(skill.name)}
            onChange={(e) => onChange(skill.name, e.target.value)}
            style={{
              width: "85%", maxWidth: 200,
              padding: "3px 6px", fontSize: 13,
              border: `1px solid ${isMissing ? "#dc2626" : "#ccc"}`,
              borderRadius: 3,
            }}
          />
        )}
        {skill.choice_kind === "select" && (
          <select
            value={draft}
            onChange={(e) => onChange(skill.name, e.target.value)}
            style={{
              maxWidth: 200,
              padding: "3px 6px", fontSize: 13,
              border: `1px solid ${isMissing ? "#dc2626" : "#ccc"}`,
              borderRadius: 3,
              background: "white",
            }}
          >
            <option value="">— Pick a weapon —</option>
            {(skill.choice_options ?? []).map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        )}
      </td>
      <td style={{
        padding: "3px 0",
        textAlign: "right",
        fontVariantNumeric: "tabular-nums",
        color: zero(skill.value) ? "#bbb" : "#222",
      }}>
        {zero(skill.value) ? "—" : skill.value}
      </td>
    </tr>
  );
}

function prettify(label: string): string {
  // Strip the bracketed category prefix from weapon rows; the prefix is
  // a loader artefact to disambiguate duplicate row labels. Then drop
  // boilerplate suffixes.
  return label
    .replace(/^\[[^\]]+\]\s*/, "")
    .replace(/ skill category$/i, "")
    .replace(/ skill$/i, "")
    .trim();
}

function placeholderFor(t16_row: string): string {
  if (t16_row.startsWith("Riding")) return "e.g. horses, wolves";
  return "specify";
}

function zero(value: string): boolean {
  return value === "" || value === "0";
}
