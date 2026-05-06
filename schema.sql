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
    crit_severity  TEXT CHECK (crit_severity IN ('A','B','C','D','E')),
    crit_type      TEXT CHECK (crit_type     IN ('G','K','P','S','T','U')),
    is_fumble      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (weapon_id, roll_min, armor_type),
    CHECK (roll_min <= roll_max)
);

CREATE INDEX IF NOT EXISTS idx_attack_result_lookup
    ON attack_result(weapon_id, armor_type, roll_min, roll_max);

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
