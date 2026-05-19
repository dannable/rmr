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
    -- Severity F is special-case: only used by Ram/Butt/Bash/Knockdown
    -- (table 3.10), which calls out "F = E-roll on Unbalance + C-roll on
    -- Krush" in a per-table note. F never appears on any standalone
    -- critical_strike_table.
    crit_severity  TEXT CHECK (crit_severity IN ('A','B','C','D','E','F')),
    crit_type      TEXT CHECK (crit_type     IN ('G','K','P','S','T','U')),
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
    updated_at     TEXT    NOT NULL            -- ISO-8601 UTC
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
