import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchRaces,
  updateCharacterCulture,
  UMBRELLA_CULTURE_SLUGS,
  type Character,
  type Race,
} from "../api";

interface Props {
  character: Character;
}

/**
 * Sub-culture picker for the Common Men / Mixed Men umbrella races.
 *
 * Renders nothing when the character's race isn't umbrella — `race_is_umbrella`
 * comes back on the Character payload from the API and is the single source
 * of truth for whether this picker should appear.
 *
 * The 7 culture options (Hillmen, Mariners, Nomads, Ruralmen, Urbanmen,
 * Woodmen, High Men) are fetched from /api/v1/races (alongside every other
 * race) and filtered locally so we share the race cache with RacePicker.
 *
 * On save we PUT the slug to /characters/:id/culture, then invalidate the
 * character + stats + adolescence-ranks queries so the rest of the builder
 * picks up the new culture without a manual refresh.
 */
export function CulturePicker({ character }: Props) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<string | null>(character.culture_slug);

  const racesQ = useQuery<Race[]>({
    queryKey: ["races"],
    queryFn: fetchRaces,
    staleTime: 1000 * 60 * 60,
  });

  const cultureOptions = useMemo(() => {
    const all = racesQ.data ?? [];
    const allowed = new Set<string>(UMBRELLA_CULTURE_SLUGS);
    return all
      .filter((r) => allowed.has(r.slug))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [racesQ.data]);

  const m = useMutation({
    mutationFn: (slug: string | null) =>
      updateCharacterCulture(character.character_id, slug),
    onSuccess: (updated) => {
      qc.setQueryData(["characters", character.character_id], updated);
      qc.invalidateQueries({
        queryKey: ["characters", character.character_id, "stats"],
      });
      qc.invalidateQueries({
        queryKey: ["characters", character.character_id, "adolescence-ranks"],
      });
      qc.invalidateQueries({ queryKey: ["characters"] });
      setDraft(updated.culture_slug);
    },
  });

  // Nothing to render when the race isn't umbrella — the picker is purely
  // a sub-step of the umbrella-race flow.
  if (!character.race_is_umbrella) return null;

  const dirty = draft !== character.culture_slug;

  return (
    <section style={{ marginTop: 16 }}>
      <header style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Culture</h3>
        <span style={{ fontSize: 12, color: "#666" }}>
          Sub-culture under {character.race_name}
        </span>
      </header>

      <p style={{ marginTop: 6, fontSize: 13, color: "#666" }}>
        <strong>{character.race_name}</strong> is an umbrella category in RMSS.
        Pick one of the specific Men cultures below — it drives your
        adolescence ranks (T-1.6) and culture-specific stats / outfitting.
      </p>

      <div style={{ marginTop: 8, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <select
          value={draft ?? ""}
          onChange={(e) => setDraft(e.target.value || null)}
          disabled={racesQ.isLoading || m.isPending}
          style={{
            flex: 1,
            minWidth: 220,
            padding: "6px 8px",
            fontSize: 14,
            border: "1px solid #ccc",
            borderRadius: 4,
          }}
        >
          <option value="">— Pick a culture —</option>
          {cultureOptions.map((c) => (
            <option key={c.slug} value={c.slug}>{c.name}</option>
          ))}
        </select>

        <button
          className="btn"
          onClick={() => m.mutate(draft)}
          disabled={!dirty || m.isPending}
        >
          {m.isPending ? "Saving…" : "Save culture"}
        </button>
        {!dirty && character.culture_slug && !m.isPending && (
          <button
            className="btn btn-secondary"
            onClick={() => m.mutate(null)}
            title="Clear the culture sub-pick"
          >
            Clear
          </button>
        )}
      </div>

      {m.error && (
        <p style={{ color: "crimson", fontSize: 13, marginTop: 6 }}>
          {String(m.error)}
        </p>
      )}

      {!character.culture_slug && (
        <p style={{ marginTop: 8, fontSize: 12, color: "#a16207" }}>
          Until you pick a culture, Step 4 (Adolescence) and culture-derived
          fields can't populate.
        </p>
      )}
    </section>
  );
}
