import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, useParams } from "react-router-dom";

import {
  fetchSkillGroup,
  HttpError,
  updateSkillGroup,
  type SkillGroupDetail as Detail,
  type SkillCategory,
  type SkillEntry,
  type SkillGroupUpdate,
  type SkillTable,
  type SkillTableRow,
} from "../api";

/**
 * One skill-category-group from RMSS Appendix A-1.
 *
 * Two display modes:
 *   - View mode: read-only PDF-style layout (categories + skills on the
 *     left, sticky maneuver table on the right).
 *   - Edit mode: every text field becomes an input/textarea; rows can
 *     be added/removed/reordered; saving sends the whole group payload
 *     to PUT /api/v1/skills/<slug>, which wipes the group's children,
 *     re-inserts from the payload, and rewrites data/skills/<slug>.txt.
 */
export function SkillGroupDetailPage() {
  const { slug } = useParams<{ slug: string }>();
  if (!slug) return <Navigate to="/skills" replace />;
  return <SkillGroupView slug={slug} />;
}

function SkillGroupView({ slug }: { slug: string }) {
  const qc = useQueryClient();
  const q = useQuery<Detail>({
    queryKey: ["skill-group", slug],
    queryFn: () => fetchSkillGroup(slug),
    throwOnError: (e) => !(e instanceof HttpError && e.status === 404),
  });

  // Local edit state. `null` means "not editing"; non-null is the draft
  // being mutated. We seed the draft from server data when the user
  // clicks "Edit", then clear it on save/cancel.
  const [draft, setDraft] = useState<Detail | null>(null);
  // Reset the draft when navigating to a different group while in edit mode.
  useEffect(() => { setDraft(null); }, [slug]);

  const m = useMutation({
    mutationFn: (body: SkillGroupUpdate) => updateSkillGroup(slug, body),
    onSuccess: (fresh) => {
      qc.setQueryData(["skill-group", slug], fresh);
      qc.invalidateQueries({ queryKey: ["skill-groups"] });
      setDraft(null);
    },
  });

  if (q.error instanceof HttpError && q.error.status === 404) {
    return (
      <section>
        <p>That skill group doesn't exist.</p>
        <Link to="/skills">Back to skills</Link>
      </section>
    );
  }
  if (q.isLoading) return <p>Loading…</p>;
  if (q.error || !q.data) return <p style={{ color: "crimson" }}>{String(q.error)}</p>;

  const g = q.data;
  const editing = draft !== null;
  const view = draft ?? g;
  const hasTables = view.tables.length > 0;

  const startEdit = () => setDraft(cloneDetail(g));
  const cancelEdit = () => setDraft(null);
  const save = () => {
    if (!draft) return;
    m.mutate({
      name: draft.name,
      categories: draft.categories,
      skills: draft.skills,
      tables: draft.tables,
    });
  };

  // Generic setter helpers — keep the SkillGroupView slim and the
  // child editors purely presentational. Each helper returns a new
  // Detail with the requested branch replaced.
  const updateDraft = (mut: (d: Detail) => void) => {
    if (!draft) return;
    const next = cloneDetail(draft);
    mut(next);
    setDraft(next);
  };

  return (
    <section>
      {/* Widen the page just for this view — two-column maneuver-table
          view doesn't breathe well inside the default narrow layout. */}
      <style>{`main { max-width: min(1180px, 96vw); }`}</style>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <Link to="/skills" style={{ fontSize: 13, color: "#666" }}>← Skills</Link>
        {!editing ? (
          <button className="btn" type="button" onClick={startEdit} style={{ fontSize: 13, padding: "4px 12px" }}>
            Edit
          </button>
        ) : (
          <div style={{ display: "flex", gap: 8 }}>
            <button
              className="btn"
              type="button"
              onClick={save}
              disabled={m.isPending}
              style={{ fontSize: 13, padding: "4px 12px" }}
            >
              {m.isPending ? "Saving…" : "Save changes"}
            </button>
            <button
              className="btn btn-secondary"
              type="button"
              onClick={cancelEdit}
              disabled={m.isPending}
              style={{ fontSize: 13, padding: "4px 12px" }}
            >
              Cancel
            </button>
          </div>
        )}
      </div>

      {editing ? (
        <input
          type="text"
          value={view.name}
          onChange={(e) => updateDraft((d) => { d.name = e.target.value; })}
          style={{ marginTop: 8, fontSize: 22, fontWeight: 600, width: "100%" }}
        />
      ) : (
        <h2 style={{ marginTop: 8 }}>{g.name}</h2>
      )}
      <p style={{ color: "#666", margin: "4px 0 0" }}>
        {g.section} — RMSS Appendix A-1 pages {g.page_div}–{g.page_content}
        {g.updated_at && (
          <span style={{ marginLeft: 12, fontSize: 11, color: "#999" }}>
            • last edited {g.updated_at.replace("T", " ").replace("+00:00", " UTC")}
          </span>
        )}
      </p>

      {m.error && (
        <p style={{ color: "crimson", fontSize: 13, marginTop: 8 }}>
          Save failed: {String(m.error)}
        </p>
      )}

      <hr />

      {hasTables ? (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
            gap: 32,
            alignItems: "start",
          }}
        >
          <div>
            <LeftColumn
              categories={view.categories}
              skills={view.skills}
              editing={editing}
              onChange={updateDraft}
            />
          </div>
          <div style={{ position: "sticky", top: 16 }}>
            {view.tables.map((t, i) => (
              <TableBlock
                key={i}
                table={t}
                groupName={view.name}
                editing={editing}
                onChange={(mut) => updateDraft((d) => mut(d.tables[i]))}
              />
            ))}
          </div>
        </div>
      ) : (
        <LeftColumn
          categories={view.categories}
          skills={view.skills}
          editing={editing}
          onChange={updateDraft}
        />
      )}
    </section>
  );
}

