import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import {
  fetchSpellClasses,
  fetchSpellLists,
  searchSpellsByName,
  type SpellClassRow,
  type SpellListRow,
  type SpellSearchHit,
} from "../api";

/**
 * Landing page for the spell explorer.
 *
 * Three entry points, in priority order:
 *   1. Search box (top) — name-substring search across every list.
 *   2. By class (left) — pick a class, see its 26-list curriculum.
 *   3. By list (right) — flat alphabetical view of every list.
 */
export function SpellsHomePage() {
  const [q, setQ] = useState("");
  const trimmed = q.trim();

  return (
    <section>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0 }}>Spells</h2>
        <Link to="/" style={{ fontSize: 13, color: "#666" }}>← Characters</Link>
      </header>

      <div style={{ marginTop: 16 }}>
        <label htmlFor="spell-search">Search by name</label>
        <input
          id="spell-search"
          type="text"
          placeholder="e.g. lightning, heal, barrier…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      {trimmed.length >= 2 ? (
        <SearchResults query={trimmed} />
      ) : (
        <BrowseGrid />
      )}
    </section>
  );
}

function SearchResults({ query }: { query: string }) {
  const q = useQuery<SpellSearchHit[]>({
    queryKey: ["spell-search", query],
    queryFn: () => searchSpellsByName(query),
  });

  if (q.isLoading) return <p style={{ marginTop: 16 }}>Searching…</p>;
  if (q.error) return <p style={{ color: "crimson" }}>{String(q.error)}</p>;
  const hits = q.data ?? [];

  return (
    <div style={{ marginTop: 16 }}>
      <p style={{ color: "#666", fontSize: 13, margin: 0 }}>
        {hits.length === 0 ? "No spells match." : `${hits.length} match${hits.length === 1 ? "" : "es"}`}
      </p>
      {hits.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8, fontSize: 14 }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid #ddd", color: "#666" }}>
              <th style={{ padding: "6px 4px", width: 40 }}>Lv</th>
              <th style={{ padding: "6px 4px" }}>Spell</th>
              <th style={{ padding: "6px 4px" }}>Type</th>
              <th style={{ padding: "6px 4px" }}>List</th>
            </tr>
          </thead>
          <tbody>
            {hits.map((h) => (
              <tr key={`${h.list_number}-${h.level}`} style={{ borderBottom: "1px solid #f3f3f3" }}>
                <td style={{ padding: "6px 4px", fontVariantNumeric: "tabular-nums" }}>{h.level}</td>
                <td style={{ padding: "6px 4px" }}>{h.name}</td>
                <td style={{ padding: "6px 4px", color: "#666" }}>{h.spell_type ?? ""}</td>
                <td style={{ padding: "6px 4px" }}>
                  <span style={{ color: "#888", marginRight: 6 }}>{h.list_number}</span>
                  {h.list_name}
                  <span style={{ color: "#888", marginLeft: 6, fontSize: 12 }}>
                    ({h.category})
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function BrowseGrid() {
  return (
    <div
      style={{
        marginTop: 24,
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 32,
      }}
    >
      <ClassesPanel />
      <ListsPanel />
    </div>
  );
}

function ClassesPanel() {
  const q = useQuery<SpellClassRow[]>({
    queryKey: ["spell-classes"],
    queryFn: fetchSpellClasses,
  });

  // Group by realm so the user can see the (currently Channeling-only) split.
  const byRealm = useMemo(() => {
    const out: Record<string, SpellClassRow[]> = {};
    for (const c of q.data ?? []) {
      (out[c.realm_name] ||= []).push(c);
    }
    return out;
  }, [q.data]);

  return (
    <div>
      <h3 style={{ margin: 0, fontSize: 15 }}>By class</h3>
      {q.isLoading && <p style={{ color: "#666" }}>Loading…</p>}
      {q.error && <p style={{ color: "crimson" }}>{String(q.error)}</p>}
      {Object.entries(byRealm).map(([realm, rows]) => (
        <div key={realm} style={{ marginTop: 12 }}>
          <div style={{ fontSize: 12, color: "#888", textTransform: "uppercase", letterSpacing: 0.5 }}>
            {realm}
          </div>
          <ul style={{ margin: "4px 0 0", padding: 0, listStyle: "none" }}>
            {rows.map((r) => (
              <li key={r.class_name} style={{ padding: "4px 0" }}>
                <Link to={`/spells/classes/${encodeURIComponent(r.class_name)}`}>
                  {r.class_name}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function ListsPanel() {
  const q = useQuery<SpellListRow[]>({
    queryKey: ["spell-lists"],
    queryFn: fetchSpellLists,
  });

  return (
    <div>
      <h3 style={{ margin: 0, fontSize: 15 }}>All lists</h3>
      {q.isLoading && <p style={{ color: "#666" }}>Loading…</p>}
      {q.error && <p style={{ color: "crimson" }}>{String(q.error)}</p>}
      <ul style={{ margin: "12px 0 0", padding: 0, listStyle: "none", fontSize: 14 }}>
        {(q.data ?? []).map((l) => (
          <li key={l.list_id} style={{ padding: "3px 0" }}>
            <span style={{ color: "#888", marginRight: 6, fontVariantNumeric: "tabular-nums" }}>
              {l.list_number}
            </span>
            <Link to={`/spells/lists/${l.list_id}`}>{l.name}</Link>
            <span style={{ color: "#888", marginLeft: 6, fontSize: 12 }}>
              ({l.category})
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
