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