/** Deep-ish clone — the immutability helpers below all return new objects,
 *  but we start the draft from a snapshot so the original isn't mutated. */
function cloneDetail(d: Detail): Detail {
  return {
    ...d,
    categories: d.categories.map((c) => ({ ...c })),
    skills: d.skills.map((s) => ({ ...s })),
    tables: d.tables.map((t) => ({
      ...t,
      columns: [...t.columns],
      general_mods: [...t.general_mods],
      rows: t.rows.map((r) => ({ ...r })),
    })),
  };
}

function LeftColumn({
  categories,
  skills,
  editing,
  onChange,
}: {
  categories: SkillCategory[];
  skills: SkillEntry[];
  editing: boolean;
  onChange: (mut: (d: Detail) => void) => void;
}) {
  return (
    <>
      <h3 style={{ margin: "0 0 8px", fontSize: 15 }}>Categories</h3>
      {categories.map((c, i) => (
        <CategoryBlock
          key={i}
          cat={c}
          editing={editing}
          onChange={(mut) => onChange((d) => mut(d.categories[i]))}
        />
      ))}

      {skills.length > 0 && (
        <>
          <hr />
          <h3 style={{ margin: "0 0 8px", fontSize: 15 }}>Skill descriptions</h3>
          {skills.map((s, i) => (
            <SkillBlock
              key={i}
              skill={s}
              editing={editing}
              onChange={(mut) => onChange((d) => mut(d.skills[i]))}
            />
          ))}
        </>
      )}
    </>
  );
}

