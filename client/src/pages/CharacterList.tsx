import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { fetchCharacters, type Character } from "../api";

export function CharacterListPage() {
  const q = useQuery<Character[]>({
    queryKey: ["characters"],
    queryFn: fetchCharacters,
  });

  if (q.isLoading) return <p>Loading characters…</p>;
  if (q.error) return <p style={{ color: "crimson" }}>Failed to load: {String(q.error)}</p>;

  const characters = q.data ?? [];

  return (
    <section>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0 }}>Your characters</h2>
        <Link className="btn" to="/characters/new">+ New character</Link>
      </div>

      {characters.length === 0 ? (
        <p style={{ color: "#666", marginTop: 24 }}>
          No characters yet. Create one to get started.
        </p>
      ) : (
        <div style={{ marginTop: 16 }}>
          {characters.map((c) => (
            <div key={c.character_id} className="character-row">
              <Link to={`/characters/${c.character_id}`}>{c.name}</Link>
              <span style={{ color: "#666", fontSize: 13 }}>Level {c.level}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
