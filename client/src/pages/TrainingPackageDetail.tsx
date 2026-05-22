import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, useParams } from "react-router-dom";

import {
  fetchTrainingPackage,
  HttpError,
  type TPRankAssignment,
  type TrainingPackageDetail,
} from "../api";

/**
 * One training package, fully expanded.
 *
 * Left column: description + specials + stat gains + rank assignments
 * (matches the RMSS Character Law layout — each TP entry on the page
 * shows what you get).
 *
 * Right column: per-profession DP costs as a filter-able table. The
 * ERA source carries ~60 professions (RMSS Core + Companion);
 * filtering helps narrow to the one a player cares about. Cost
 * column on the list page shows the `default_cost`.
 */
export function TrainingPackageDetailPage() {
  const { slug } = useParams<{ slug: string }>();
  if (!slug) return <Navigate to="/training-packages" replace />;
  return <TrainingPackageView slug={slug} />;
}

function TrainingPackageView({ slug }: { slug: string }) {
  const q = useQuery<TrainingPackageDetail>({
    queryKey: ["training-package", slug],
    queryFn: () => fetchTrainingPackage(slug),
    throwOnError: (e) => !(e instanceof HttpError && e.status === 404),
  });

  if (q.error instanceof HttpError && q.error.status === 404) {
    return (
      <section>
        <p>That training package doesn't exist.</p>
        <Link to="/training-packages">Back to training packages</Link>
      </section>
    );
  }
  if (q.isLoading) return <p>Loading…</p>;
  if (q.error || !q.data) return <p style={{ color: "crimson" }}>{String(q.error)}</p>;

  const tp = q.data;
  return (
    <section>
      <style>{`main { max-width: min(1180px, 96vw); }`}</style>
      <Link to="/training-packages" style={{ fontSize: 13, color: "#666" }}>
        ← Training packages
      </Link>
      <h2 style={{ marginTop: 8 }}>{tp.name}</h2>
      <p style={{ color: "#666", margin: "4px 0 0", fontSize: 13 }}>
        {tp.category}
        {tp.default_cost > 0 && (
          <span style={{ marginLeft: 12 }}>default cost: {tp.default_cost} DP</span>
        )}
      </p>
      <hr />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1.5fr) minmax(0, 1fr)",
          gap: 32,
          alignItems: "start",
        }}
      >
        <div>
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
        </div>

        <div style={{ position: "sticky", top: 16 }}>
          <ProfessionCostTable
            costs={tp.profession_costs}
            defaultCost={tp.default_cost}
          />
        </div>
      </div>
    </section>
  );
}

function RankAssignmentBlock({ ra }: { ra: TPRankAssignment }) {
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

function ProfessionCostTable({
  costs,
  defaultCost,
}: {
  costs: { profession_name: string; cost: number }[];
  defaultCost: number;
}) {
  const [filter, setFilter] = useState("");
  const trimmed = filter.trim().toLowerCase();

  const filtered = useMemo(() => {
    if (!trimmed) return costs;
    return costs.filter((c) => c.profession_name.toLowerCase().includes(trimmed));
  }, [costs, trimmed]);

  // Sort by cost ascending so the cheapest professions float to the top —
  // those are the ones the TP is "intended" for.
  const sorted = useMemo(
    () => filtered.slice().sort((a, b) => a.cost - b.cost),
    [filtered],
  );

  return (
    <div style={{
      border: "1px solid #ddd",
      borderRadius: 4,
      background: "#fafafa",
      padding: "10px 12px",
    }}>
      <h3 style={{ margin: "0 0 6px", fontSize: 14 }}>DP cost per profession</h3>
      <p style={{ margin: "0 0 8px", fontSize: 12, color: "#888" }}>
        Sorted cheapest first. Default {defaultCost} DP applies to unlisted professions.
      </p>
      <input
        type="text"
        placeholder="filter…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        style={{ width: "100%", fontSize: 12, marginBottom: 6 }}
      />
      <div style={{ maxHeight: 480, overflowY: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <tbody>
            {sorted.map((c, i) => (
              <tr key={i} style={{ borderBottom: "1px solid #eee" }}>
                <td style={{ padding: "2px 6px", color: "#333" }}>{c.profession_name}</td>
                <td style={{
                  padding: "2px 6px",
                  textAlign: "right",
                  fontFamily: "monospace",
                  color: c.cost <= defaultCost ? "#222" : "#888",
                  fontWeight: c.cost <= defaultCost ? 600 : 400,
                }}>
                  {c.cost}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
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

const listStyle: React.CSSProperties = {
  margin: 0,
  paddingLeft: 20,
  color: "#333",
  lineHeight: 1.55,
  fontSize: 14,
};
