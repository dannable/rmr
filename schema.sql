-- Rolemaster Fantasy Roleplaying Suite — core schema
-- SQLite dialect.

PRAGMA foreign_keys = ON;

-- =========================================================================
-- Critical Strike Tables (must come before weapon, so weapon can FK into it)
-- =========================================================================

CREATE TABLE IF NOT EXISTS critical_strike_table (
    crit_table_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,        -- "Slash", "Puncture", "Krush", "Martial Arts Sweeps", ...
    table_number    TEXT    NOT NULL,               -- "4.6", "4.7", ...
    crit_type_code  TEXT CHECK (crit_type_code IN ('G','K','P','S','T','U')),  -- letter when one applies
    column_axis     TEXT NOT NULL DEFAULT 'severity'
                    CHECK (column_axis IN ('severity','attack_type')),
    notes           TEXT
);

-- One row per (table, roll-band, column) cell.
-- For column_axis='severity' charts, the `severity` column holds A/B/C/D/E.
-- For column_axis='attack_type' charts (Large Creature, Super Large Creature),
-- it holds named labels like 'normal','magic','mithril','holy_arms','slaying'.
-- Plain TEXT (no CHECK) so both shapes share the table.
CREATE TABLE IF NOT EXISTS critical_result (
    crit_table_id  INTEGER NOT NULL REFERENCES critical_strike_table(crit_table_id) ON DELETE CASCADE,
    roll_min       INTEGER NOT NULL,
    roll_max       INTEGER NOT NULL,
    severity       TEXT    NOT NULL,
    narrative      TEXT,                            -- flavor text
    PRIMARY KEY (crit_table_id, roll_min, severity),
    CHECK (roll_min <= roll_max)
);

