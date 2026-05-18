import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { createCharacter, type Character } from "../api";

export function NewCharacterPage() {
  const [name, setName] = useState("");
  const qc = useQueryClient();
  const navigate = useNavigate();

  const m = useMutation({
    mutationFn: () => createCharacter(name.trim()),
    onSuccess: (created: Character) => {
      qc.invalidateQueries({ queryKey: ["characters"] });
      navigate(`/characters/${created.character_id}`, { replace: true });
    },
  });

  const canSubmit = name.trim().length > 0 && !m.isPending;

  return (
    <section>
      <h2 style={{ marginTop: 0 }}>New character</h2>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (canSubmit) m.mutate();
        }}
        style={{ marginTop: 16 }}
      >
        <label htmlFor="name">Name</label>
        <input
          id="name"
          type="text"
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Varak the Bold"
          maxLength={80}
        />

        {m.error && (
          <p style={{ color: "crimson", fontSize: 13, marginTop: 8 }}>
            {String(m.error)}
          </p>
        )}

        <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
          <button className="btn" type="submit" disabled={!canSubmit}>
            {m.isPending ? "Creating…" : "Create"}
          </button>
          <button
            className="btn btn-secondary"
            type="button"
            onClick={() => navigate(-1)}
          >
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}
