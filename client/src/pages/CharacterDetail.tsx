import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";

import {
  deleteCharacter,
  fetchBackgroundOptions,
  fetchCharacter,
  fetchCharacterAdolescence,
  fetchCharacterStats,
  HttpError,
  type BackgroundOptionsResponse,
  type Character,
  type CharacterAdolescence,
  type CharacterStats,
} from "../api";
import { AdolescenceRanks } from "../components/AdolescenceRanks";
import { BackgroundOptions } from "../components/BackgroundOptions";
import { CulturePicker } from "../components/CulturePicker";
import { ProfessionPicker } from "../components/ProfessionPicker";
import { RacePicker } from "../components/RacePicker";
import { StatsEditor } from "../components/StatsEditor";

/**
 * Character builder page, segmented into the 8-step RMSS Character
 * Design Summary flow (RMSS Character Law p.11).
 *
 * The 8 steps appear as tabs across the top; clicking jumps without
 * any "next/prev" gating, since players often revisit earlier steps
 * after seeing later ones. A small ✓ on each tab signals that the
 * step has data we recognize as complete; the completion predicates
 * are intentionally generous (presence-based rather than strict RMSS
 * validity).
 *
 * Current data:
 *   Step 1 (concept):        placeholder — no schema field yet
 *   Step 2 (race+prof+realm): RacePicker + ProfessionPicker + derived realm
 *   Step 3 (stats):           StatsEditor with RMSS T-1.2 budget banner
 *   Step 4 (adolescence):     AdolescenceRanks
 *   Step 5 (background opts): BackgroundOptions (T-1.5)
 *   Step 6 (apprenticeship):  placeholder — DP allocator TBD
 *   Step 7 (role traits):     placeholder
 *   Step 8 (finalize):        placeholder
 */
export function CharacterDetailPage() {
  const { id } = useParams<{ id: string }>();
  const characterId = Number(id);

  if (!characterId || Number.isNaN(characterId)) {
    return <Navigate to="/" replace />;
  }

  return <CharacterDetail characterId={characterId} />;
}

type StepId =
  | "concept"
  | "choices"
  | "stats"
  | "adolescence"
  | "background"
  | "apprenticeship"
  | "role"
  | "finalize";

interface StepDef {
  id: StepId;
  number: number;
  title: string;
  subtitle?: string;
}

const STEPS: StepDef[] = [
  { id: "concept",        number: 1, title: "Concept",       subtitle: "Decide what type of character to play" },
  { id: "choices",        number: 2, title: "Initial Choices", subtitle: "Race · Profession · Realm" },
  { id: "stats",          number: 3, title: "Stats",          subtitle: "Temporary + Potential" },
  { id: "adolescence",    number: 4, title: "Adolescence",    subtitle: "Starting skill ranks (T-1.6)" },
  { id: "background",     number: 5, title: "Background",     subtitle: "T-1.5 options" },
  { id: "apprenticeship", number: 6, title: "Apprenticeship", subtitle: "1st-level DP allocator" },
  { id: "role",           number: 7, title: "Role",           subtitle: "Traits + setting details" },
  { id: "finalize",       number: 8, title: "Finalize",       subtitle: "PP · Hits · DB · RR · MMP" },
];