-- One or more effect rows per cell.
-- Most cells have exactly one (condition NULL); cells with armor-conditional
-- alternates have two rows (e.g. "with helmet" / "without helmet").
CREATE TABLE IF NOT EXISTS critical_result_effect (
    crit_table_id    INTEGER NOT NULL,
    roll_min         INTEGER NOT NULL,
    severity         TEXT    NOT NULL,
    condition        TEXT,                          -- NULL = unconditional; e.g. "with helmet"
    raw_code         TEXT    NOT NULL,              -- verbatim, e.g. "+5H – 2∑ – 3∫ – (-15)"
    extra_hits       INTEGER,                       -- +NH
    parry_rounds     INTEGER,                       -- Nπ  (must parry N rounds)
    no_parry_rounds  INTEGER,                       -- N∏  (no parry for N rounds)
    stun_rounds      INTEGER,                       -- N∑  (stunned N rounds)
    bleed_per_round  INTEGER,                       -- N∫  (bleed N hits/round)
    foe_penalty      INTEGER,                       -- magnitude of (-N), stored positive
    attacker_bonus   INTEGER,                       -- magnitude of (+N), stored positive
    special_text     TEXT,                          -- anything not matched by the above (e.g. "all allies get +10 for 1 round")
    FOREIGN KEY (crit_table_id, roll_min, severity)
        REFERENCES critical_result(crit_table_id, roll_min, severity) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_critical_result_lookup
    ON critical_result(crit_table_id, severity, roll_min, roll_max);

-- =========================================================================
-- Fumble Tables (4.13 Weapon, 4.14 Non-Weapon)
-- =========================================================================
-- Different shape from crit tables: columns are weapon/attack categories
-- (variable count per table — Weapon has 6, Non-Weapon has 4), and cells
-- have only a narrative (no separate parsed effect code).

CREATE TABLE IF NOT EXISTS fumble_table (
    fumble_table_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT    NOT NULL UNIQUE,        -- "Weapon Fumble Table", "Non-Weapon Fumble Table"
    table_number     TEXT    NOT NULL,               -- "4.13", "4.14"
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS fumble_table_column (
    fumble_table_id  INTEGER NOT NULL REFERENCES fumble_table(fumble_table_id) ON DELETE CASCADE,
    col_index        INTEGER NOT NULL,               -- 1-based, left-to-right
    col_name         TEXT    NOT NULL,
    PRIMARY KEY (fumble_table_id, col_index)
);

CREATE TABLE IF NOT EXISTS fumble_result (
    fumble_table_id  INTEGER NOT NULL REFERENCES fumble_table(fumble_table_id) ON DELETE CASCADE,
    roll_min         INTEGER NOT NULL,
    roll_max         INTEGER NOT NULL,
    col_index        INTEGER NOT NULL,
    narrative        TEXT,
    PRIMARY KEY (fumble_table_id, roll_min, col_index),
    CHECK (roll_min <= roll_max),
    FOREIGN KEY (fumble_table_id, col_index)
        REFERENCES fumble_table_column(fumble_table_id, col_index)
);

CREATE INDEX IF NOT EXISTS idx_fumble_result_lookup
    ON fumble_result(fumble_table_id, col_index, roll_min, roll_max);

-- =========================================================================
-- Weapons / attack tables
-- =========================================================================

CREATE TABLE IF NOT EXISTS weapon (
    weapon_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name                   TEXT    NOT NULL UNIQUE,
    attack_table           TEXT    NOT NULL,        -- e.g. "2.1", "3.9"
    is_two_handed          INTEGER NOT NULL DEFAULT 0,
    length_min_ft          REAL,
    length_max_ft          REAL,
    weight_min_lb          REAL,
    weight_max_lb          REAL,
    fumble_min             INTEGER,
    fumble_max             INTEGER,
    fumble_unmodified      INTEGER NOT NULL DEFAULT 0,
    strength_min           INTEGER,
    strength_max           INTEGER,
    strength_flag          TEXT,
    range_modifiers        TEXT,
    notes                  TEXT,
    -- For "implicit-crit-table" attack charts (e.g. Sweeps): every severity-only
    -- cell rolls on this critical table. NULL for charts that name a crit type
    -- in each cell (e.g. Battle Axe cells like "19EK").
    default_crit_table_id  INTEGER REFERENCES critical_strike_table(crit_table_id),
    -- Where to roll when this weapon fumbles. NULL leaves resolution to the GM.
    -- e.g. Battle Axe → ("Weapon Fumble Table", 2 = Two-Handed Arms);
    --      Brawling   → ("Non-Weapon Fumble Table", 3 = Brawling);
    --      Sweeps     → ("Non-Weapon Fumble Table", 2 = MA Sweeps).
    fumble_table_name      TEXT,
    fumble_column_index    INTEGER,
    -- For weapons that use the degree-cap mechanism (Sweeps, Brawling, Martial
    -- Arts Strikes), what to call the degree axis: "Size" (default — Small /
    -- Medium / Large / Huge) or "Rank" (Rank 1..4). Plain TEXT so other
    -- weapons can introduce new vocabularies without a schema change.
    degree_term            TEXT
);

CREATE TABLE IF NOT EXISTS weapon_breakage_number (
    weapon_id        INTEGER NOT NULL REFERENCES weapon(weapon_id) ON DELETE CASCADE,
    breakage_number  INTEGER NOT NULL CHECK (breakage_number BETWEEN 0 AND 9),
    PRIMARY KEY (weapon_id, breakage_number)
);

-- For Sweeps-style charts: results for an attacker of a given size degree
-- "cap out" at a given roll. e.g. degree=1 (Small) max_roll=105 means a Small
-- attacker treats any total > 105 as if it were 105.
-- Degree: 1=Small, 2=Medium, 3=Large, 4=Huge. Empty for charts that don't cap.
CREATE TABLE IF NOT EXISTS attack_table_size_cap (
    weapon_id  INTEGER NOT NULL REFERENCES weapon(weapon_id) ON DELETE CASCADE,
    degree     INTEGER NOT NULL CHECK (degree BETWEEN 1 AND 4),
    max_roll   INTEGER NOT NULL,
    PRIMARY KEY (weapon_id, degree)
);

-- One row per (weapon, attack-roll-band, armor-type) cell on the chart.
-- For range rows (e.g. "56-57"), roll_min < roll_max.
-- A cell may be:
--   miss        -> raw='-',     hits=0,  is_fumble=0
--   hits only   -> raw='12',    hits=12, is_fumble=0
--   hits + crit -> raw='19EK',  hits=19, crit_severity='E', crit_type='K'
--   sev only    -> raw='1A',    hits=1,  crit_severity='A', crit_type=NULL
--                                                   (crit chart resolved via weapon.default_crit_table_id)
--   fumble      -> raw='F',     hits=0,  is_fumble=1
CREATE TABLE IF NOT EXISTS attack_result (
    weapon_id      INTEGER NOT NULL REFERENCES weapon(weapon_id) ON DELETE CASCADE,
    roll_min       INTEGER NOT NULL,
    roll_max       INTEGER NOT NULL,
    armor_type     INTEGER NOT NULL CHECK (armor_type BETWEEN 1 AND 20),
    raw            TEXT    NOT NULL,
    hits           INTEGER NOT NULL DEFAULT 0,
    -- Severity letters:
    --   A-E  standard Arms Law (and Armory weapon) severities
    --   F    Ram/Butt/Bash/Knockdown (table 3.10) special: "E-roll on
    --        Unbalance + C-roll on Krush". F never appears on any standalone
    --        critical_strike_table.
    --   G-J  Spell Law bolt/ball severities — Lightning Bolt's chart
    --        goes up to G/H/I/J at the very high-roll bands.
    crit_severity  TEXT CHECK (crit_severity IN
                       ('A','B','C','D','E','F','G','H','I','J')),
    -- Crit-type single-letter codes resolve to a critical_strike_table:
    --   B → Brawling          G → Grapple           P → Puncture
    --   C → Cold              H → Heat              Q → Martial Arts Strikes
    --   D → Subdual           I → Impact            S → Slash
    --   E → Electricity       K → Krush             T → Tiny
    --                                               U → Unbalancing
    --                                               W → Martial Arts Sweeps
    crit_type      TEXT CHECK (crit_type IN
                       ('B','C','D','E','G','H','I','K','P','Q','S','T','U','W')),
    is_fumble      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (weapon_id, roll_min, armor_type),
    CHECK (roll_min <= roll_max)
);

CREATE INDEX IF NOT EXISTS idx_attack_result_lookup
    ON attack_result(weapon_id, armor_type, roll_min, roll_max);

-- =========================================================================
-- App users (web layer) — ties a Discord identity to characters owned in
-- the builder. The bot can look up app_user by discord_id to find which
-- character a slash-command invoker has claimed.
-- =========================================================================

CREATE TABLE IF NOT EXISTS app_user (
    user_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_id        TEXT    NOT NULL UNIQUE,        -- Discord snowflake
    discord_username  TEXT,                            -- last-seen username (cached)
    discord_avatar    TEXT,                            -- avatar hash (cached)
    created_at        TEXT    NOT NULL,                -- ISO-8601 UTC
    last_login_at     TEXT    NOT NULL                 -- ISO-8601 UTC
);

CREATE INDEX IF NOT EXISTS idx_app_user_discord_id ON app_user(discord_id);

-- =========================================================================
-- Chargen reference data: races.
-- =========================================================================
-- One row per playable race. Loaded from data/chargen/races/<slug>.txt via
-- load.py with INSERT ... ON CONFLICT(slug) DO UPDATE so the race_id stays
-- stable across reference-data reloads (characters reference race_id).
--
-- Stat / RR modifiers are stored as plain INTEGER columns (one per code).
-- Development "progression" sequences come from the source PDF as e.g.
-- "0 • 7 • 5 • 3 • 1" and are stored verbatim as TEXT; the caller parses.

CREATE TABLE IF NOT EXISTS race (
    race_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug             TEXT    NOT NULL UNIQUE,    -- e.g. "high_men", "dwarves"
    name             TEXT    NOT NULL UNIQUE,    -- e.g. "High Men", "Dwarves"
    -- Stat modifiers (RMSS T-1.1). Range observed: -5..+10 in source data.
    stat_ag  INTEGER NOT NULL DEFAULT 0,
    stat_co  INTEGER NOT NULL DEFAULT 0,
    stat_me  INTEGER NOT NULL DEFAULT 0,
    stat_re  INTEGER NOT NULL DEFAULT 0,
    stat_sd  INTEGER NOT NULL DEFAULT 0,
    stat_em  INTEGER NOT NULL DEFAULT 0,
    stat_in  INTEGER NOT NULL DEFAULT 0,
    stat_pr  INTEGER NOT NULL DEFAULT 0,
    stat_qu  INTEGER NOT NULL DEFAULT 0,
    stat_st  INTEGER NOT NULL DEFAULT 0,
    -- Resistance Roll modifiers (RMSS T-1.1).
    rr_ess   INTEGER NOT NULL DEFAULT 0,
    rr_chan  INTEGER NOT NULL DEFAULT 0,
    rr_ment  INTEGER NOT NULL DEFAULT 0,
    rr_pois  INTEGER NOT NULL DEFAULT 0,
    rr_dis   INTEGER NOT NULL DEFAULT 0,
    -- Background option count + per-progression DP costs (verbatim TEXT).
    bg_opts        INTEGER NOT NULL DEFAULT 0,
    body_dev_prog  TEXT    NOT NULL DEFAULT '',
    chan_pp_prog   TEXT    NOT NULL DEFAULT '',
    ess_pp_prog    TEXT    NOT NULL DEFAULT '',
    ment_pp_prog   TEXT    NOT NULL DEFAULT '',
    -- Rich culture data extracted from "Cultures and Races" appendix. Stored
    -- as a JSON object with optional keys for each structured field —
    -- languages, hobby skills, weapons, armor, money, special skills, bg
    -- option sub-fields, narrative paragraphs (build, lifestyle, religion,
    -- demeanor, etc.). Default '{}' means no rich data loaded for this
    -- race yet (current case for Common Men + Mixed Men).
    culture_data   TEXT    NOT NULL DEFAULT '{}'
);

-- =========================================================================
-- Chargen reference data: professions (RMSS Character Law).
-- =========================================================================
-- One row per playable profession (Animist, Bard, ..., Warrior Monk).
-- Loaded from data/chargen/professions/<slug>.txt via load.py with
-- INSERT ... ON CONFLICT(slug) DO UPDATE so profession_id stays stable
-- across reference-data reloads (characters reference profession_id).
--
-- The source is `ERA/rmfrpCharacterLaw.professions.era` — a reversed
-- base64-encoded ZIP of XML files produced by Electronic Roleplaying
-- Assistant. `.scratch/build_professions.py` decodes the .era and
-- generates the per-profession .txt files that load.py ingests.
--
-- Per-profession bonuses and DP costs are stored as child rows with
-- ERA's verbatim group / category strings. ERA uses simpler naming
-- ("Awareness/Perceptions") than RMSS Appendix A-1's divider-page-per-
-- sub-category breakdown ("Awareness • Perceptions" as its own group),
-- so the strings here don't FK to skill_category_group — they live on
-- their own and will be cross-walked when the skill DP allocator
-- needs them.

CREATE TABLE IF NOT EXISTS profession (
    profession_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    slug            TEXT    NOT NULL UNIQUE,    -- e.g. "lay_healer"
    name            TEXT    NOT NULL UNIQUE,    -- e.g. "Lay Healer"
    description     TEXT    NOT NULL DEFAULT '',
    -- Source book tag — 'character_law' for the 20 base professions
    -- from the ERA-derived RMFRP Character Law data, 'sohk' for the
    -- 4 new ones added by School of Hard Knocks.
    source          TEXT    NOT NULL DEFAULT 'character_law',
    -- Relative path to the portrait PNG decoded from the .era SampleImage,
    -- under data/chargen/professions/img/. NULL when no portrait is
    -- available locally (the directory is gitignored as third-party IP).
    portrait_path   TEXT
);

CREATE TABLE IF NOT EXISTS profession_realm (
    profession_id   INTEGER NOT NULL REFERENCES profession(profession_id) ON DELETE CASCADE,
    realm_name      TEXT    NOT NULL,           -- "Essence" / "Channeling" / "Mentalism"
    PRIMARY KEY (profession_id, realm_name)
);

CREATE TABLE IF NOT EXISTS profession_prime_stat (
    profession_id   INTEGER NOT NULL REFERENCES profession(profession_id) ON DELETE CASCADE,
    stat_code       TEXT    NOT NULL,           -- two-letter code: Ag/Co/Me/Re/SD/Em/In/Pr/Qu/St
    PRIMARY KEY (profession_id, stat_code)
);

-- Flat bonus to every skill in a category group (e.g. Fighter: Weapon +20).
CREATE TABLE IF NOT EXISTS profession_group_bonus (
    profession_id   INTEGER NOT NULL REFERENCES profession(profession_id) ON DELETE CASCADE,
    group_name      TEXT    NOT NULL,           -- ERA's groupName, verbatim
    bonus           INTEGER NOT NULL,
    PRIMARY KEY (profession_id, group_name)
);

-- Targeted bonus to one specific category (e.g. Magician: Lore/Magical +5).
CREATE TABLE IF NOT EXISTS profession_category_bonus (
    profession_id   INTEGER NOT NULL REFERENCES profession(profession_id) ON DELETE CASCADE,
    group_name      TEXT    NOT NULL,
    category_name   TEXT    NOT NULL,
    bonus           INTEGER NOT NULL,
    PRIMARY KEY (profession_id, group_name, category_name)
);

-- Per-category DP cost. Stored as the source string ("2/5", "4/4/4-…")
-- so the DP allocator can parse the slash/dash structure as needed.
CREATE TABLE IF NOT EXISTS profession_category_cost (
    profession_id   INTEGER NOT NULL REFERENCES profession(profession_id) ON DELETE CASCADE,
    group_name      TEXT    NOT NULL,
    category_name   TEXT    NOT NULL,
    cost            TEXT    NOT NULL,
    PRIMARY KEY (profession_id, group_name, category_name)
);

-- Per-skill cost multiplier (e.g. Magician: Spell Mastery × 0.5).
CREATE TABLE IF NOT EXISTS profession_skill_cost_modifier (
    profession_id   INTEGER NOT NULL REFERENCES profession(profession_id) ON DELETE CASCADE,
    group_name      TEXT    NOT NULL,
    category_name   TEXT    NOT NULL,
    skill_name      TEXT    NOT NULL,
    classification  TEXT    NOT NULL,           -- "Static Maneuver", "Spell Casting Maneuver", ...
    modifier        REAL    NOT NULL,           -- e.g. 0.5, 2.0
    PRIMARY KEY (profession_id, group_name, category_name, skill_name)
);

-- The profession's "favorite" / signature skills (used by training-package
-- presets and the future DP allocator's "highlight likely picks" view).
CREATE TABLE IF NOT EXISTS profession_favorite_skill (
    profession_id   INTEGER NOT NULL REFERENCES profession(profession_id) ON DELETE CASCADE,
    group_name      TEXT    NOT NULL,
    category_name   TEXT    NOT NULL,
    skill_name      TEXT    NOT NULL,
    classification  TEXT    NOT NULL,
    sort_order      INTEGER NOT NULL,           -- preserves source order for display
    PRIMARY KEY (profession_id, group_name, category_name, skill_name)
);

CREATE INDEX IF NOT EXISTS idx_profession_realm_by_prof
    ON profession_realm(profession_id);
CREATE INDEX IF NOT EXISTS idx_profession_prime_stat_by_prof
    ON profession_prime_stat(profession_id);

-- =========================================================================
-- Chargen reference data: training packages (RMSS Character Law).
-- =========================================================================
-- One row per training package (Adventurer, Bard, ..., Zealot — 36 in
-- the source .era). Loaded from data/chargen/training_packages/<slug>.txt
-- via load.py with INSERT ... ON CONFLICT(slug) DO UPDATE so training_
-- package_id stays stable across reference-data reloads.
--
-- A training package is a bundle of rank assignments + stat gains +
-- random outfitting (Specials) the player can purchase as a single
-- chunk for one of the per-profession DP costs.
--
-- Source: ERA/rmfrpCharacterLaw.trainingPackages.era — same reversed-
-- base64 ZIP format as the professions file.  ERA's group/category
-- naming is preserved verbatim (same caveat as profession_*).
--
-- The ERA data references ~60 professions across RMSS Core + Companion
-- expansions; our schema currently knows only the 20 from Character Law.
-- ProfessionCost rows for unknown professions are stored anyway — the
-- string is the profession's name, no FK — so a future Companion-data
-- import won't require a backfill.

CREATE TABLE IF NOT EXISTS training_package (
    training_package_id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug                TEXT    NOT NULL UNIQUE,    -- e.g. "lay_healer"
    name                TEXT    NOT NULL UNIQUE,    -- e.g. "Lay Healer"
    category            TEXT    NOT NULL DEFAULT '',  -- "RMFRP Core", etc.
    description         TEXT    NOT NULL DEFAULT '',
    default_cost        INTEGER NOT NULL DEFAULT 0,   -- fallback DP cost when
                                                       -- ProfessionCost row absent
    -- Source book tag — 'character_law' for the 36 ERA-derived RMFRP Core
    -- training packages, 'sohk' for the 18 added by School of Hard Knocks.
    source              TEXT    NOT NULL DEFAULT 'character_law'
);

-- Random outfitting rolls. Each row is rolled independently; on a
-- success the item is granted.
CREATE TABLE IF NOT EXISTS training_package_special (
    training_package_id INTEGER NOT NULL REFERENCES training_package(training_package_id) ON DELETE CASCADE,
    sort_order          INTEGER NOT NULL,
    chance              INTEGER NOT NULL,           -- 0..100 in source data
    description         TEXT    NOT NULL,
    PRIMARY KEY (training_package_id, sort_order)
);

-- Stat gain slots. A "guaranteed" gain has stat_code populated and
-- has_choice = 0. A "pick one" gain has stat_code NULL, has_choice = 1,
-- with the choices listed in training_package_stat_gain_choice.
CREATE TABLE IF NOT EXISTS training_package_stat_gain (
    training_package_id INTEGER NOT NULL REFERENCES training_package(training_package_id) ON DELETE CASCADE,
    sort_order          INTEGER NOT NULL,
    stat_code           TEXT,                       -- Ag/Co/Me/Re/SD/Em/In/Pr/Qu/St when guaranteed
    has_choice          INTEGER NOT NULL DEFAULT 0, -- 1 when this slot offers a pick-one set
    PRIMARY KEY (training_package_id, sort_order)
);

CREATE TABLE IF NOT EXISTS training_package_stat_gain_choice (
    training_package_id INTEGER NOT NULL,
    sort_order          INTEGER NOT NULL,
    stat_code           TEXT    NOT NULL,
    PRIMARY KEY (training_package_id, sort_order, stat_code),
    FOREIGN KEY (training_package_id, sort_order)
        REFERENCES training_package_stat_gain(training_package_id, sort_order)
        ON DELETE CASCADE
);

-- One row per RankAssignment slot. A "fixed" slot has group_name +
-- category_name populated and reference_label NULL. A "flexible" slot
-- has reference_label populated (e.g. "Melee Weapon") and the allowed
-- (group, category) pairs live in training_package_ra_category_option.
-- Skill-level filters / spread caps land in the rest of the columns.
CREATE TABLE IF NOT EXISTS training_package_rank_assignment (
    training_package_id INTEGER NOT NULL REFERENCES training_package(training_package_id) ON DELETE CASCADE,
    sort_order          INTEGER NOT NULL,
    reference_label     TEXT,                       -- "Melee Weapon" etc. — NULL when fixed
    group_name          TEXT,                       -- NULL when reference_label set
    category_name       TEXT,                       -- NULL when reference_label set
    cat_ranks           INTEGER NOT NULL DEFAULT 0,
    skill_ranks         INTEGER NOT NULL DEFAULT 0,
    cat_spread_max      INTEGER,                    -- "spread your category picks over at most N options"
    skill_spread_max    INTEGER,                    -- same for skill picks
    ranks_assigned_max  INTEGER,                    -- per-skill cap when the slot grants multiple ranks
    PRIMARY KEY (training_package_id, sort_order)
);

-- Allowed (group, category) options for a flexible-slot RankAssignment.
-- Empty when the slot is fixed (reference_label = NULL).
CREATE TABLE IF NOT EXISTS training_package_ra_category_option (
    training_package_id INTEGER NOT NULL,
    sort_order          INTEGER NOT NULL,            -- matches rank_assignment.sort_order
    option_index        INTEGER NOT NULL,            -- preserves source order
    group_name          TEXT    NOT NULL,
    category_name       TEXT    NOT NULL,
    PRIMARY KEY (training_package_id, sort_order, option_index),
    FOREIGN KEY (training_package_id, sort_order)
        REFERENCES training_package_rank_assignment(training_package_id, sort_order)
        ON DELETE CASCADE
);

-- Skill-level constraints inside a RankAssignment: when present, the
-- ranks must be spent on one of these specific skills. Empty when the
-- slot is free to pick any skill in the chosen category.
CREATE TABLE IF NOT EXISTS training_package_ra_skill_option (
    training_package_id INTEGER NOT NULL,
    sort_order          INTEGER NOT NULL,
    option_index        INTEGER NOT NULL,
    skill_name          TEXT    NOT NULL,
    classification      TEXT    NOT NULL,
    PRIMARY KEY (training_package_id, sort_order, option_index),
    FOREIGN KEY (training_package_id, sort_order)
        REFERENCES training_package_rank_assignment(training_package_id, sort_order)
        ON DELETE CASCADE
);

-- Per-profession DP cost for this TP. ERA's data references ~60 professions
-- (RMSS Core + Companion expansions); we keep the profession_name as a free
-- string rather than FK'ing into our 20-profession `profession` table so
-- unknown professions don't cause load failures.
CREATE TABLE IF NOT EXISTS training_package_profession_cost (
    training_package_id INTEGER NOT NULL REFERENCES training_package(training_package_id) ON DELETE CASCADE,
    profession_name     TEXT    NOT NULL,
    cost                INTEGER NOT NULL,
    PRIMARY KEY (training_package_id, profession_name)
);

CREATE INDEX IF NOT EXISTS idx_tp_special_by_tp
    ON training_package_special(training_package_id);
CREATE INDEX IF NOT EXISTS idx_tp_rank_assignment_by_tp
    ON training_package_rank_assignment(training_package_id);
CREATE INDEX IF NOT EXISTS idx_tp_profession_cost_by_tp
    ON training_package_profession_cost(training_package_id);

-- =========================================================================
-- Adolescence Rank Table T-1.6
-- =========================================================================
-- Starting skill ranks granted to a new character during adolescence,
-- per (culture × skill) pair. Loaded from data/chargen/adolescence_ranks.txt.
-- The skill DP allocator consumes this to seed each character's skill
-- ranks once race + culture is chosen.
--
-- skill column is the verbatim row label from T-1.6 ("Athletic • Brawn
-- skill category", "Climbing skill", "1 Weapon Based on Culture/Race ‡",
-- etc.). value is the cell text — usually an integer but the Background
-- Options row stores values like "6/5".

CREATE TABLE IF NOT EXISTS adolescence_rank (
    skill        TEXT    NOT NULL,
    culture_slug TEXT    NOT NULL,   -- e.g. "hillmen", "dwarves" (matches race.slug)
    value        TEXT    NOT NULL,
    PRIMARY KEY (skill, culture_slug)
);

-- =========================================================================
-- Characters (web layer)
-- =========================================================================
-- A character is owned by exactly one app_user. As of this milestone the
-- table only carries enough to list/view/create a placeholder ("blank")
-- character — the wide set of fields from the RMSS plan (stats, race FK,
-- profession FK, skill ranks, etc.) will be added in subsequent migrations
-- as the chargen wizard fills out.

CREATE TABLE IF NOT EXISTS character (
    character_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id  INTEGER NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
    name           TEXT    NOT NULL,
    level          INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT    NOT NULL,           -- ISO-8601 UTC
    updated_at     TEXT    NOT NULL,           -- ISO-8601 UTC
    -- Chargen progress columns. Nullable so a blank character can sit at
    -- step 1 (stats) without forcing a downstream choice. The race FK
    -- uses SET NULL so a reference-data reload that wipes race rows
    -- doesn't cascade-delete characters — though in practice the race
    -- loader uses ON CONFLICT(slug) DO UPDATE so race_id stays stable.
    race_id        INTEGER REFERENCES race(race_id) ON DELETE SET NULL,
    -- Profession picked from the RMSS Character Law list. Same reload-
    -- proof story as race_id: SET NULL on profession delete, but the
    -- loader keeps profession_id stable across reloads via UPSERT.
    profession_id  INTEGER REFERENCES profession(profession_id) ON DELETE SET NULL,
    -- Culture sub-selection for umbrella races (Common Men, Mixed Men).
    -- Stored as a slug pointing into race.slug — the 7 Men sub-cultures
    -- (Hillmen / Mariners / Nomads / Ruralmen / Urbanmen / Woodmen /
    -- High Men) live in the race table as full rows, so culture_slug
    -- reuses them rather than duplicating the data. Only meaningful when
    -- race_id resolves to an umbrella race; the PUT endpoint clears
    -- culture_slug whenever race changes to a non-umbrella value.
    culture_slug   TEXT
);

CREATE INDEX IF NOT EXISTS idx_character_owner ON character(owner_user_id);

-- One row per character per stat code. The 10 stat codes come from
-- core.chargen.stats.STAT_CODES (Ag/Co/Me/Re/SD/Em/In/Pr/Qu/St); the FK
-- to character is what enforces ownership, and ON DELETE CASCADE keeps
-- the per-stat rows in sync with the parent.
--
-- `temp` and `potential` are the raw values the player rolled / bought
-- (1..102 in practice). Derived bonuses (basic stat bonus, RR formulas)
-- are computed on the fly by core.chargen.stats and NOT stored here —
-- the table T-2.1 is the single source of truth.
CREATE TABLE IF NOT EXISTS character_stat (
    character_id  INTEGER NOT NULL REFERENCES character(character_id) ON DELETE CASCADE,
    stat_code     TEXT    NOT NULL CHECK (stat_code IN
                    ('Ag','Co','Me','Re','SD','Em','In','Pr','Qu','St')),
    temp          INTEGER NOT NULL DEFAULT 50  CHECK (temp      BETWEEN 1 AND 102),
    potential     INTEGER NOT NULL DEFAULT 50  CHECK (potential BETWEEN 1 AND 102),
    PRIMARY KEY (character_id, stat_code)
);

-- =========================================================================
-- Adolescence specifier choices + character_skill ranks
-- =========================================================================
-- Some T-1.6 rows require the player to pick a specific instance before
-- the rank can be applied. Examples:
--   * "Riding skill (usually horses)" — pick a mount (free-text).
--   * "1 Weapon Based on Culture/Race ‡" rows — pick a weapon from the
--     race's outfitting list, classified by RMSS weapon category.
--
-- We store the player's pending picks here, keyed by the T-1.6 row label
-- the loader uses (the same label that comes back on the
-- /adolescence-ranks API). On "Apply Adolescent Ranks" the picks are
-- folded into character_skill rows with a resolved skill name like
-- "Riding (horses)" or "1-H Edged: Short Sword".

CREATE TABLE IF NOT EXISTS character_adolescence_choice (
    character_id INTEGER NOT NULL REFERENCES character(character_id) ON DELETE CASCADE,
    t16_row      TEXT    NOT NULL,           -- adolescence_rank.skill verbatim
    choice       TEXT    NOT NULL,           -- user's text or selected weapon name
    PRIMARY KEY (character_id, t16_row)
);

-- One row per (character, skill). `source` tags where the rank came
-- from so future passes (skill DP allocator, hobby ranks) can layer
-- additional ranks on top without overwriting the adolescence-derived
-- ones. Reapplying adolescence is idempotent within source='adolescence'.

CREATE TABLE IF NOT EXISTS character_skill (
    character_id INTEGER NOT NULL REFERENCES character(character_id) ON DELETE CASCADE,
    skill        TEXT    NOT NULL,           -- resolved final name (e.g. "Riding (horses)")
    rank         INTEGER NOT NULL DEFAULT 0,
    source       TEXT    NOT NULL DEFAULT 'adolescence',  -- 'adolescence' | 'dp' | 'hobby' | ...
    PRIMARY KEY (character_id, skill)
);
CREATE INDEX IF NOT EXISTS idx_character_skill_by_source
    ON character_skill(character_id, source);

-- One row per "background option" the player has spent on a character
-- (RMSS Character Law p.20, Table T-1.5). The total number of options
-- a character may take is race-dependent (race.bg_opts). Each row
-- records the option_key (which T-1.5 menu entry) + optional detail
-- text the player typed in (e.g. "+5 ranks in Sindarin" or
-- "Heirloom shortsword").
CREATE TABLE IF NOT EXISTS character_background_option (
    character_id INTEGER NOT NULL REFERENCES character(character_id) ON DELETE CASCADE,
    sort_order   INTEGER NOT NULL,
    option_key   TEXT    NOT NULL,           -- e.g. "extra_languages", "extra_money"
    detail       TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (character_id, sort_order)
);
CREATE INDEX IF NOT EXISTS idx_character_background_option_by_char
    ON character_background_option(character_id);

CREATE VIEW IF NOT EXISTS v_attack_result_by_roll AS
WITH RECURSIVE expand(weapon_id, roll, roll_min, armor_type) AS (
    SELECT weapon_id, roll_min, roll_min, armor_type FROM attack_result
    UNION ALL
    SELECT weapon_id, roll + 1, roll_min, armor_type
      FROM expand
      JOIN attack_result USING (weapon_id, roll_min, armor_type)
     WHERE roll < roll_max
)
SELECT e.weapon_id, e.roll, e.armor_type,
       ar.raw, ar.hits, ar.crit_severity, ar.crit_type, ar.is_fumble
  FROM expand e
  JOIN attack_result ar
    ON ar.weapon_id = e.weapon_id
   AND ar.roll_min  = e.roll_min
   AND ar.armor_type = e.armor_type;


-- =========================================================================
-- Spell lists (Phase 1: index + summary chart only; descriptions come later)
-- =========================================================================
-- Three Rolemaster spell realms (Channeling / Essence / Mentalism), each
-- with its own set of caster classes and shared open/closed list pools.
-- Schema is realm-agnostic so adding Essence/Mentalism later is just data.

CREATE TABLE IF NOT EXISTS spell_realm (
    realm_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT    NOT NULL UNIQUE       -- "Channeling", "Essence", "Mentalism"
);

CREATE TABLE IF NOT EXISTS spell_class (
    class_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT    NOT NULL UNIQUE,      -- "Animist", "Cleric", "Paladin", ...
    realm_id  INTEGER NOT NULL REFERENCES spell_realm(realm_id) ON DELETE CASCADE
);

-- One row per spell list (e.g., "Barrier Law", "Holy Healing").
-- category is one of: 'Open', 'Closed', 'Base'.
-- list_number is the source-PDF section number (e.g., "2.1.1", "2.4.3").
CREATE TABLE IF NOT EXISTS spell_list (
    list_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    realm_id     INTEGER NOT NULL REFERENCES spell_realm(realm_id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,
    list_number  TEXT,                       -- "2.1.1" etc.
    category     TEXT    NOT NULL CHECK (category IN ('Open', 'Closed', 'Base')),
    UNIQUE (realm_id, name)
);

-- Many-to-many: which classes have access to which lists.
-- For Open / Closed lists, every channeler class is associated with them.
-- For Base lists, exactly one class owns each list.
CREATE TABLE IF NOT EXISTS class_spell_list (
    class_id  INTEGER NOT NULL REFERENCES spell_class(class_id)   ON DELETE CASCADE,
    list_id   INTEGER NOT NULL REFERENCES spell_list(list_id)     ON DELETE CASCADE,
    PRIMARY KEY (class_id, list_id)
);

-- One row per spell on a list. `level` is the slot on the list (1..50 in RM,
-- with gaps; extension levels 25/30/50 are common). Descriptions come in
-- a later phase; this Phase-1 table just carries the summary-chart fields.
CREATE TABLE IF NOT EXISTS spell (
    spell_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id      INTEGER NOT NULL REFERENCES spell_list(list_id) ON DELETE CASCADE,
    level        INTEGER NOT NULL,
    name         TEXT    NOT NULL,
    area_effect  TEXT,                       -- e.g. "20' x 20' x 1\""
    duration     TEXT,                       -- "C" (concentration), "P" (permanent), "1 min/lvl"
    range_str    TEXT,                       -- "50'", "touch", "self"
    spell_type   TEXT,                       -- E/F/U/P single-letter type code (with optional 's' modifier)
    description  TEXT,                       -- left NULL for Phase 1; filled by Phase 2
    starred      INTEGER NOT NULL DEFAULT 0, -- 1 if the chart printed an asterisk after the name
    -- Edit-audit columns populated by the web explorer's PUT endpoint.
    -- Reference-data reload (load.py --reload-ref) drops these along with
    -- the rest of the spell row, but the canonical data is in the .txt
    -- files anyway — the write-back keeps the two in sync.
    updated_at         TEXT,
    updated_by_user_id INTEGER REFERENCES app_user(user_id) ON DELETE SET NULL,
    UNIQUE (list_id, level)
);

CREATE INDEX IF NOT EXISTS idx_spell_lookup_name
    ON spell(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_spell_by_list
    ON spell(list_id, level);

-- =========================================================================
-- Skills (RMSS Appendix A-1)
-- =========================================================================
-- One skill_category_group row per A-1.x divider page (34 in total). A
-- group can hold 1+ skill_category rows (Armor has 3 sub-categories, Lore
-- has 4, most groups have 1) and 0+ skill rows for the per-skill
-- descriptions on the content page.
--
-- skill_table + skill_table_row capture the embedded maneuver / lookup
-- tables (Static Maneuver Table T-4.8.x etc.) that sit on the divider
-- pages alongside category metadata.
--
-- All four tables are reference data — wiped + reloaded on --reload-ref.

CREATE TABLE IF NOT EXISTS skill_category_group (
    group_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT    NOT NULL UNIQUE,        -- e.g. "awareness_perceptions"
    section     TEXT    NOT NULL,               -- e.g. "A-1.7"
    name        TEXT    NOT NULL,               -- e.g. "Awareness • Perceptions"
    page_div    INTEGER NOT NULL,
    page_content INTEGER NOT NULL,
    -- Audit fields touched by the web edit endpoint; NULL until the first
    -- save. updated_by_user_id may be NULL after the user's account is
    -- deleted (ON DELETE SET NULL).
    updated_at         TEXT,
    updated_by_user_id INTEGER REFERENCES app_user(user_id) ON DELETE SET NULL,
    -- Group-level prose from "School of Hard Knocks" Section 5
    -- (general usage rules that apply across a whole skill-category
    -- family — e.g. EP costs + pace multipliers for Athletic skills).
    -- Empty when SOHK has no Section 5 entry for this family.
    sohk_notes         TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS skill_category (
    category_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id             INTEGER NOT NULL REFERENCES skill_category_group(group_id) ON DELETE CASCADE,
    name                 TEXT    NOT NULL,
    skills_list          TEXT,                  -- raw comma-separated as in source
    restricted           TEXT,
    stat_bonuses         TEXT,
    rank_progression     TEXT,
    category_progression TEXT,
    parent_group         TEXT,                  -- the "Group:" field — e.g. "Armor"
    classification       TEXT,                  -- "Moving Maneuver" / "Static Maneuver" / ...
    description          TEXT,
    -- Optional per-category prose from "School of Hard Knocks" Section 5
    -- (extra usage notes, modifiers, common situations). Empty when
    -- SOHK has no entry for this category. Stored as a single TEXT
    -- block; the SPA renders it under a "SOHK notes" disclosure.
    sohk_notes           TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_skill_category_by_group
    ON skill_category(group_id);

CREATE TABLE IF NOT EXISTS skill (
    skill_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id     INTEGER NOT NULL REFERENCES skill_category_group(group_id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,
    stat         TEXT,                          -- "In" / "Em" / multi like "Em/Pr"
    description  TEXT,
    -- Optional per-skill supplemental data from "School of Hard Knocks"
    -- (book 5808). Stored as a JSON object with optional keys:
    --   optional_stats:        e.g. "Ag/Qu/Ag"
    --   ep_cost:               e.g. "1 every 6 rounds"
    --   distance_multiplier:   e.g. "1"
    --   notes:                 GM-facing maneuver-resolution paragraphs
    --   specialties:           list[str] of specialization options
    --   example_difficulties:  dict[str, str] keyed by tier
    --                          ("Routine", "Easy", "Light", "Medium",
    --                           "Hard", "Very Hard", "Extremely Hard",
    --                           "Sheer Folly", "Absurd")
    -- Default '{}' means SOHK doesn't elaborate this skill.
    sohk_data    TEXT    NOT NULL DEFAULT '{}',
    UNIQUE (group_id, name)
);
CREATE INDEX IF NOT EXISTS idx_skill_lookup_name
    ON skill(name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS skill_table (
    table_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id     INTEGER NOT NULL REFERENCES skill_category_group(group_id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,              -- "Static Maneuver Table T-4.8.7"
    columns      TEXT    NOT NULL,              -- pipe-separated column labels
    -- "General and GM-Assigned Modifers" list that the source PDF prints
    -- below the table proper. Stored as newline-separated "Label: value"
    -- entries; empty when the source table has no such section.
    general_mods TEXT    NOT NULL DEFAULT '',
    UNIQUE (group_id, name)
);

CREATE TABLE IF NOT EXISTS skill_table_row (
    row_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id     INTEGER NOT NULL REFERENCES skill_table(table_id) ON DELETE CASCADE,
    sort_order   INTEGER NOT NULL,              -- preserves source order
    roll         TEXT,
    result       TEXT,
    percent      TEXT,
    time         TEXT,
    mod          TEXT,
    description  TEXT
);
CREATE INDEX IF NOT EXISTS idx_skill_table_row_by_table
    ON skill_table_row(table_id, sort_order);
