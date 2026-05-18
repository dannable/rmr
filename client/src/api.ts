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
  basic_bonus: number;
}

export interface StatsRR {
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

export interface CharacterStats {
  stats: StatRow[];
  resistance_rolls: StatsRR;
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
