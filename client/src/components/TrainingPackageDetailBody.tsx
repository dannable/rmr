import type { ReactNode } from "react";

import type { TPRankAssignment, TrainingPackageDetail } from "../api";

/**
 * Shared renderer for the "what you get" portion of a training package —
 * description, stat gains, rank assignments, and the random-outfitting
 * (Specials) table.
 *
 * Used by both the full TP detail page (pages/TrainingPackageDetail.tsx)
 * and the inline expand panel inside the Step 6 purchase modal
 * (components/SkillAllocator.tsx). Keeping it in one place means the two
 * surfaces never drift.
 *
 * The per-profession DP cost table is intentionally NOT here — that's a
 * page-only affordance; the purchase modal already shows the character's
 * own effective cost on each row.
 */
export function TPDetailSections({ tp }: { tp: TrainingPackageDetail }) {
  return (
    <>
      {tp.description && (
        <p style={{ marginTop: 0, color: "#444", lineHeight: 1.5, fontSize: 14 }}>
          {tp.description}
        </p>
      )}

      {tp.stat_gains.length > 0 && (
        <Section label="Stat gains">
          <ul style={listStyle}>
            {tp.stat_gains.map((sg, i) => (
              <li key={i}>
                {sg.stat_code !== null
                  ? <><strong>+{sg.stat_code}</strong> <span style={{ color: "#888" }}>(guaranteed)</span></>
                  : <>Pick one: <strong>{sg.choices.join(" · ")}</strong></>}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {tp.rank_assignments.length > 0 && (
        <Section label="Rank assignments">
          <ol style={{ ...listStyle, paddingLeft: 24 }}>
            {tp.rank_assignments.map((ra, i) => (
              <li key={i} style={{ marginBottom: 8 }}>
                <RankAssignmentBlock ra={ra} />
              </li>
            ))}
          </ol>
        </Section>
      )}

      {tp.specials.length > 0 && (
        <Section label="Random outfitting (Specials)">
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <tbody>
              {tp.specials.map((sp, i) => (
                <tr key={i} style={{ borderBottom: "1px solid #f3f3f3" }}>
                  <td style={{ padding: "3px 6px", color: "#666", fontFamily: "monospace", width: 50 }}>
                    {sp.chance}%
                  </td>
                  <td style={{ padding: "3px 6px", color: "#333" }}>
                    {sp.description}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}
    </>
  );
}

export function RankAssignmentBlock({ ra }: { ra: TPRankAssignment }) {
  const targetLabel = ra.reference_label
    ? <em>{ra.reference_label}</em>
    : (ra.group_name && ra.category_name
        ? <span><strong>{ra.group_name}</strong> / {ra.category_name}</span>
        : <em>(unspecified)</em>);

  const ranks: string[] = [];
  if (ra.cat_ranks)   ranks.push(`${ra.cat_ranks} category rank${ra.cat_ranks === 1 ? "" : "s"}`);
  if (ra.skill_ranks) ranks.push(`${ra.skill_ranks} skill rank${ra.skill_ranks === 1 ? "" : "s"}`);

  return (
    <div style={{ fontSize: 13, lineHeight: 1.55 }}>
      <div>
        {targetLabel}
        {ranks.length > 0 && (
          <span style={{ color: "#666" }}>: {ranks.join(", ")}</span>
        )}
      </div>
      {ra.category_options.length > 0 && (
        <div style={{ color: "#666", paddingLeft: 12 }}>
          Pick from: {ra.category_options
            .map((c) => `${c.group_name}/${c.category_name}`)
            .join(", ")}
        </div>
      )}
      {ra.skill_options.length > 0 && (
        <div style={{ color: "#666", paddingLeft: 12 }}>
          Specific skill{ra.skill_options.length === 1 ? "" : "s"}:{" "}
          {ra.skill_options
            .map((s) => `${s.skill_name} (${s.classification})`)
            .join(", ")}
        </div>
      )}
      {(ra.cat_spread_max || ra.skill_spread_max || ra.ranks_assigned_max) && (
        <div style={{ color: "#888", paddingLeft: 12, fontSize: 12 }}>
          {ra.cat_spread_max ? `at most ${ra.cat_spread_max} category${ra.cat_spread_max === 1 ? "" : "s"}` : ""}
          {ra.cat_spread_max && (ra.skill_spread_max || ra.ranks_assigned_max) ? " · " : ""}
          {ra.skill_spread_max ? `at most ${ra.skill_spread_max} skill${ra.skill_spread_max === 1 ? "" : "s"}` : ""}
          {ra.skill_spread_max && ra.ranks_assigned_max ? " · " : ""}
          {ra.ranks_assigned_max ? `max ${ra.ranks_assigned_max} ranks per skill` : ""}
        </div>
      )}
    </div>
  );
}

export function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div style={{ marginTop: 18 }}>
      <h3 style={{
        margin: "0 0 8px",
        fontSize: 13,
        textTransform: "uppercase",
        letterSpacing: 0.3,
        color: "#444",
      }}>
        {label}
      </h3>
      {children}
    </div>
  );
}

export const listStyle: React.CSSProperties = {
  margin: 0,
  paddingLeft: 20,
  color: "#333",
  lineHeight: 1.55,
  fontSize: 14,
};
