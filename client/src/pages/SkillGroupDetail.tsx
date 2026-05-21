import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, useParams } from "react-router-dom";

import {
  fetchSkillGroup,
  HttpError,
  type SkillGroupDetail as Detail,
  type SkillCategory,
  type SkillEntry,
  type SkillTable,
} from "../api";

/**
 * One skill-category-group from RMSS Appendix A-1: shows the per-category
 * metadata blocks, the per-skill description blocks, and any embedded
 * maneuver/lookup tables.
 */
export function SkillGroupDetailPage() {
  const { slug } = useParams<{ slug: string }>();
  if (!slug) return <Navigate to="/skills" replace />;
  return <SkillGroupView slug={slug} />;
}

function SkillGroupView({ slug }: { slug: string }) {
  const q = useQuery<Detail>({
    queryKey: ["skill-group", slug],
    queryFn: () => fetchSkillGroup(slug),
    throwOnError: (e) => !(e instanceof HttpError && e.status === 404),
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
  return (
    <section>
      <Link to="/skills" style={{ fontSize: 13, color: "#666" }}>← Skills</Link>
      <h2 style={{ marginTop: 8 }}>{g.name}</h2>
      <p style={{ color: "#666", margin: "4px 0 0" }}>
        {g.section} — RMSS Appendix A-1 pages {g.page_div}–{g.page_content}
      </p>

      <hr />

      <h3 style={{ margin: "0 0 8px", fontSize: 15 }}>Categories</h3>
      {g.categories.map((c, i) => (
        <CategoryBlock key={`${c.name}-${i}`} cat={c} />
      ))}

      {g.skills.length > 0 && (
        <>
          <hr />
          <h3 style={{ margin: "0 0 8px", fontSize: 15 }}>Skill descriptions</h3>
          {g.skills.map((s, i) => (
            <SkillBlock key={`${s.name}-${i}`} skill={s} />
          ))}
        </>
      )}

      {g.tables.length > 0 && (
        <>
          <hr />
          <h3 style={{ margin: "0 0 8px", fontSize: 15 }}>Embedded tables</h3>
          {g.tables.map((t, i) => (
            <TableBlock key={`${t.name}-${i}`} table={t} />
          ))}
        </>
      )}
    </section>
  );
}

function CategoryBlock({ cat }: { cat: SkillCategory }) {
  return (
    <div style={{ marginBottom: 16, paddingBottom: 12, borderBottom: "1px solid #eee" }}>
      <h4 style={{ margin: "0 0 6px", fontSize: 14 }}>{cat.name}</h4>
      <dl
        style={{
          display: "grid",
          gridTemplateColumns: "180px 1fr",
          gap: "2px 12px",
          fontSize: 13,
          margin: 0,
        }}
      >
        <Field label="Skills" value={cat.skills_list} />
        <Field label="Restricted" value={cat.restricted} />
        <Field label="Stat Bonuses" value={cat.stat_bonuses} />
        <Field label="Rank Progression" value={cat.rank_progression} />
        <Field label="Category Progression" value={cat.category_progression} />
        <Field label="Group" value={cat.parent_group} />
        <Field label="Classification" value={cat.classification} />
      </dl>
      {cat.description && (
        <p style={{ marginTop: 8, fontSize: 13, color: "#444", whiteSpace: "pre-wrap" }}>
          {cat.description}
        </p>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <>
      <dt style={{ color: "#888" }}>{label}</dt>
      <dd style={{ margin: 0, color: "#333" }}>{value}</dd>
    </>
  );
}

function SkillBlock({ skill }: { skill: SkillEntry }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <h4 style={{ margin: "0 0 4px", fontSize: 14 }}>
        {skill.name}
        {skill.stat && (
          <span style={{ marginLeft: 8, color: "#888", fontSize: 12 }}>
            ({skill.stat})
          </span>
        )}
      </h4>
      {skill.description && (
        <p style={{ margin: 0, fontSize: 13, color: "#444", whiteSpace: "pre-wrap" }}>
          {skill.description}
        </p>
      )}
    </div>
  );
}

function TableBlock({ table }: { table: SkillTable }) {
  // Most embedded tables are RMSS Static Maneuver Tables — six columns
  // (roll, result, percent, time, mod, description). For those we use a
  // PDF-style per-row layout: bold roll + result on the left, mod values
  // right-aligned on the same line, description indented beneath. Tables
  // with a different column set fall through to the plain HTML <table>.
  const isManeuverTable = isExpectedColumns(
    table.columns,
    ["roll", "result", "percent", "time", "mod", "description"],
  );
  if (isManeuverTable) {
    return <ManeuverTableBlock table={table} />;
  }
  return <GenericTableBlock table={table} />;
}


function isExpectedColumns(actual: string[], expected: string[]): boolean {
  if (actual.length !== expected.length) return false;
  return actual.every((c, i) => c.toLowerCase() === expected[i].toLowerCase());
}


/** PDF-style Static Maneuver Table layout — mirrors RMSS T-4.8.x. */
function ManeuverTableBlock({ table }: { table: SkillTable }) {
  return (
    <div style={{ marginBottom: 20 }}>
      <h4 style={{
        margin: "0 0 8px",
        fontSize: 13,
        textAlign: "center",
        textTransform: "uppercase",
        letterSpacing: 0.3,
        borderBottom: "1px solid #ccc",
        paddingBottom: 4,
      }}>
        {table.name}
      </h4>
      {table.rows.map((row, i) => (
        <ManeuverRow key={i} row={row} />
      ))}
    </div>
  );
}


function ManeuverRow({ row }: { row: SkillTableRow }) {
  const modParts: string[] = [];
  if (row.percent) modParts.push(row.percent);
  if (row.time)    modParts.push(row.time);
  if (row.mod)     modParts.push(row.mod);
  const modText = modParts.join(" • ");
  const showColon = !!row.result;

  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "baseline",
        gap: 12,
        fontSize: 13,
      }}>
        <div style={{ fontWeight: 600, color: "#222" }}>
          {row.roll && <span style={{ marginRight: 8 }}>{row.roll}</span>}
          {row.result}{showColon ? ":" : ""}
        </div>
        {modText && (
          <div style={{
            color: "#666",
            fontVariantNumeric: "tabular-nums",
            whiteSpace: "nowrap",
            fontSize: 12,
          }}>
            {modText}
            {row.mod && (
              <span style={{ marginLeft: 6 }}>➡</span>
            )}
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


/** Fallback for tables that don't match the standard maneuver-table shape. */
function GenericTableBlock({ table }: { table: SkillTable }) {
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
                  {(row as unknown as Record<string, string | null>)[c] ?? ""}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
