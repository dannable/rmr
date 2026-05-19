import { useEffect, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";

import {
  fetchSpell,
  HttpError,
  updateSpell,
  type Spell,
  type SpellUpdate,
} from "../api";

/**
 * Edit form for one spell. Any logged-in user may edit; the API stamps
 * updated_at / updated_by_user_id and atomically re-writes the .txt file
 * that backs this list.
 *
 * The form keeps a local draft and only PUTs fields that actually changed,
 * matching the partial-update shape of /api/v1/spells/lists/:id/spells/:lvl.
 */
export function SpellEditPage() {
  const { listId, level } = useParams<{ listId: string; level: string }>();
  const idN = Number(listId);
  const lvlN = Number(level);
  if (!idN || Number.isNaN(idN) || !lvlN || Number.isNaN(lvlN)) {
    return <Navigate to="/spells" replace />;
  }
  return <SpellEdit listId={idN} level={lvlN} />;
}

interface Draft {
  name: string;
  area_effect: string;
  duration: string;
  range_str: string;
  spell_type: string;
  description: string;
  starred: boolean;
}

function spellToDraft(s: Spell): Draft {
  return {
    name: s.name,
    area_effect: s.area_effect ?? "",
    duration: s.duration ?? "",
    range_str: s.range_str ?? "",
    spell_type: s.spell_type ?? "",
    description: s.description ?? "",
    starred: s.starred,
  };
}

function diff(orig: Spell, d: Draft): SpellUpdate {
  // Convert blank strings back to null on the wire so we don't write "" into
  // columns the original loader left as NULL.
  const norm = (v: string): string | null => (v.trim() === "" ? null : v);
  const out: SpellUpdate = {};
  if (d.name !== orig.name) out.name = d.name;
  if (norm(d.area_effect) !== orig.area_effect) out.area_effect = norm(d.area_effect);
  if (norm(d.duration) !== orig.duration) out.duration = norm(d.duration);
  if (norm(d.range_str) !== orig.range_str) out.range_str = norm(d.range_str);
  if (norm(d.spell_type) !== orig.spell_type) out.spell_type = norm(d.spell_type);
  if (norm(d.description) !== orig.description) out.description = norm(d.description);
  if (d.starred !== orig.starred) out.starred = d.starred;
  return out;
}

function SpellEdit({ listId, level }: { listId: number; level: number }) {
  const qc = useQueryClient();
  const navigate = useNavigate();

  const q = useQuery<Spell>({
    queryKey: ["spell", listId, level],
    queryFn: () => fetchSpell(listId, level),
    throwOnError: (e) => !(e instanceof HttpError && e.status === 404),
  });

  const [draft, setDraft] = useState<Draft | null>(null);
  useEffect(() => {
    if (q.data) setDraft(spellToDraft(q.data));
  }, [q.data]);

  const m = useMutation({
    mutationFn: (body: SpellUpdate) => updateSpell(listId, level, body),
    onSuccess: (fresh) => {
      // Update caches so the detail page sees the new values without refetching.
      qc.setQueryData(["spell", listId, level], fresh);
      qc.invalidateQueries({ queryKey: ["spell-list", listId, "spells"] });
      navigate(`/spells/lists/${listId}/spells/${level}`, { replace: true });
    },
  });

  if (q.error instanceof HttpError && q.error.status === 404) {
    return (
      <section>
        <p>No spell at level {level} on that list.</p>
        <Link to={`/spells/lists/${listId}`}>Back to list</Link>
      </section>
    );
  }
  if (q.isLoading || !draft || !q.data) return <p>Loading…</p>;
  if (q.error) return <p style={{ color: "crimson" }}>{String(q.error)}</p>;

  const orig = q.data;
  const changes = diff(orig, draft);
  const dirty = Object.keys(changes).length > 0;

  return (
    <section>
      <Link to={`/spells/lists/${listId}/spells/${level}`} style={{ fontSize: 13, color: "#666" }}>
        ← {orig.name}
      </Link>

      <h2 style={{ marginTop: 8 }}>Edit spell</h2>
      <p style={{ color: "#666" }}>
        Level {level} on {orig.list_number} {orig.list_name}
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (dirty && !m.isPending) m.mutate(changes);
        }}
        style={{ marginTop: 16, display: "grid", gap: 12 }}
      >
        <Field label="Name">
          <input
            type="text"
            value={draft.name}
            maxLength={120}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          />
        </Field>

        <Field label="Area / Target">
          <input
            type="text"
            value={draft.area_effect}
            onChange={(e) => setDraft({ ...draft, area_effect: e.target.value })}
          />
        </Field>

        <Field label="Duration">
          <input
            type="text"
            value={draft.duration}
            onChange={(e) => setDraft({ ...draft, duration: e.target.value })}
          />
        </Field>

        <Field label="Range">
          <input
            type="text"
            value={draft.range_str}
            onChange={(e) => setDraft({ ...draft, range_str: e.target.value })}
          />
        </Field>

        <Field label="Type">
          <input
            type="text"
            value={draft.spell_type}
            onChange={(e) => setDraft({ ...draft, spell_type: e.target.value })}
            placeholder="e.g. E, F, U, P…"
          />
        </Field>

        <Field label="Concentration / continuing effect (*)">
          <label style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 0 }}>
            <input
              type="checkbox"
              checked={draft.starred}
              onChange={(e) => setDraft({ ...draft, starred: e.target.checked })}
            />
            <span style={{ fontSize: 13, color: "#666" }}>
              Mark as a Concentration / continuing-effect spell
            </span>
          </label>
        </Field>

        <Field label="Description">
          <textarea
            value={draft.description}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            rows={10}
            style={{
              width: "100%",
              boxSizing: "border-box",
              padding: "8px 10px",
              border: "1px solid #ccc",
              borderRadius: 4,
              fontFamily: "inherit",
              fontSize: 14,
              lineHeight: 1.5,
              resize: "vertical",
            }}
          />
        </Field>

        {m.error && (
          <p style={{ color: "crimson", fontSize: 13, margin: 0 }}>
            Save failed: {String(m.error)}
          </p>
        )}

        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button className="btn" type="submit" disabled={!dirty || m.isPending}>
            {m.isPending ? "Saving…" : "Save changes"}
          </button>
          <button
            className="btn btn-secondary"
            type="button"
            onClick={() => navigate(-1)}
            disabled={m.isPending}
          >
            Cancel
          </button>
          {dirty && (
            <span style={{ fontSize: 13, color: "#666" }}>
              {Object.keys(changes).length} change{Object.keys(changes).length === 1 ? "" : "s"}
            </span>
          )}
        </div>
      </form>
    </section>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <label>{label}</label>
      {children}
    </div>
  );
}
