import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, useParams } from "react-router-dom";

import {
  fetchClassLists,
  fetchSpellLists,
  type ClassListRow,
  type SpellListRow,
} from "../api";

/**
 * One class's curriculum: its Base / Open / Closed lists.
 *
 * The class API returns just (name, list_number, category) — we need to
 * resolve each name back to a list_id so the rows can link to /spells/lists/:id.
 * Doing one /api/v1/spells/lists fetch (cached) is cheaper than 26 lookups.
 */
export function ClassListsPage() {
  const { className } = useParams<{ className: string }>();
  if (!className) return <Navigate to="/spells" replace />;
  return <ClassLists className={decodeURIComponent(className)} />;
}

function ClassLists({ className }: { className: string }) {
  const listsQ = useQuery<ClassListRow[]>({
    queryKey: ["spell-class-lists", className],
    queryFn: () => fetchClassLists(className),
  });
  const allQ = useQuery<SpellListRow[]>({
    queryKey: ["spell-lists"],
    queryFn: fetchSpellLists,
  });

  const idByNumber = useMemo(() => {
    const m: Record<string, number> = {};
    for (const l of allQ.data ?? []) m[l.list_number] = l.list_id;
    return m;
  }, [allQ.data]);

  // Group by category so each section can have its own heading.
  const byCategory = useMemo(() => {
    const out: Record<string, ClassListRow[]> = { Base: [], Open: [], Closed: [] };
    for (const l of listsQ.data ?? []) (out[l.category] ||= []).push(l);
    return out;
  }, [listsQ.data]);

  if (listsQ.isLoading || allQ.isLoading) return <p>Loading…</p>;
  if (listsQ.error) return <p style={{ color: "crimson" }}>{String(listsQ.error)}</p>;

  const total = (listsQ.data ?? []).length;

  return (
    <section>
      <Link to="/spells" style={{ fontSize: 13, color: "#666" }}>← Spells</Link>
      <h2 style={{ marginTop: 8 }}>{className}</h2>
      <p style={{ color: "#666" }}>{total} list{total === 1 ? "" : "s"}</p>

      {total === 0 && (
        <p style={{ color: "#888", marginTop: 16 }}>
          No spell lists are loaded for this class yet.
        </p>
      )}

      {(["Base", "Open", "Closed"] as const).map((cat) => {
        const rows = byCategory[cat] ?? [];
        if (rows.length === 0) return null;
        return (
          <div key={cat} style={{ marginTop: 20 }}>
            <h3 style={{ margin: 0, fontSize: 14, color: "#444" }}>{cat}</h3>
            <ul style={{ margin: "8px 0 0", padding: 0, listStyle: "none", fontSize: 14 }}>
              {rows.map((l) => {
                const id = idByNumber[l.list_number];
                return (
                  <li key={l.list_number} style={{ padding: "3px 0" }}>
                    <span style={{ color: "#888", marginRight: 6, fontVariantNumeric: "tabular-nums" }}>
                      {l.list_number}
                    </span>
                    {id ? (
                      <Link to={`/spells/lists/${id}`}>{l.name}</Link>
                    ) : (
                      <span>{l.name}</span>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </section>
  );
}
