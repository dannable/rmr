import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";

import {
  deleteCharacter,
  fetchCharacter,
  HttpError,
  type Character,
} from "../api";
import { RacePicker } from "../components/RacePicker";
import { StatsEditor } from "../components/StatsEditor";

export function CharacterDetailPage() {
  const { id } = useParams<{ id: string }>();
  const characterId = Number(id);

  if (!characterId || Number.isNaN(characterId)) {
    return <Navigate to="/" replace />;
  }

  return <CharacterDetail characterId={characterId} />;
}

function CharacterDetail({ characterId }: { characterId: number }) {
  const qc = useQueryClient();
  const navigate = useNavigate();

  const q = useQuery<Character>({
    queryKey: ["characters", characterId],
    queryFn: () => fetchCharacter(characterId),
    // 404s shouldn't trigger the error boundary — let the page render a message.
    throwOnError: (e) => !(e instanceof HttpError && e.status === 404),
  });

  const del = useMutation({
    mutationFn: () => deleteCharacter(characterId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["characters"] });
      navigate("/", { replace: true });
    },
  });

  if (q.isLoading) return <p>Loading…</p>;
  if (q.error instanceof HttpError && q.error.status === 404) {
    return (
      <section>
        <p>That character doesn't exist (or isn't yours).</p>
        <Link to="/">Back to your characters</Link>
      </section>
    );
  }
  if (q.error || !q.data) {
    return <p style={{ color: "crimson" }}>Failed to load: {String(q.error)}</p>;
  }

  const c = q.data;
  return (
    <section>
      <Link to="/" style={{ fontSize: 13, color: "#666" }}>← Back</Link>

      <h2 style={{ marginTop: 8 }}>{c.name}</h2>
      <p style={{ color: "#666" }}>
        Level {c.level}
        {c.race_name && <span style={{ marginLeft: 8 }}> · {c.race_name}</span>}
      </p>

      <hr />

      <dl
        style={{
          display: "grid",
          gridTemplateColumns: "120px 1fr",
          gap: "4px 16px",
          fontSize: 14,
        }}
      >
        <dt style={{ color: "#666" }}>ID</dt>
        <dd style={{ margin: 0 }}>{c.character_id}</dd>
        <dt style={{ color: "#666" }}>Created</dt>
        <dd style={{ margin: 0 }}>{c.created_at}</dd>
        <dt style={{ color: "#666" }}>Updated</dt>
        <dd style={{ margin: 0 }}>{c.updated_at}</dd>
      </dl>

      <hr />

      <RacePicker character={c} />

      <hr />

      <StatsEditor characterId={c.character_id} />

      <hr />

      <p style={{ color: "#888", fontSize: 13 }}>
        Next: culture + profession picker. Skill DP allocator after that.
      </p>

      <div style={{ marginTop: 24 }}>
        <button
          className="btn btn-danger"
          onClick={() => {
            if (confirm(`Delete "${c.name}"? This cannot be undone.`)) {
              del.mutate();
            }
          }}
          disabled={del.isPending}
        >
          {del.isPending ? "Deleting…" : "Delete character"}
        </button>
        {del.error && (
          <p style={{ color: "crimson", fontSize: 13, marginTop: 8 }}>
            {String(del.error)}
          </p>
        )}
      </div>
    </section>
  );
}
