import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import {
  fetchTrainingPackages,
  type TrainingPackageRow,
} from "../api";

/**
 * Browse landing for RMSS Character Law training packages.
 *
 * 36 TPs sorted alphabetically with a name filter on top. Each card
 * shows the description, source category, and default DP cost. Clicking
 * a name opens the detail page.
 */
export function TrainingPackagesHomePage() {
  const [filter, setFilter] = useState("");
  const trimmed = filter.trim().toLowerCase();

  const q = useQuery<TrainingPackageRow[]>({
    queryKey: ["training-packages"],
    queryFn: fetchTrainingPackages,
    staleTime: 1000 * 60 * 60,
  });

  const filtered = useMemo(() => {
    const data = q.data ?? [];
    if (!trimmed) return data;
    return data.filter((tp) =>
      tp.name.toLowerCase().includes(trimmed) ||
      tp.description.toLowerCase().includes(trimmed),
    );
  }, [q.data, trimmed]);

  return (
    <section>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0 }}>Training Packages</h2>
        <Link to="/" style={{ fontSize: 13, color: "#666" }}>← Characters</Link>
      </header>

      <p style={{ color: "#666", margin: "4px 0 0", fontSize: 13 }}>
        RMSS Character Law — bundled rank assignments + stat gains + random outfitting
      </p>

      <div style={{ marginTop: 16 }}>
        <label htmlFor="tp-filter">Filter by name or description</label>
        <input
          id="tp-filter"
          type="text"
          placeholder="e.g. knight, magic, scout…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>

      {q.isLoading && <p style={{ marginTop: 16, color: "#666" }}>Loading…</p>}
      {q.error && <p style={{ color: "crimson" }}>{String(q.error)}</p>}

      {q.data && (
        <>
          <p style={{ color: "#888", fontSize: 12, margin: "12px 0 0" }}>
            {filtered.length} of {q.data.length} training packages
          </p>
          <ul style={{ margin: "8px 0 0", padding: 0, listStyle: "none" }}>
            {filtered.map((tp) => (
              <li
                key={tp.slug}
                style={{
                  padding: "10px 0",
                  borderBottom: "1px solid #eee",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                  <Link
                    to={`/training-packages/${tp.slug}`}
                    style={{ fontWeight: 600, color: "#222", fontSize: 15 }}
                  >
                    {tp.name}
                  </Link>
                  <span style={{ color: "#888", fontSize: 12 }}>
                    default {tp.default_cost} DP
                    {tp.category && (
                      <span style={{ marginLeft: 8 }}>· {tp.category}</span>
                    )}
                  </span>
                </div>
                {tp.description && (
                  <p style={{ margin: "4px 0 0", color: "#555", fontSize: 13, lineHeight: 1.5 }}>
                    {truncate(tp.description, 220)}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function truncate(s: string, n: number): string {
  if (s.length <= n) return s;
  return s.slice(0, n).replace(/\s+\S*$/, "") + "…";
}
