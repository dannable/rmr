import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchProfession,
  fetchProfessions,
  updateCharacterProfession,
  type Character,
  type ProfessionDetail,
  type ProfessionRow,
} from "../api";

interface Props {
  character: Character;
}

/**
 * Profession picker for the chargen wizard.
 *
 * Sits below the RacePicker on CharacterDetail. Picking a profession PUTs
 * the slug to /api/v1/characters/:id/profession, then we invalidate the
 * character query so the header re-renders with the new profession.
 *
 * Beneath the dropdown we preview the chosen profession's metadata —
 * description, prime stats, realm(s), category-group bonuses, and the
 * profession's favourite skills — so the user can compare options before
 * committing. Per-category DP costs are collapsed by default behind a
 * disclosure since there are ~50 rows per profession.
 */
export function ProfessionPicker({ character }: Props) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<string | null>(character.profession_slug);

  const listQ = useQuery<ProfessionRow[]>({
    queryKey: ["professions"],
    queryFn: fetchProfessions,
    staleTime: 1000 * 60 * 60,
  });

  // Detail query only fires when there's a draft selected. We use the
  // draft (not the committed character.profession_slug) so previewing a
  // new pick shows that profession's full block before saving.
  const detailQ = useQuery<ProfessionDetail>({
    queryKey: ["profession-detail", draft],
    queryFn: () => fetchProfession(draft!),
    enabled: draft !== null,
    staleTime: 1000 * 60 * 60,
  });

  const m = useMutation({
    mutationFn: (slug: string | null) =>
      updateCharacterProfession(character.character_id, slug),
    onSuccess: (updated) => {
      qc.setQueryData(["characters", character.character_id], updated);
      qc.invalidateQueries({ queryKey: ["characters"] });
      setDraft(updated.profession_slug);
    },
  });

  const professionsByName = useMemo(
    () => (listQ.data ?? []).slice().sort((a, b) => a.name.localeCompare(b.name)),
    [listQ.data],
  );

  const dirty = draft !== character.profession_slug;
  const detail = detailQ.data;

  return (
    <section>
      <header style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Profession</h3>
        <span style={{ fontSize: 12, color: "#666" }}>
          RMSS Character Law
        </span>
      </header>

      <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center" }}>
        <select
          value={draft ?? ""}
          onChange={(e) => setDraft(e.target.value || null)}
          disabled={listQ.isLoading || m.isPending}
          style={{
            flex: 1,
            padding: "6px 8px",
            fontSize: 14,
            border: "1px solid #ccc",
            borderRadius: 4,
            background: "white",
          }}
        >
          <option value="">— Pick a profession —</option>
          {professionsByName.map((p) => (
            <option key={p.slug} value={p.slug}>
              {p.name}{p.realms.length ? ` (${p.realms.join(" / ")})` : ""}
            </option>
          ))}
        </select>
        <button
          className="btn"
          onClick={() => m.mutate(draft)}
          disabled={!dirty || m.isPending}
        >
          {m.isPending ? "Saving…" : (draft === null ? "Clear" : "Save")}
        </button>
      </div>

      {m.error && (
        <p style={{ color: "crimson", fontSize: 13, marginTop: 8 }}>
          Save failed: {String(m.error)}
        </p>
      )}

      {dirty && (
        <p style={{ marginTop: 8, fontSize: 12, color: "#888" }}>
          Unsaved selection — click Save to commit.
        </p>
      )}

      {detail && draft !== null && (
        <ProfessionDetailPanel detail={detail} />
      )}
    </section>
  );
}

function ProfessionDetailPanel({ detail }: { detail: ProfessionDetail }) {
  return (
    <div style={{ marginTop: 16, fontSize: 13 }}>
      <p style={{ margin: "0 0 10px", color: "#444", lineHeight: 1.5 }}>
        {detail.description}
      </p>

      <dl
        style={{
          display: "grid",
          gridTemplateColumns: "150px 1fr",
          gap: "4px 12px",
          marginBottom: 12,
        }}
      >
        <dt style={{ color: "#888" }}>Prime stats</dt>
        <dd style={{ margin: 0 }}>
          {detail.prime_stats.length ? detail.prime_stats.join(" • ") : "—"}
        </dd>
        <dt style={{ color: "#888" }}>Realm(s)</dt>
        <dd style={{ margin: 0 }}>
          {detail.realms.length ? detail.realms.join(" / ") : "Non-spell user"}
        </dd>
      </dl>

      {detail.group_bonuses.length > 0 && (
        <Section label="Category-group bonuses">
          <ul style={listStyle}>
            {detail.group_bonuses.map((b) => (
              <li key={b.group_name}>
                <strong>{b.group_name}</strong>: {b.bonus >= 0 ? "+" : ""}{b.bonus}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {detail.category_bonuses.length > 0 && (
        <Section label="Category bonuses">
          <ul style={listStyle}>
            {detail.category_bonuses.map((b, i) => (
              <li key={i}>
                <strong>{b.group_name} / {b.category_name}</strong>:{" "}
                {b.bonus >= 0 ? "+" : ""}{b.bonus}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {detail.skill_cost_modifiers.length > 0 && (
        <Section label="Skill cost modifiers">
          <ul style={listStyle}>
            {detail.skill_cost_modifiers.map((m, i) => (
              <li key={i}>
                <strong>{m.skill_name}</strong>
                <span style={{ color: "#888" }}> ({m.classification})</span>: ×{m.modifier}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {detail.favorite_skills.length > 0 && (
        <Section label="Favorite skills">
          <ul style={listStyle}>
            {detail.favorite_skills.map((f, i) => (
              <li key={i}>
                <strong>{f.skill_name}</strong>
                <span style={{ color: "#888" }}>
                  {" "}({f.group_name} / {f.category_name})
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {detail.category_costs.length > 0 && (
        <details style={{ marginTop: 12 }}>
          <summary style={{ cursor: "pointer", color: "#666" }}>
            DP costs per category ({detail.category_costs.length})
          </summary>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, marginTop: 6 }}>
            <thead>
              <tr style={{ background: "#fafafa", borderBottom: "1px solid #ddd" }}>
                <th style={costThStyle}>Group</th>
                <th style={costThStyle}>Category</th>
                <th style={costThStyle}>Cost</th>
              </tr>
            </thead>
            <tbody>
              {detail.category_costs.map((c, i) => (
                <tr key={i} style={{ borderBottom: "1px solid #f3f3f3" }}>
                  <td style={costTdStyle}>{c.group_name}</td>
                  <td style={costTdStyle}>{c.category_name}</td>
                  <td style={{ ...costTdStyle, fontFamily: "monospace" }}>{c.cost}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 12, color: "#888", textTransform: "uppercase", letterSpacing: 0.3, marginBottom: 4 }}>
        {label}
      </div>
      {children}
    </div>
  );
}

const listStyle: React.CSSProperties = {
  margin: 0,
  paddingLeft: 20,
  color: "#333",
  lineHeight: 1.5,
};

const costThStyle: React.CSSProperties = {
  padding: "4px 6px",
  textAlign: "left",
  color: "#666",
  textTransform: "capitalize",
  whiteSpace: "nowrap",
};

const costTdStyle: React.CSSProperties = {
  padding: "3px 6px",
  color: "#333",
  verticalAlign: "top",
};