function CategoryBlock({
  cat,
  editing,
  onChange,
}: {
  cat: SkillCategory;
  editing: boolean;
  onChange: (mut: (c: SkillCategory) => void) => void;
}) {
  return (
    <div style={{ marginBottom: 16, paddingBottom: 12, borderBottom: "1px solid #eee" }}>
      {editing ? (
        <input
          type="text"
          value={cat.name}
          onChange={(e) => onChange((c) => { c.name = e.target.value; })}
          style={{ marginBottom: 6, fontSize: 14, fontWeight: 600, width: "100%" }}
        />
      ) : (
        <h4 style={{ margin: "0 0 6px", fontSize: 14 }}>{cat.name}</h4>
      )}
      <dl
        style={{
          display: "grid",
          gridTemplateColumns: "180px 1fr",
          gap: "4px 12px",
          fontSize: 13,
          margin: 0,
        }}
      >
        <CatField label="Skills"               value={cat.skills_list}        editing={editing} onChange={(v) => onChange((c) => { c.skills_list = v; })} />
        <CatField label="Restricted"           value={cat.restricted}         editing={editing} onChange={(v) => onChange((c) => { c.restricted = v; })} />
        <CatField label="Stat Bonuses"         value={cat.stat_bonuses}       editing={editing} onChange={(v) => onChange((c) => { c.stat_bonuses = v; })} />
        <CatField label="Rank Progression"     value={cat.rank_progression}   editing={editing} onChange={(v) => onChange((c) => { c.rank_progression = v; })} />
        <CatField label="Category Progression" value={cat.category_progression} editing={editing} onChange={(v) => onChange((c) => { c.category_progression = v; })} />
        <CatField label="Group"                value={cat.parent_group}       editing={editing} onChange={(v) => onChange((c) => { c.parent_group = v; })} />
        <CatField label="Classification"       value={cat.classification}     editing={editing} onChange={(v) => onChange((c) => { c.classification = v; })} />
      </dl>
      <div style={{ marginTop: 8 }}>
        <label style={{ color: "#888", fontSize: 12 }}>Description</label>
        {editing ? (
          <textarea
            value={cat.description ?? ""}
            onChange={(e) => onChange((c) => { c.description = e.target.value; })}
            rows={4}
            style={textareaStyle}
          />
        ) : cat.description ? (
          <p style={{ marginTop: 4, fontSize: 13, color: "#444", whiteSpace: "pre-wrap" }}>
            {cat.description}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function CatField({
  label,
  value,
  editing,
  onChange,
}: {
  label: string;
  value: string | null;
  editing: boolean;
  onChange: (v: string | null) => void;
}) {
  if (!editing && !value) return null;
  return (
    <>
      <dt style={{ color: "#888" }}>{label}</dt>
      <dd style={{ margin: 0, color: "#333" }}>
        {editing ? (
          <input
            type="text"
            value={value ?? ""}
            onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
            style={{ width: "100%", fontSize: 13 }}
          />
        ) : (
          value
        )}
      </dd>
    </>
  );
}

function SkillBlock({
  skill,
  editing,
  onChange,
}: {
  skill: SkillEntry;
  editing: boolean;
  onChange: (mut: (s: SkillEntry) => void) => void;
}) {
  return (
    <div style={{ marginBottom: 12 }}>
      {editing ? (
        <div style={{ display: "flex", gap: 8, alignItems: "baseline", marginBottom: 4 }}>
          <input
            type="text"
            value={skill.name}
            onChange={(e) => onChange((s) => { s.name = e.target.value; })}
            style={{ flex: 1, fontSize: 14, fontWeight: 600 }}
          />
          <input
            type="text"
            value={skill.stat ?? ""}
            placeholder="stat"
            onChange={(e) => onChange((s) => { s.stat = e.target.value === "" ? null : e.target.value; })}
            style={{ width: 90, fontSize: 12 }}
          />
        </div>
      ) : (
        <h4 style={{ margin: "0 0 4px", fontSize: 14 }}>
          {skill.name}
          {skill.stat && (
            <span style={{ marginLeft: 8, color: "#888", fontSize: 12 }}>
              ({skill.stat})
            </span>
          )}
        </h4>
      )}
      {editing ? (
        <textarea
          value={skill.description ?? ""}
          onChange={(e) => onChange((s) => { s.description = e.target.value; })}
          rows={4}
          style={textareaStyle}
        />
      ) : skill.description ? (
        <p style={{ margin: 0, fontSize: 13, color: "#444", whiteSpace: "pre-wrap" }}>
          {skill.description}
        </p>
      ) : null}
    </div>
  );
}

function TableBlock({
  table,
  groupName,
  editing,
  onChange,
}: {
  table: SkillTable;
  groupName: string;
  editing: boolean;
  onChange: (mut: (t: SkillTable) => void) => void;
}) {
  const isManeuverTable = isExpectedColumns(
    table.columns,
    ["roll", "result", "percent", "time", "mod", "description"],
  );
  if (isManeuverTable) {
    return <ManeuverTableBlock table={table} groupName={groupName} editing={editing} onChange={onChange} />;
  }
  return <GenericTableBlock table={table} editing={editing} onChange={onChange} />;
}

function isExpectedColumns(actual: string[], expected: string[]): boolean {
  if (actual.length !== expected.length) return false;
  return actual.every((c, i) => c.toLowerCase() === expected[i].toLowerCase());
}

/**
 * PDF-style Static Maneuver Table layout — mirrors RMSS T-4.8.x.
 *
 * Title bar: solid black with white text, two lines (skill / group name on
 * top, "Static Maneuver Table T-x.x" on bottom), matching the printed
 * page chrome.
 *
 * Body: each row is bold roll range + result name on the left, the
 * percent / time / mod cluster right-aligned. Dotted leaders bridge the
 * two halves. UM 66 (Unusual Event) and UM 100 (Unusual Success) rows
 * get a grey background to mirror the PDF's call-out shading; everything
 * else stays white.
 */
function ManeuverTableBlock({
  table,
  groupName,
  editing,
  onChange,
}: {
  table: SkillTable;
  groupName: string;
  editing: boolean;
  onChange: (mut: (t: SkillTable) => void) => void;
}) {
  const addRow = () =>
    onChange((t) => {
      t.rows = [
        ...t.rows,
        { roll: "", result: "", percent: "", time: "", mod: "", description: "" },
      ];
    });
  const removeRow = (i: number) =>
    onChange((t) => { t.rows = t.rows.filter((_, j) => j !== i); });
  const moveRow = (i: number, delta: -1 | 1) =>
    onChange((t) => {
      const j = i + delta;
      if (j < 0 || j >= t.rows.length) return;
      const next = [...t.rows];
      [next[i], next[j]] = [next[j], next[i]];
      t.rows = next;
    });

  return (
    <div
      style={{
        marginBottom: 20,
        background: "#fff",
        border: "1px solid #222",
        borderRadius: 4,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          background: "#111",
          color: "#fff",
          padding: "10px 16px",
          textAlign: "center",
        }}
      >
        <div style={{
          fontSize: 14,
          fontWeight: 700,
          letterSpacing: 0.3,
          textTransform: "uppercase",
        }}>
          {groupName}
        </div>
        <div style={{
          fontSize: 11,
          color: "#ddd",
          marginTop: 2,
          letterSpacing: 0.2,
        }}>
          {table.name}
        </div>
      </div>

      <div style={{ padding: "12px 16px" }}>
        {table.rows.map((row, i) => (
          <ManeuverRow
            key={i}
            row={row}
            editing={editing}
            isFirst={i === 0}
            isLast={i === table.rows.length - 1}
            onChange={(mut) => onChange((t) => mut(t.rows[i]))}
            onRemove={() => removeRow(i)}
            onMoveUp={() => moveRow(i, -1)}
            onMoveDown={() => moveRow(i, 1)}
          />
        ))}
        {editing && (
          <div style={{ marginTop: 8 }}>
            <button
              className="btn btn-secondary"
              type="button"
              onClick={addRow}
              style={{ fontSize: 12, padding: "4px 10px" }}
            >
              + Add row
            </button>
          </div>
        )}

        <GeneralModsFooter
          entries={table.general_mods}
          editing={editing}
          onChange={(mut) => onChange((t) => { t.general_mods = mut(t.general_mods); })}
        />
      </div>
    </div>
  );
}

function isHighlightRow(roll: string | null): boolean {
  // UM 66 / UM 100 — Unusual Event / Unusual Success. The PDF shades
  // these rows. We match anything whose roll cell starts with "UM ".
  return !!roll && roll.trim().toUpperCase().startsWith("UM ");
}

function ManeuverRow({
  row,
  editing,
  isFirst,
  isLast,
  onChange,
  onRemove,
  onMoveUp,
  onMoveDown,
}: {
  row: SkillTableRow;
  editing: boolean;
  isFirst: boolean;
  isLast: boolean;
  onChange: (mut: (r: SkillTableRow) => void) => void;
  onRemove: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
}) {
  const modParts: string[] = [];
  if (row.percent) modParts.push(row.percent);
  if (row.time)    modParts.push(row.time);
  if (row.mod)     modParts.push(row.mod);
  const modText = modParts.join(" • ");
  const highlighted = isHighlightRow(row.roll);

  const rowBg = highlighted ? "#e9e9e9" : "transparent";

  if (editing) {
    return (
      <div
        style={{
          background: rowBg,
          padding: "8px 8px",
          borderRadius: 3,
          marginBottom: 6,
          border: "1px solid #ddd",
        }}
      >
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr 1fr", gap: 4 }}>
          <input type="text" placeholder="roll"    value={row.roll ?? ""}    onChange={(e) => onChange((r) => { r.roll = e.target.value; })}    style={inlineInputStyle} />
          <input type="text" placeholder="result"  value={row.result ?? ""}  onChange={(e) => onChange((r) => { r.result = e.target.value; })}  style={inlineInputStyle} />
          <input type="text" placeholder="percent" value={row.percent ?? ""} onChange={(e) => onChange((r) => { r.percent = e.target.value; })} style={inlineInputStyle} />
          <input type="text" placeholder="time"    value={row.time ?? ""}    onChange={(e) => onChange((r) => { r.time = e.target.value; })}    style={inlineInputStyle} />
          <input type="text" placeholder="mod"     value={row.mod ?? ""}     onChange={(e) => onChange((r) => { r.mod = e.target.value; })}     style={inlineInputStyle} />
        </div>
        <textarea
          value={row.description ?? ""}
          onChange={(e) => onChange((r) => { r.description = e.target.value; })}
          rows={3}
          placeholder="description"
          style={{ ...textareaStyle, marginTop: 4, fontSize: 12 }}
        />
        <div style={{ display: "flex", gap: 4, marginTop: 4, fontSize: 11 }}>
          <button type="button" className="btn-link" onClick={onMoveUp} disabled={isFirst} title="Move up">↑</button>
          <button type="button" className="btn-link" onClick={onMoveDown} disabled={isLast} title="Move down">↓</button>
          <button type="button" className="btn-link" onClick={onRemove} title="Remove" style={{ color: "#c00" }}>✕ remove</button>
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        background: rowBg,
        padding: highlighted ? "6px 8px" : "0",
        borderRadius: 3,
        marginBottom: 10,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: 8,
          fontSize: 13,
        }}
      >
        <div style={{ fontWeight: 600, color: "#222", whiteSpace: "nowrap" }}>
          {row.roll && <span style={{ marginRight: 8 }}>{row.roll}</span>}
          {row.result}
        </div>
        <span
          aria-hidden
          style={{
            flex: 1,
            borderBottom: "1px dotted #aaa",
            marginBottom: 4,
            minWidth: 12,
          }}
        />
        {modText && (
          <div
            style={{
              color: "#555",
              fontVariantNumeric: "tabular-nums",
              whiteSpace: "nowrap",
              fontSize: 12,
            }}
          >
            {modText}
          </div>
        )}
      </div>
      {row.description && (
        <p style={{
          margin: "2px 0 0",
          fontSize: 12,
          color: "#444",
          lineHeight: 1.45,
        }}>
          {row.description}
        </p>
      )}
    </div>
  );
}

/**
 * "General and GM-Assigned Modifers" footer.
 *
 * View mode: dotted-leader rows mirroring the PDF.
 * Edit mode: one input per entry with add/remove. Stored as a string
 * list; we split on the LAST ':' so labels with colons survive intact.
 */
function GeneralModsFooter({
  entries,
  editing,
  onChange,
}: {
  entries: string[];
  editing: boolean;
  onChange: (mut: (entries: string[]) => string[]) => void;
}) {
  if (!editing && entries.length === 0) return null;
  return (
    <div style={{ marginTop: 14, paddingTop: 10, borderTop: "1px solid #ccc" }}>
      <h5
        style={{
          margin: "0 0 8px",
          fontSize: 12,
          textTransform: "uppercase",
          letterSpacing: 0.3,
          color: "#444",
          fontWeight: 600,
        }}
      >
        General and GM-Assigned Modifers
      </h5>
      {editing ? (
        <>
          {entries.map((entry, i) => (
            <div key={i} style={{ display: "flex", gap: 4, marginBottom: 4 }}>
              <input
                type="text"
                value={entry}
                onChange={(e) => {
                  const v = e.target.value;
                  onChange((arr) => arr.map((x, j) => (j === i ? v : x)));
                }}
                style={{ flex: 1, fontSize: 12 }}
              />
              <button
                type="button"
                className="btn-link"
                onClick={() => onChange((arr) => arr.filter((_, j) => j !== i))}
                style={{ color: "#c00", fontSize: 11 }}
              >
                ✕
              </button>
            </div>
          ))}
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => onChange((arr) => [...arr, ""])}
            style={{ fontSize: 12, padding: "3px 8px" }}
          >
            + Add modifier
          </button>
        </>
      ) : (
        entries.map((entry, i) => {
          const idx = entry.lastIndexOf(":");
          const label = idx >= 0 ? entry.slice(0, idx).trim() : entry;
          const value = idx >= 0 ? entry.slice(idx + 1).trim() : "";
          return (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "baseline",
                gap: 6,
                fontSize: 12,
                marginBottom: 3,
              }}
            >
              <span style={{ color: "#333" }}>{label}</span>
              <span
                aria-hidden
                style={{
                  flex: 1,
                  borderBottom: "1px dotted #aaa",
                  marginBottom: 4,
                  minWidth: 12,
                }}
              />
              <span style={{
                color: "#333",
                fontVariantNumeric: "tabular-nums",
                whiteSpace: "nowrap",
                fontWeight: 500,
              }}>
                {value}
              </span>
            </div>
          );
        })
      )}
    </div>
  );
}

