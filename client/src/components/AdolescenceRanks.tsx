import { useQuery } from "@tanstack/react-query";

import {
  fetchCharacterAdolescence,
  type CharacterAdolescence,
} from "../api";

interface Props {
  characterId: number;
  /** The slug of the currently-picked race, used as a render hint so the
   *  panel re-fetches when the picker mutates the character's race. */
  raceSlug: string | null;
}

/**
 * Starting skill ranks granted to a character during adolescence
 * (RMSS T-1.6, keyed by race/culture). Read-only — these come straight
 * from reference data once a race is picked; the future skill DP
 * allocator will let the player layer additional ranks on top.
 */
export function AdolescenceRanks({ characterId, raceSlug }: Props) {
  const q = useQuery<CharacterAdolescence>({
    // raceSlug is in the key so picking a different race triggers a refetch.
    queryKey: ["characters", characterId, "adolescence-ranks", raceSlug],
    queryFn: () => fetchCharacterAdolescence(characterId),
  });

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
          Pick a race above to see the starting skill ranks granted during adolescence.
        </p>
      )}

      {q.data && q.data.culture_slug && (
        <>
          <p style={{ marginTop: 8, fontSize: 13, color: "#666" }}>
            Ranks below are what your character starts with based on{" "}
            <strong>{q.data.culture_name}</strong> race/culture. Each rank reflects
            time spent learning skills before character creation; the skill DP
            allocator (coming later) will let you add more on top.
          </p>
          <RanksTable data={q.data} />
        </>
      )}
    </section>
  );
}

function RanksTable({ data }: { data: CharacterAdolescence }) {
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 12, fontSize: 13 }}>
      <thead>
        <tr style={{ textAlign: "left", borderBottom: "1px solid #ddd", color: "#666", fontSize: 12 }}>
          <th style={{ padding: "4px 0" }}>Skill / Category</th>
          <th style={{ padding: "4px 0", textAlign: "right", width: 80 }}>Ranks</th>
        </tr>
      </thead>
      <tbody>
        {data.groups.map((g, gi) => (
          <GroupRows key={`${g.category}-${gi}`} group={g} />
        ))}
      </tbody>
    </table>
  );
}

function GroupRows({ group }: { group: { category: string; value: string; skills: { name: string; value: string }[] } }) {
  const isSummary = group.category === "Summary";
  const isOther = group.category === "Other";

  return (
    <>
      {/* Category header row — bold, no indent. Summary/Other are synthetic
         buckets so we render their label slightly differently. */}
      <tr style={{ background: isSummary || isOther ? "#fafafa" : "transparent" }}>
        <td style={{
          padding: "5px 0",
          fontWeight: 500,
          color: isSummary || isOther ? "#888" : "#222",
        }}>
          {prettify(group.category)}
        </td>
        <td style={{
          padding: "5px 0",
          textAlign: "right",
          fontVariantNumeric: "tabular-nums",
          color: zero(group.value) ? "#bbb" : "#222",
        }}>
          {zero(group.value) ? "—" : group.value}
        </td>
      </tr>
      {/* Leaf skills indented under their category. */}
      {group.skills.map((s, i) => (
        <tr key={`${group.category}-${s.name}-${i}`} style={{ borderBottom: "1px solid #f3f3f3" }}>
          <td style={{ padding: "3px 0 3px 24px", color: "#444" }}>
            {prettify(s.name)}
          </td>
          <td style={{
            padding: "3px 0",
            textAlign: "right",
            fontVariantNumeric: "tabular-nums",
            color: zero(s.value) ? "#bbb" : "#222",
          }}>
            {zero(s.value) ? "—" : s.value}
          </td>
        </tr>
      ))}
    </>
  );
}

// Trim the boilerplate suffixes T-1.6 uses ("skill category", "skill", etc.)
// to keep the table compact.
function prettify(label: string): string {
  return label
    .replace(/ skill category$/i, "")
    .replace(/ skill$/i, "")
    .trim();
}

// T-1.6 uses "0" for "no starting rank"; render those as em-dashes to
// keep the table visually quiet (only non-zero ranks draw the eye).
function zero(value: string): boolean {
  return value === "" || value === "0";
}
