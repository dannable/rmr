/**
 * Tiny fetch wrapper that always sends cookies (session) and parses JSON.
 * Throws an Error with a `status` field on non-2xx; throws a special
 * UnauthenticatedError on 401 so the UI can branch on logged-in state.
 */

export class HttpError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export class UnauthenticatedError extends HttpError {
  constructor() {
    super(401, "Not authenticated");
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init.headers || {}) },
    ...init,
  });
  if (res.status === 401) throw new UnauthenticatedError();
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new HttpError(res.status, body || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export interface Me {
  user_id: number;
  discord_id: string;
  discord_username: string | null;
  discord_avatar: string | null;
}

export const fetchMe = () => api<Me>("/api/v1/me");
export const logout = () => api<void>("/auth/logout", { method: "POST" });

// ---- characters --------------------------------------------------------

export interface Character {
  character_id: number;
  owner_user_id: number;
  name: string;
  level: number;
  created_at: string;
  updated_at: string;
  // Chargen progress fields — NULL when not picked yet.
  race_id: number | null;
  race_slug: string | null;
  race_name: string | null;
  profession_id: number | null;
  profession_slug: string | null;
  profession_name: string | null;
}

export const fetchCharacters = () =>
  api<Character[]>("/api/v1/characters");

export const fetchCharacter = (id: number) =>
  api<Character>(`/api/v1/characters/${id}`);

export const createCharacter = (name: string) =>
  api<Character>("/api/v1/characters", {
    method: "POST",
    body: JSON.stringify({ name }),
  });

export const deleteCharacter = (id: number) =>
  api<void>(`/api/v1/characters/${id}`, { method: "DELETE" });

export const updateCharacterRace = (id: number, slug: string | null) =>
  api<Character>(`/api/v1/characters/${id}/race`, {
    method: "PUT",
    body: JSON.stringify({ slug }),
  });

export const updateCharacterProfession = (id: number, slug: string | null) =>
  api<Character>(`/api/v1/characters/${id}/profession`, {
    method: "PUT",
    body: JSON.stringify({ slug }),
  });

// ---- adolescence (starting skill ranks from RMSS T-1.6) ----------------

export interface AdolescenceSkill {
  name: string;
  value: string;
  /** Set when this row needs a player pick before it can be applied. */
  choice_kind: "text" | "select" | null;
  /** Dropdown options when choice_kind === "select". */
  choice_options: string[] | null;
  /** Player's saved pick, or null if not yet chosen. */
  choice: string | null;
}

export interface AdolescenceGroup {
  category: string;
  value: string;
  skills: AdolescenceSkill[];
}

export interface CharacterAdolescence {
  culture_slug: string | null;
  culture_name: string | null;
  groups: AdolescenceGroup[];
}

export interface AdolescenceApplyResult {
  applied: number;
  skipped_pending: string[];
}

export const fetchCharacterAdolescence = (id: number) =>
  api<CharacterAdolescence>(`/api/v1/characters/${id}/adolescence-ranks`);

export const updateAdolescenceChoices = (
  id: number,
  choices: { t16_row: string; choice: string }[],
) =>
  api<CharacterAdolescence>(`/api/v1/characters/${id}/adolescence-choices`, {
    method: "PUT",
    body: JSON.stringify({ choices }),
  });

export const applyAdolescenceRanks = (id: number) =>
  api<AdolescenceApplyResult>(`/api/v1/characters/${id}/apply-adolescence`, {
    method: "POST",
  });

// ---- character stats ---------------------------------------------------

export type StatCode = "Ag" | "Co" | "Me" | "Re" | "SD" | "Em" | "In" | "Pr" | "Qu" | "St";

export const STAT_CODES: readonly StatCode[] = [
  "Ag", "Co", "Me", "Re", "SD", "Em", "In", "Pr", "Qu", "St",
] as const;

export interface StatRow {
  code: StatCode;
  name: string;
  temp: number;
  potential: number;
  race_mod: number;       // T-1.1 race modifier (0 when no race set)
  basic_bonus: number;    // T-2.1 bonus from (temp + race_mod)
}

export interface StatsRR {
  // Race-inclusive totals from the API.
  channeling: number;
  essence: number;
  mentalism: number;
  chan_ess: number;
  chan_ment: number;
  ess_ment: number;
  arcane: number;
  poison_disease: number;
  fear: number;
}

export interface StatsRaceInfo {
  slug: string;
  name: string;
}

export interface CharacterStats {
  stats: StatRow[];
  resistance_rolls: StatsRR;       // formula + race contribution (totals)
  race_rr_mods: StatsRR;           // race contribution only (zero if unraced)
  race: StatsRaceInfo | null;
}

export const fetchCharacterStats = (id: number) =>
  api<CharacterStats>(`/api/v1/characters/${id}/stats`);

export const updateCharacterStats = (
  id: number,
  stats: { code: StatCode; temp: number; potential: number }[],
) =>
  api<CharacterStats>(`/api/v1/characters/${id}/stats`, {
    method: "PUT",
    body: JSON.stringify({ stats }),
  });

// ---- races -------------------------------------------------------------

export interface RaceRRMods {
  channeling: number;
  essence: number;
  mentalism: number;
  chan_ess: number;
  chan_ment: number;
  ess_ment: number;
  arcane: number;
  poison_disease: number;
  fear: number;
}

export interface Race {
  slug: string;
  name: string;
  stat_mods: Record<StatCode, number>;
  rr_mods: RaceRRMods;
  bg_opts: number;
  body_dev_prog: string;
  chan_pp_prog: string;
  ess_pp_prog: string;
  ment_pp_prog: string;
  // Rich culture data extracted from the RMSS Cultures & Races appendix.
  // Keys vary by race; Common Men + Mixed Men have an empty object since
  // the source PDF doesn't cover them. See bottom of RacePicker for the
  // canonical field-key catalog.
  culture_data: Record<string, string>;
}

export const fetchRaces = () => api<Race[]>("/api/v1/races");

// ---- professions -------------------------------------------------------

export interface ProfessionRow {
  slug: string;
  name: string;
  description: string;
  realms: string[];
  prime_stats: string[];
  portrait_path: string | null;
}

export interface ProfessionGroupBonus {
  group_name: string;
  bonus: number;
}

export interface ProfessionCategoryBonus {
  group_name: string;
  category_name: string;
  bonus: number;
}

export interface ProfessionCategoryCost {
  group_name: string;
  category_name: string;
  cost: string;
}

export interface ProfessionSkillCostModifier {
  group_name: string;
  category_name: string;
  skill_name: string;
  classification: string;
  modifier: number;
}

export interface ProfessionFavoriteSkill {
  group_name: string;
  category_name: string;
  skill_name: string;
  classification: string;
}

export interface ProfessionDetail {
  slug: string;
  name: string;
  description: string;
  portrait_path: string | null;
  realms: string[];
  prime_stats: string[];
  group_bonuses: ProfessionGroupBonus[];
  category_bonuses: ProfessionCategoryBonus[];
  category_costs: ProfessionCategoryCost[];
  skill_cost_modifiers: ProfessionSkillCostModifier[];
  favorite_skills: ProfessionFavoriteSkill[];
}

export const fetchProfessions = () =>
  api<ProfessionRow[]>("/api/v1/professions");

export const fetchProfession = (slug: string) =>
  api<ProfessionDetail>(`/api/v1/professions/${encodeURIComponent(slug)}`);

// ---- spells ------------------------------------------------------------

export interface SpellClassRow {
  class_name: string;
  realm_name: string;
}

export interface SpellListRow {
  list_id: number;
  name: string;
  list_number: string;
  category: string;
  realm_name: string;
}

export interface ClassListRow {
  name: string;
  list_number: string;
  category: string;
}

export interface SpellListDetail {
  list_id: number;
  name: string;
  list_number: string;
  category: string;
  realm_name: string;
  classes: string[];
}

export interface SpellSummary {
  level: number;
  name: string;
  area_effect: string | null;
  duration: string | null;
  range_str: string | null;
  spell_type: string | null;
  starred: boolean;
}

export interface Spell {
  list_id: number;
  list_name: string;
  list_number: string;
  category: string;
  realm_name: string;
  level: number;
  name: string;
  area_effect: string | null;
  duration: string | null;
  range_str: string | null;
  spell_type: string | null;
  starred: boolean;
  description: string | null;
  updated_at: string | null;
  updated_by_user_id: number | null;
}

export interface SpellUpdate {
  name?: string;
  area_effect?: string | null;
  duration?: string | null;
  range_str?: string | null;
  spell_type?: string | null;
  description?: string | null;
  starred?: boolean;
}

export interface SpellSearchHit {
  level: number;
  name: string;
  spell_type: string | null;
  list_name: string;
  list_number: string;
  category: string;
}

export const fetchSpellClasses = () =>
  api<SpellClassRow[]>("/api/v1/spells/classes");

export const fetchClassLists = (className: string) =>
  api<ClassListRow[]>(`/api/v1/spells/classes/${encodeURIComponent(className)}/lists`);

export const fetchSpellLists = () =>
  api<SpellListRow[]>("/api/v1/spells/lists");

export const fetchSpellList = (listId: number) =>
  api<SpellListDetail>(`/api/v1/spells/lists/${listId}`);

export const fetchListSpells = (listId: number) =>
  api<SpellSummary[]>(`/api/v1/spells/lists/${listId}/spells`);

export const fetchSpell = (listId: number, level: number) =>
  api<Spell>(`/api/v1/spells/lists/${listId}/spells/${level}`);

export const updateSpell = (listId: number, level: number, body: SpellUpdate) =>
  api<Spell>(`/api/v1/spells/lists/${listId}/spells/${level}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const searchSpellsByName = (q: string, limit = 25) =>
  api<SpellSearchHit[]>(
    `/api/v1/spells/search?q=${encodeURIComponent(q)}&limit=${limit}`,
  );

// ---- skills catalog (RMSS Appendix A-1) --------------------------------

export interface SkillGroupRow {
  slug: string;
  section: string;
  name: string;
  page_div: number;
  page_content: number;
}

export interface SkillCategory {
  name: string;
  skills_list: string | null;
  restricted: string | null;
  stat_bonuses: string | null;
  rank_progression: string | null;
  category_progression: string | null;
  parent_group: string | null;
  classification: string | null;
  description: string | null;
}

export interface SkillEntry {
  name: string;
  stat: string | null;
  description: string | null;
}

export interface SkillTableRow {
  roll: string | null;
  result: string | null;
  percent: string | null;
  time: string | null;
  mod: string | null;
  description: string | null;
}

export interface SkillTable {
  name: string;
  columns: string[];
  /**
   * "General and GM-Assigned Modifers" footer entries from the source PDF
   * (e.g. "Practiced piece: +(1-3 x Memory bonus)"). Empty when the source
   * table has no such footer. Each entry is a full "Label: value" string.
   */
  general_mods: string[];
  rows: SkillTableRow[];
}

export interface SkillGroupDetail {
  slug: string;
  section: string;
  name: string;
  page_div: number;
  page_content: number;
  categories: SkillCategory[];
  skills: SkillEntry[];
  tables: SkillTable[];
  updated_at: string | null;
  updated_by_user_id: number | null;
}

/**
 * Wholesale-replace payload for `PUT /api/v1/skills/{slug}`. The server
 * wipes the group's categories/skills/tables and re-inserts from this
 * payload, then re-serialises data/skills/<slug>.txt.
 */
export interface SkillGroupUpdate {
  name?: string;
  categories: SkillCategory[];
  skills: SkillEntry[];
  tables: SkillTable[];
}

export interface SkillSearchHit {
  name: string;
  stat: string | null;
  group_slug: string;
  section: string;
  group_name: string;
}

export const fetchSkillGroups = () =>
  api<SkillGroupRow[]>("/api/v1/skills");

export const fetchSkillGroup = (slug: string) =>
  api<SkillGroupDetail>(`/api/v1/skills/${encodeURIComponent(slug)}`);

export const updateSkillGroup = (slug: string, body: SkillGroupUpdate) =>
  api<SkillGroupDetail>(`/api/v1/skills/${encodeURIComponent(slug)}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const searchSkills = (q: string, limit = 25) =>
  api<SkillSearchHit[]>(
    `/api/v1/skills/search?q=${encodeURIComponent(q)}&limit=${limit}`,
  );