/** Fallback for tables that don't match the standard maneuver-table shape. */
function GenericTableBlock({
  table,
  editing,
  onChange,
}: {
  table: SkillTable;
  editing: boolean;
  onChange: (mut: (t: SkillTable) => void) => void;
}) {
  return (
    <div style={{ marginBottom: 20 }}>
      <h4 style={{ margin: "0 0 6px", fontSize: 14 }}>{table.name}</h4>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead>
          <tr style={{ background: "#fafafa", borderBottom: "1px solid #ddd" }}>
            {table.columns.map((c) => (
              <th key={c} style={{
                padding: "4px 6px", textAlign: "left",
                color: "#666", textTransform: "capitalize", whiteSpace: "nowrap",
              }}>
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, i) => (
            <tr key={i} style={{ borderBottom: "1px solid #f3f3f3" }}>
              {table.columns.map((c) => (
                <td key={c} style={{
                  padding: "3px 6px", color: "#333",
                  verticalAlign: "top", fontVariantNumeric: "tabular-nums",
                }}>
                  {editing ? (
                    <input
                      type="text"
                      value={(row as unknown as Record<string, string | null>)[c] ?? ""}
                      onChange={(e) => {
                        const v = e.target.value === "" ? null : e.target.value;
                        onChange((t) => {
                          (t.rows[i] as unknown as Record<string, string | null>)[c] = v;
                        });
                      }}
                      style={inlineInputStyle}
                    />
                  ) : (
                    (row as unknown as Record<string, string | null>)[c] ?? ""
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <GeneralModsFooter
        entries={table.general_mods}
        editing={editing}
        onChange={(mut) => onChange((t) => { t.general_mods = mut(t.general_mods); })}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// shared inline styles (kept here so the rest of the file stays declarative)
// ---------------------------------------------------------------------------

const textareaStyle: React.CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  padding: "6px 8px",
  border: "1px solid #ccc",
  borderRadius: 4,
  fontFamily: "inherit",
  fontSize: 13,
  lineHeight: 1.5,
  resize: "vertical",
};

const inlineInputStyle: React.CSSProperties = {
  width: "100%",
  fontSize: 12,
  padding: "2px 4px",
  border: "1px solid #ccc",
  borderRadius: 3,
  boxSizing: "border-box",
};
