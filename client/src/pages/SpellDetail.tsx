import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, useParams } from "react-router-dom";

import { fetchSpell, HttpError, type Spell } from "../api";

/**
 * One spell, full detail. The header links back to the list and forward to
 * /edit. Description is rendered as preformatted text — the .txt source
 * uses simple line wrapping that we preserve so paragraphs read naturally.
 */
export function SpellDetailPage() {
  const { listId, level } = useParams<{ listId: string; level: string }>();
  const idN = Number(listId);
  const lvlN = Number(level);
  if (!idN || Number.isNaN(idN) || !lvlN || Number.isNaN(lvlN)) {
    return <Navigate to="/spells" replace />;
  }
  return <SpellDetail listId={idN} level={lvlN} />;
}

function SpellDetail({ listId, level }: { listId: number; level: number }) {
  const q = useQuery<Spell>({
    queryKey: ["spell", listId, level],
    queryFn: () => fetchSpell(listId, level),
    throwOnError: (e) => !(e instanceof HttpError && e.status === 404),
  });

  if (q.error instanceof HttpError && q.error.status === 404) {
    return (
      <section>
        <p>No spell at level {level} on that list.</p>
        <Link to={`/spells/lists/${listId}`}>Back to list</Link>
      </section>
    );
  }
  if (q.isLoading) return <p>Loading…</p>;
  if (q.error || !q.data) return <p style={{ color: "crimson" }}>{String(q.error)}</p>;

  const s = q.data;

  return (
    <section>
      <Link to={`/spells/lists/${listId}`} style={{ fontSize: 13, color: "#666" }}>
        ← {s.list_name}
      </Link>

      <header style={{ marginTop: 8, display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div>
          <h2 style={{ margin: 0 }}>
            {s.name}
            {s.starred && <span style={{ marginLeft: 6 }}>*</span>}
          </h2>
          <p style={{ color: "#666", margin: "4px 0 0" }}>
            Level {s.level} — {s.list_number} {s.list_name} ({s.category})
          </p>
        </div>
        <Link className="btn" to={`/spells/lists/${listId}/spells/${level}/edit`}>
          Edit
        </Link>
      </header>

      <hr />

      <dl
        style={{
          display: "grid",
          gridTemplateColumns: "140px 1fr",
          gap: "4px 16px",
          fontSize: 14,
        }}
      >
        <dt style={{ color: "#666" }}>Area / Target</dt>
        <dd style={{ margin: 0 }}>{s.area_effect ?? <em style={{ color: "#aaa" }}>—</em>}</dd>
        <dt style={{ color: "#666" }}>Duration</dt>
        <dd style={{ margin: 0 }}>{s.duration ?? <em style={{ color: "#aaa" }}>—</em>}</dd>
        <dt style={{ color: "#666" }}>Range</dt>
        <dd style={{ margin: 0 }}>{s.range_str ?? <em style={{ color: "#aaa" }}>—</em>}</dd>
        <dt style={{ color: "#666" }}>Type</dt>
        <dd style={{ margin: 0 }}>{s.spell_type ?? <em style={{ color: "#aaa" }}>—</em>}</dd>
        <dt style={{ color: "#666" }}>Realm</dt>
        <dd style={{ margin: 0 }}>{s.realm_name}</dd>
      </dl>

      <hr />

      <h3 style={{ margin: 0, fontSize: 15 }}>Description</h3>
      {s.description ? (
        <p style={{ marginTop: 8, whiteSpace: "pre-wrap" }}>{s.description}</p>
      ) : (
        <p style={{ marginTop: 8, color: "#888" }}>No description recorded.</p>
      )}

      {s.updated_at && (
        <p style={{ marginTop: 24, fontSize: 12, color: "#888" }}>
          Last edited {s.updated_at}
          {s.updated_by_user_id != null && ` by user ${s.updated_by_user_id}`}
        </p>
      )}
    </section>
  );
}