function CharacterDetail({ characterId }: { characterId: number }) {
  const qc = useQueryClient();
  const navigate = useNavigate();

  const q = useQuery<Character>({
    queryKey: ["characters", characterId],
    queryFn: () => fetchCharacter(characterId),
    throwOnError: (e) => !(e instanceof HttpError && e.status === 404),
  });

  // Side fetches feed the completion-tick predicates without forcing a
  // full re-render of each step component.
  const statsQ = useQuery<CharacterStats>({
    queryKey: ["characters", characterId, "stats"],
    queryFn: () => fetchCharacterStats(characterId),
    enabled: !!q.data,
  });
  const adolQ = useQuery<CharacterAdolescence>({
    queryKey: ["characters", characterId, "adolescence-ranks"],
    queryFn: () => fetchCharacterAdolescence(characterId),
    enabled: !!q.data,
  });
  const bgQ = useQuery<BackgroundOptionsResponse>({
    queryKey: ["characters", characterId, "background-options"],
    queryFn: () => fetchBackgroundOptions(characterId),
    enabled: !!q.data,
  });

  // Tab selection. Persists via the URL hash so reload / sharing keeps
  // the user on the same step.
  const initialTab = (window.location.hash.replace(/^#/, "") || "choices") as StepId;
  const [active, setActiveState] = useState<StepId>(initialTab);
  const setActive = (s: StepId) => {
    setActiveState(s);
    history.replaceState(null, "", `#${s}`);
  };

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
  const done = computeCompletion(c, statsQ.data, adolQ.data, bgQ.data);

  return (
    <section>
      {/* No local main override: the shell Layout already opens to ~1500px,
          which is plenty for the 8 builder tabs + stats grid + RR panel. */}

      <Link to="/" style={{ fontSize: 13, color: "#666" }}>← Back</Link>

      <h2 style={{ marginTop: 8 }}>{c.name}</h2>
      <p style={{ color: "#666", margin: "4px 0 16px" }}>
        Level {c.level}
        {c.race_name && <span style={{ marginLeft: 8 }}> · {c.race_name}</span>}
        {c.profession_name && <span style={{ marginLeft: 8 }}> · {c.profession_name}</span>}
      </p>

      <TabBar active={active} setActive={setActive} done={done} />

      <div style={{ paddingTop: 16 }}>
        {active === "concept"        && <ConceptStep character={c} />}
        {active === "choices"        && <ChoicesStep character={c} />}
        {active === "stats"          && <StatsStep   character={c} />}
        {active === "adolescence"    && <AdolescenceStep character={c} />}
        {active === "background"     && <BackgroundStep  character={c} />}
        {active === "apprenticeship" && <PlaceholderStep title="Apprenticeship Skills"
                                            body="Allocate 1st-level development points across training packages, skill development, and stat gains. DP allocator coming in a follow-up PR." />}
        {active === "role"           && <PlaceholderStep title="Role Traits + Background Details"
                                            body="Free-form role-traits and setting-specific background notes. Tracking field coming in a follow-up PR." />}
        {active === "finalize"       && <PlaceholderStep title="Finalize Character"
                                            body="Total stat + skill bonuses, age, level + XP, outfitting, power points, hits, defensive bonus, spells, RR bonuses, MMP, base movement. Coming in follow-up PRs." />}
      </div>

      <hr style={{ marginTop: 24 }} />
      <div style={{ marginTop: 16 }}>
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


// ---------------------------------------------------------------------------
// completion predicates — purposefully forgiving (presence over validity)
// ---------------------------------------------------------------------------

type Completion = Record<StepId, boolean>;

function computeCompletion(
  c: Character,
  stats: CharacterStats | undefined,
  adol: CharacterAdolescence | undefined,
  bg: BackgroundOptionsResponse | undefined,
): Completion {
  return {
    concept: false,                  // no schema field yet
    choices: !!c.race_id && !!c.profession_id,
    stats: stats
      ? // "Done" when the budget is fully spent (within 5 pts) AND every
        // prime stat meets its minimum.
        Math.abs(stats.budget.spent - stats.budget.budget) <= 5 &&
        stats.stats.filter((s) => s.is_prime).every((s) => s.temp >= stats.budget.prime_min)
      : false,
    adolescence: !!adol && adol.groups.length > 0,
    background: !!bg && bg.max_options > 0 && bg.picks.length >= bg.max_options,
    apprenticeship: false,
    role: false,
    finalize: false,
  };
}


// ---------------------------------------------------------------------------
// tab bar
// ---------------------------------------------------------------------------

function TabBar({
  active,
  setActive,
  done,
}: {
  active: StepId;
  setActive: (s: StepId) => void;
  done: Completion;
}) {
  // Each tab gets `flex: 1` so all 8 distribute evenly across the bar
  // and the row never needs to scroll. `whiteSpace: nowrap` keeps a
  // long label like "Apprenticeship" on a single line at narrower
  // widths; if the viewport ever gets so cramped that text would clip,
  // ellipsis kicks in rather than wrapping into a second row.
  return (
    <nav
      style={{
        display: "flex",
        gap: 2,
        borderBottom: "1px solid #d0d4dc",
        flexWrap: "nowrap",
      }}
    >
      {STEPS.map((s) => {
        const isActive = s.id === active;
        const isDone = done[s.id];
        return (
          <button
            key={s.id}
            onClick={() => setActive(s.id)}
            title={s.subtitle}
            style={{
              flex: "1 1 0",
              minWidth: 0,            // allow shrinking past content width
              padding: "10px 12px",
              border: "1px solid transparent",
              borderBottom: "none",
              background: isActive ? "white" : "#eef1f7",
              borderColor: isActive ? "#d0d4dc" : "transparent",
              borderTopLeftRadius: 6,
              borderTopRightRadius: 6,
              cursor: "pointer",
              fontSize: 13,
              fontWeight: isActive ? 600 : 500,
              color: isActive ? "#222" : "#566",
              position: "relative",
              top: 1,
              display: "flex",
              gap: 6,
              alignItems: "baseline",
              justifyContent: "center",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            <span style={{
              fontSize: 11,
              color: "#888",
              fontVariantNumeric: "tabular-nums",
              flexShrink: 0,
            }}>
              {s.number}.
            </span>
            <span style={{
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}>
              {s.title}
            </span>
            {isDone && (
              <span
                style={{ color: "#16a34a", fontSize: 12, flexShrink: 0 }}
                aria-label="done"
              >
                ✓
              </span>
            )}
          </button>
        );
      })}
    </nav>
  );
}


// ---------------------------------------------------------------------------
// step bodies
// ---------------------------------------------------------------------------

function StepHeader({ step }: { step: StepDef }) {
  return (
    <header style={{ marginBottom: 12 }}>
      <h3 style={{ margin: 0 }}>
        <span style={{ color: "#888", fontWeight: 500, marginRight: 8 }}>
          Step {step.number}
        </span>
        {step.title}
      </h3>
      {step.subtitle && (
        <p style={{ margin: "2px 0 0", color: "#666", fontSize: 13 }}>
          {step.subtitle}
        </p>
      )}
    </header>
  );
}


function ConceptStep({ character }: { character: Character }) {
  // Stub for now — no schema field for concept yet. Just show the name +
  // a hint about what this step is for.
  return (
    <div>
      <StepHeader step={STEPS[0]} />
      <p style={{ color: "#444" }}>
        Discuss your general character concept with your GM. Together, finalize
        what kind of character <strong>{character.name}</strong> will be —
        background, motivations, role in the party.
      </p>
      <p style={{ color: "#888", fontSize: 13, fontStyle: "italic" }}>
        A concept text field will land in a follow-up PR. For now, jot your
        ideas down outside the tool.
      </p>
    </div>
  );
}


function ChoicesStep({ character }: { character: Character }) {
  // Realm of power is derived from profession. Detail comes from the
  // ProfessionPicker's existing fetch; here we just show a one-line
  // summary above the pickers.
  //
  // The CulturePicker only renders when race_is_umbrella is true — it
  // self-hides for concrete races, so there's no need to gate it here.
  return (
    <div>
      <StepHeader step={STEPS[1]} />
      <RacePicker character={character} />
      <CulturePicker character={character} />
      <hr />
      <ProfessionPicker character={character} />
      <hr />
      <div>
        <h3 style={{ margin: "0 0 6px", fontSize: 15 }}>Realm of Power</h3>
        <p style={{ margin: 0, color: "#444", fontSize: 14 }}>
          {character.profession_name
            ? <>Derived from your profession ({character.profession_name}). See the profession's "Realm(s)" line above.</>
            : <span style={{ color: "#888" }}>Pick a profession to determine your realm of power.</span>}
        </p>
      </div>
    </div>
  );
}


function StatsStep({ character }: { character: Character }) {
  return (
    <div>
      <StepHeader step={STEPS[2]} />
      <StatsEditor characterId={character.character_id} />
    </div>
  );
}


function AdolescenceStep({ character }: { character: Character }) {
  return (
    <div>
      <StepHeader step={STEPS[3]} />
      <AdolescenceRanks
        characterId={character.character_id}
        raceSlug={character.race_slug}
        cultureSlug={character.culture_slug}
        raceIsUmbrella={character.race_is_umbrella}
      />
    </div>
  );
}


function BackgroundStep({ character }: { character: Character }) {
  return (
    <div>
      <StepHeader step={STEPS[4]} />
      <BackgroundOptions
        characterId={character.character_id}
        raceSlug={character.race_slug}
      />
    </div>
  );
}


function PlaceholderStep({ title, body }: { title: string; body: string }) {
  return (
    <div>
      <h3 style={{ marginTop: 0 }}>{title}</h3>
      <p style={{ color: "#666" }}>{body}</p>
    </div>
  );
}
