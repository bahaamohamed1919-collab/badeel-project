-- Badeel database schema.
-- Written in plain SQL that works on SQLite (used now) and needs only small
-- changes for PostgreSQL (AUTOINCREMENT -> SERIAL / IDENTITY).

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    email           TEXT    NOT NULL UNIQUE,
    password_hash   TEXT    NOT NULL,                 -- never the password itself
    role            TEXT    NOT NULL DEFAULT 'patient'
                    CHECK (role IN ('patient', 'pharmacist', 'admin')),
    status          TEXT    NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'pending', 'disabled')),
    allergies_enc   TEXT,                             -- encrypted (Fernet/AES)
    consent_at      TEXT,                             -- explicit consent for health data
    failed_logins   INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT,
    created_at      TEXT    NOT NULL
);

-- One row per active ingredient (scientific name), e.g. "paracetamol".
CREATE TABLE IF NOT EXISTS ingredients (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL UNIQUE
);

-- One row per product on the shelf, e.g. "Panadol 500 mg tablets".
CREATE TABLE IF NOT EXISTS drugs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_name          TEXT NOT NULL,
    trade_name_ar       TEXT,
    ingredients_display TEXT NOT NULL,   -- "Amoxicillin + Clavulanic acid"
    strength_display    TEXT,            -- "875 mg + 125 mg"
    form                TEXT NOT NULL,   -- normalised: tablet, syrup, ...
    form_raw            TEXT,            -- as typed in the source data
    company             TEXT,
    price               REAL CHECK (price IS NULL OR price >= 0),
    pack_count          INTEGER,         -- units in the pack (20 tablets), if known
    drug_class          TEXT,
    country             TEXT,
    availability        TEXT NOT NULL DEFAULT 'unknown'
                        CHECK (availability IN ('available', 'shortage', 'unknown')),
    -- The two keys below are what the recommendation engine compares.
    ingredient_key      TEXT NOT NULL,   -- "amoxicillin|clavulanic acid"
    composition_key     TEXT NOT NULL,   -- "amoxicillin:875mg|clavulanic acid:125mg"
    strength_known      INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_drugs_composition ON drugs (composition_key, form);
CREATE INDEX IF NOT EXISTS idx_drugs_ingredient  ON drugs (ingredient_key);
CREATE INDEX IF NOT EXISTS idx_drugs_class       ON drugs (drug_class);

-- Many-to-many: a drug can contain several ingredients, each with a strength.
CREATE TABLE IF NOT EXISTS drug_ingredients (
    drug_id         INTEGER NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
    ingredient_id   INTEGER NOT NULL REFERENCES ingredients(id),
    strength_value  REAL,
    strength_unit   TEXT,
    strength_text   TEXT,
    PRIMARY KEY (drug_id, ingredient_id)
);
CREATE INDEX IF NOT EXISTS idx_di_ingredient ON drug_ingredients (ingredient_id);

CREATE TABLE IF NOT EXISTS favorites (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    drug_id     INTEGER NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (user_id, drug_id)
);

CREATE TABLE IF NOT EXISTS search_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    query       TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_user ON search_history (user_id, created_at);

-- Failed logins, honeypot hits, blocked requests ...
CREATE TABLE IF NOT EXISTS security_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL,
    ip          TEXT,
    path        TEXT,
    user_agent  TEXT,
    detail      TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_time ON security_events (created_at);
CREATE INDEX IF NOT EXISTS idx_events_ip   ON security_events (ip, type, created_at);

-- Who changed what (admin and pharmacist actions).
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action      TEXT NOT NULL,
    detail      TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key     TEXT PRIMARY KEY,
    value   TEXT
);
