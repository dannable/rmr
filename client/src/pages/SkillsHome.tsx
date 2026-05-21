import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import {
  fetchSkillGroups,
  searchSkills,
  type SkillGroupRow,
  type SkillSearchHit,
} from "../api";

/**
 * Catalog landing for RMSS Appendix A-1 (the Skills appendix). Two
 * entry points:
 *   1. Search box (top) — name substring search across every skill.
 *   2. Group list — all 34 skill-category-groups, in A-1.X order.
 */
export function SkillsHomePage() {
  const [q, setQ] = useState("");
  const trimmed = q.trim();

  return (
    <section>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0 }}>Skills</h2>
        <Link to="/" style={{ fontSize: 13, color: "#666" }}>← Characters</Link>
      </header>

      <div style={{ marginTop: 16 }}>
        <label htmlFor="skill-search">Search by skill name</label>
        <input
          id="skill-search"
          type="text"
          placeholder="e.g. climbing, alertness, swimming…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      {trimmed.length >= 2 ? <SearchResults query={trimmed} /> : <GroupList />}
    </section>
  );
}

function SearchResults({ query }: { query: string }) {
  const q = useQuery<SkillSearchHit[]>({
    queryKey: ["skill-search", query],
    queryFn: () => searchSkills(query),
  });
  if (q.isLoading) return <p style={{ marginTop: 16 }}>Searching…</p>;
  if (q.error) return <p style={{ color: "crimson" }}>{String(q.error)}</p>;
  const hits = q.data ?? [];
  return (
    <div style={{ marginTop: 16 }}>
      <p style={{ color: "#666", fontSize: 13, margin: 0 }}>
        {hits.length === 0 ? "No skills match." : `${hits.length} match${hits.length === 1 ? "" : "es"}`}
      </p>
      {hits.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8, fontSize: 14 }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid #ddd", color: "#666" }}>
              <th style={{ padding: "6px 4px" }}>Skill</th>
              <th style={{ padding: "6px 4px", width: 60 }}>Stat</th>
              <th style={{ padding: "6px 4px" }}>Group</th>
            </tr>
          </thead>
          <tbody>
            {hits.map((h, i) => (
              <tr key={`${h.group_slug}-${h.name}-${i}`} style={{ borderBottom: "1px solid #f3f3f3" }}>
                <td style={{ padding: "6px 4px" }}>{h.name}</td>
                <td style={{ padding: "6px 4px", color: "#666" }}>{h.stat ?? ""}</td>
                <td style={{ padding: "6px 4px" }}>
                  <Link to={`/skills/${h.group_slug}`} style={{ color: "#444" }}>
                    <span style={{ color: "#888", marginRight: 6 }}>{h.section}</span>
                    {h.group_name}
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function GroupList() {
  const q = useQuery<SkillGroupRow[]>({
    queryKey: ["skill-groups"],
    queryFn: fetchSkillGroups,
    staleTime: 1000 * 60 * 60,
  });
  // Group rows by "parent" prefix (Armor, Artistic, Athletic, Awareness,
  // Outdoor, Power, Special, Subterfuge, Technical/Trade) to make the
  // 34-row list visually manageable.
  const grouped = useMemo(() => {
    const data = q.data ?? [];
    const out: Record<string, SkillGroupRow[]> = {};
    for (const g of data) {
      const prefix = g.name.includes("•") ? g.name.split("•")[0].trim() : "Other";
      (out[prefix] ||= []).push(g);
    }
    return out;
  }, [q.data]);

  if (q.isLoading) return <p style={{ marginTop: 16, color: "#666" }}>Loading…</p>;
  if (q.error) return <p style={{ color: "crimson" }}>{String(q.error)}</p>;

  return (
    <div style={{ marginTop: 16 }}>
      {Object.entries(grouped).map(([prefix, groups]) => (
        <div key={prefix} style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 12, color: "#888", textTransform: "uppercase", letterSpacing: 0.5 }}>
            {prefix === "Other" ? "Standalone" : prefix}
          </div>
          <ul style={{ margin: "4px 0 0", padding: 0, listStyle: "none", fontSize: 14 }}>
            {groups.map((g) => (
              <li key={g.slug} style={{ padding: "3px 0" }}>
                <span style={{ color: "#888", marginRight: 6 }}>{g.section}</span>
                <Link to={`/skills/${g.slug}`}>{g.name}</Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
