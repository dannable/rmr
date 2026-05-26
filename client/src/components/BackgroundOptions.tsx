import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchBackgroundOptions,
  updateBackgroundOptions,
  type BackgroundOptionsResponse,
  type BackgroundOptionPick,
} from "../api";

interface Props {
  characterId: number;
  /** Optional. When provided, used only to hint at the "pick a race first"
   *  empty state — the server still ground-truths max_options. */
  raceSlug: string | null;
}

/**
 * Step 5: background-options picker (RMSS T-1.5).
 *
 * The character spends `race.bg_opts` slots picking from a fixed menu;
 * each pick can carry an optional player-typed detail (e.g. which
 * language, which weapon). Unsaved edits sit in local state until the
 * user clicks Save.
 */
export function BackgroundOptions({ characterId, raceSlug }: Props) {
  const qc = useQueryClient();
  const q = useQuery<BackgroundOptionsResponse>({
    queryKey: ["characters", characterId, "background-options"],
    queryFn: () => fetchBackgroundOptions(characterId),
  });

  // Local draft. Seed from the server response and replace on save.
  const [draft, setDraft] = useState<BackgroundOptionPick[] | null>(null);
  useEffect(() => {
    if (q.data && draft === null) setDraft(q.data.picks);
  }, [q.data, draft]);

  const m = useMutation({
    mutationFn: (picks: BackgroundOptionPick[]) =>
      updateBackgroundOptions(characterId, picks),
    onSuccess: (fresh) => {
      qc.setQueryData(
        ["characters", characterId, "background-options"], fresh,
      );
      setDraft(fresh.picks);
    },
  });

  const catalog = q.data?.catalog ?? [];
  const max = q.data?.max_options ?? 0;
  const current = draft ?? q.data?.picks ?? [];

  const catalogByKey = useMemo(
    () => Object.fromEntries(catalog.map((c) => [c.key, c])),
    [catalog],
  );

  const dirty = useMemo(() => {
    if (!q.data) return false;
    if (current.length !== q.data.picks.length) return true;
    return current.some((p, i) => {
      const o = q.data!.picks[i];
      return p.option_key !== o.option_key || (p.detail || "") !== (o.detail || "");
    });
  }, [current, q.data]);

  if (q.isLoading) return <p style={{ color: "#666" }}>Loading…</p>;
  if (q.error) return <p style={{ color: "crimson" }}>{String(q.error)}</p>;
  if (!q.data) return null;

  // Empty state when the character has no race set.
  if (max === 0 && !raceSlug) {
    return (
      <p style={{ color: "#888", fontSize: 13 }}>
        Pick a race in Step 2 first — background-option count depends on race.
      </p>
    );
  }

  const remaining = max - current.length;
  const overBudget = remaining < 0;

  const setPick = (idx: number, updater: (p: BackgroundOptionPick) => BackgroundOptionPick) => {
    setDraft((prev) => {
      const arr = (prev ?? q.data!.picks).slice();
      arr[idx] = updater(arr[idx]);
      return arr;
    });
  };

  const addPick = () => {
    setDraft((prev) => [
      ...(prev ?? q.data!.picks),
      { option_key: catalog[0]?.key ?? "", detail: "" },
    ]);
  };

  const removePick = (idx: number) => {
    setDraft((prev) => (prev ?? q.data!.picks).filter((_, i) => i !== idx));
  };

  return (
    <div>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <span style={{ fontSize: 13, color: "#666" }}>
          RMSS Character Law Table T-1.5
        </span>
        <span style={{ fontSize: 13 }}>
          <strong>{current.length}</strong> / {max} options spent
          {remaining > 0 && (
            <span style={{ color: "#888", marginLeft: 6 }}>
              ({remaining} remaining)
            </span>
          )}
          {overBudget && (
            <span style={{ color: "crimson", marginLeft: 6 }}>
              ({-remaining} over budget)
            </span>
          )}
        </span>
      </header>

      <div style={{ marginTop: 12 }}>
        {current.length === 0 ? (
          <p style={{ color: "#888", fontSize: 13 }}>
            No background options selected yet.
          </p>
        ) : (
          current.map((pick, i) => {
            const entry = catalogByKey[pick.option_key];
            return (
              <div
                key={i}
                style={{
                  display: "grid",
                  gridTemplateColumns: "260px 1fr auto",
                  gap: 8,
                  marginBottom: 6,
                  alignItems: "start",
                }}
              >
                <select
                  value={pick.option_key}
                  onChange={(e) =>
                    setPick(i, (p) => ({ ...p, option_key: e.target.value }))
                  }
                  style={{
                    padding: "4px 6px",
                    fontSize: 13,
                    border: "1px solid #ccc",
                    borderRadius: 4,
                    background: "white",
                  }}
                >
                  {catalog.map((c) => (
                    <option key={c.key} value={c.key}>{c.label}</option>
                  ))}
                </select>
                {entry?.wants_detail ? (
                  <input
                    type="text"
                    value={pick.detail}
                    placeholder={entry.detail_placeholder}
                    onChange={(e) =>
                      setPick(i, (p) => ({ ...p, detail: e.target.value }))
                    }
                    style={{ padding: "4px 6px", fontSize: 13 }}
                  />
                ) : (
                  <span style={{ color: "#888", fontSize: 12, alignSelf: "center" }}>
                    {entry?.description ?? ""}
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => removePick(i)}
                  className="btn-link"
                  style={{ color: "#c00", fontSize: 12 }}
                >
                  ✕
                </button>
              </div>
            );
          })
        )}
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={addPick}
          disabled={catalog.length === 0}
          style={{ fontSize: 13, padding: "4px 12px" }}
        >
          + Add option
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => draft && m.mutate(draft)}
          disabled={!dirty || m.isPending}
          style={{ fontSize: 13, padding: "4px 12px" }}
        >
          {m.isPending ? "Saving…" : "Save"}
        </button>
      </div>

      {m.error && (
        <p style={{ color: "crimson", fontSize: 13, marginTop: 8 }}>
          Save failed: {String(m.error)}
        </p>
      )}
    </div>
  );
}
