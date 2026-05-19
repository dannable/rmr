import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, useParams } from "react-router-dom";

import {
  fetchListSpells,
  fetchSpellList,
  HttpError,
  type SpellListDetail as SpellListDetailT,
  type SpellSummary,
} from "../api";

/**
 * One spell list — metadata header + chart of every spell in the list.
 * Clicking a row drills into /spells/lists/:listId/spells/:level.
 */
export function SpellListDetailPage() {
  const { listId } = useParams<{ listId: string }>();
  const id = Number(listId);
  if (!id || Number.isNaN(id)) return <Navigate to="/spells" replace />;
  return <SpellListView listId={id} />;
}

function SpellListView({ listId }: { listId: number }) {
  const listQ = useQuery<SpellListDetailT>({
    queryKey: ["spell-list", listId],
    queryFn: () => fetchSpellList(listId),
    throwOnError: (e) => !(e instanceof HttpError && e.status === 404),
  });
  const spellsQ = useQuery<SpellSummary[]>({
    queryKey: ["spell-list", listId, "spells"],
    queryFn: () => fetchListSpells(listId),
    throwOnError: (e) => !(e instanceof HttpError && e.status === 404),
  });

  if (listQ.error instanceof HttpError && listQ.error.status === 404) {
    return (
      <section>
        <p>That spell list doesn't exist.</p>
        <Link to="/spells">Back to spells</Link>
      </section>
    );
  }
  if (listQ.isLoading || spellsQ.isLoading) return <p>Loading…</p>;
  if (listQ.error || spellsQ.error) {
    return <p style={{ color: "crimson" }}>{String(listQ.error || spellsQ.error)}</p>;
  }
  if (!listQ.data || !spellsQ.data) return null;

  const list = listQ.data;
  const spells = spellsQ.data;

  return (
    <section>
      <Link to="/spells" style={{ fontSize: 13, color: "#666" }}>← Spells</Link>

      <h2 style={{ marginTop: 8 }}>{list.name}</h2>
      <p style={{ color: "#666" }}>
        {list.list_number} — {list.category} — {list.realm_name}
      </p>

      {list.classes.length > 0 && (
        <p style={{ fontSize: 13, color: "#666" }}>
          <span style={{ color: "#888" }}>Accessible to:</span>{" "}
          {list.classes.join(", ")}
        </p>
      )}

      <hr />

      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "1px solid #ddd", color: "#666" }}>
            <th style={{ padding: "6px 4px", width: 40 }}>Lv</th>
            <th style={{ padding: "6px 4px" }}>Spell</th>
            <th style={{ padding: "6px 4px" }}>Area / Target</th>
            <th style={{ padding: "6px 4px" }}>Duration</th>
            <th style={{ padding: "6px 4px" }}>Range</th>
            <th style={{ padding: "6px 4px" }}>Type</th>
          </tr>
        </thead>
        <tbody>
          {spells.map((s) => (
            <tr key={s.level} style={{ borderBottom: "1px solid #f3f3f3" }}>
              <td style={{ padding: "6px 4px", fontVariantNumeric: "tabular-nums" }}>{s.level}</td>
              <td style={{ padding: "6px 4px" }}>
                <Link to={`/spells/lists/${listId}/spells/${s.level}`}>
                  {s.name}
                </Link>
                {s.starred && (
                  <span title="Concentration / continuing effect" style={{ marginLeft: 4 }}>*</span>
                )}
              </td>
              <td style={{ padding: "6px 4px", color: "#444" }}>{s.area_effect ?? ""}</td>
              <td style={{ padding: "6px 4px", color: "#444" }}>{s.duration ?? ""}</td>
              <td style={{ padding: "6px 4px", color: "#444" }}>{s.range_str ?? ""}</td>
              <td style={{ padding: "6px 4px", color: "#666" }}>{s.spell_type ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
