/**
 * Mirror of core/chargen/skills.py rank progressions — RMSS T-2.2.
 *
 * The SPA uses these to recompute the rank-bonus immediately when the
 * player clicks +/- in the SkillAllocator, so totals update without
 * waiting for the server PUT to round-trip. The server stays the source
 * of truth — these formulas just provide an optimistic preview.
 *
 * Keep in sync with the Python module. The test suite over there pins
 * every cell on T-2.2, so a deviation here will be a SPA-only bug.
 */

export function standardSkillBonus(ranks: number): number {
  if (ranks <= 0) return -15;
  let bonus = 0;
  if (ranks > 30) { bonus += 0.5 * (ranks - 30); ranks = 30; }
  if (ranks > 20) { bonus += 1.0 * (ranks - 20); ranks = 20; }
  if (ranks > 10) { bonus += 2.0 * (ranks - 10); ranks = 10; }
  bonus += 3.0 * ranks;
  return bonus;
}

export function standardCategoryBonus(ranks: number): number {
  if (ranks <= 0) return -15;
  if (ranks >= 31) return 35;     // caps per T-2.2 footer
  let bonus = 0;
  if (ranks > 20) { bonus += 0.5 * (ranks - 20); ranks = 20; }
  if (ranks > 10) { bonus += 1.0 * (ranks - 10); ranks = 10; }
  bonus += 2.0 * ranks;
  return bonus;
}

export function combinedSkillBonus(ranks: number): number {
  if (ranks <= 0) return -30;
  let bonus = 0;
  if (ranks > 30) { bonus += 0.5 * (ranks - 30); ranks = 30; }
  if (ranks > 20) { bonus += 1.5 * (ranks - 20); ranks = 20; }
  if (ranks > 10) { bonus += 3.0 * (ranks - 10); ranks = 10; }
  bonus += 5.0 * ranks;
  return bonus;
}

export function limitedSkillBonus(ranks: number): number {
  if (ranks <= 0) return 0;
  if (ranks >= 31) return 25;
  if (ranks > 20) return 20 + 0.5 * (ranks - 20);
  return ranks;
}

export function specialSkillBonus(ranks: number): number {
  if (ranks <= 0) return 0;
  let bonus = 0;
  if (ranks > 30) { bonus += 3.0 * (ranks - 30); ranks = 30; }
  if (ranks > 20) { bonus += 4.0 * (ranks - 20); ranks = 20; }
  if (ranks > 10) { bonus += 5.0 * (ranks - 10); ranks = 10; }
  bonus += 6.0 * ranks;
  return bonus;
}

/** Parse a dotted progression like "0 • 7 • 5 • 3 • 1". Returns [] for
 *  empty / non-numeric input (caller falls back to default). */
function parseDottedProgression(text: string): number[] {
  const out: number[] = [];
  for (const part of text.replace(/•/g, "·").split("·")) {
    const t = part.trim();
    if (!t) continue;
    const n = Number(t);
    if (Number.isNaN(n)) return [];
    out.push(n);
  }
  return out;
}

/** Dispatch on the progression label. Mirror of progression_bonus in
 *  core/chargen/skills.py. `isCategory=true` keeps the "Combined" /
 *  "Limited" / "Special" tags fallback to Standard Category, matching
 *  the server. */
export function progressionBonus(
  progressionText: string,
  ranks: number,
  isCategory: boolean,
): number {
  const txt = (progressionText || "").trim();
  if (txt === "" || txt === "Standard") {
    return isCategory ? standardCategoryBonus(ranks) : standardSkillBonus(ranks);
  }
  if (txt === "Combined") {
    return isCategory ? standardCategoryBonus(ranks) : combinedSkillBonus(ranks);
  }
  if (txt === "Limited") {
    return isCategory ? standardCategoryBonus(ranks) : limitedSkillBonus(ranks);
  }
  if (txt === "Special") {
    return isCategory ? standardCategoryBonus(ranks) : specialSkillBonus(ranks);
  }
  const tokens = parseDottedProgression(txt);
  if (tokens.length === 0) {
    return isCategory ? standardCategoryBonus(ranks) : standardSkillBonus(ranks);
  }
  let bonus = 0;
  let remaining = Math.max(0, ranks);
  let band = 0;
  while (remaining > 0 && band < tokens.length) {
    const take = Math.min(remaining, 10);
    bonus += tokens[band] * take;
    remaining -= take;
    band += 1;
  }
  return bonus;
}
