import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, useParams } from "react-router-dom";

import {
  fetchTrainingPackage,
  HttpError,
  type TrainingPackageDetail,
} from "../api";
import { TPDetailSections } from "../components/TrainingPackageDetailBody";

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
          <TPDetailSections tp={tp} />
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

