-- Schema de Nublock (PRD sección 11). Fechas en ISO 8601 UTC como TEXT.
-- IF NOT EXISTS: se puede ejecutar en cada arranque sin borrar datos.

CREATE TABLE IF NOT EXISTS activity_sessions (
    id            INTEGER PRIMARY KEY,
    started_at    TEXT    NOT NULL,
    ended_at      TEXT,                       -- NULL hasta el primer heartbeat o el cierre
    process_name  TEXT    NOT NULL,
    app_name      TEXT,
    window_title  TEXT,                       -- NULL si store_window_titles = false
    url_domain    TEXT,                       -- M7 (browser extension)
    productivity  TEXT    NOT NULL CHECK (productivity IN ('productive','neutral','distracting')),
    subcategory   TEXT,
    is_idle       INTEGER NOT NULL DEFAULT 0  -- SQLite no tiene BOOLEAN: 0/1
);

CREATE TABLE IF NOT EXISTS attention_events (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    state       TEXT NOT NULL CHECK (state IN
                ('FOCUSED','LOOKING_AWAY','LOOKING_DOWN','PHONE','ABSENT','PAUSED','CAMERA_UNAVAILABLE')),
    confidence  REAL
);

CREATE TABLE IF NOT EXISTS interventions (
    id               INTEGER PRIMARY KEY,
    at               TEXT NOT NULL,
    trigger          TEXT NOT NULL,           -- ej. 'rule:social-daily-limit'
    level            INTEGER NOT NULL,        -- 1, 2, 3 (escalation)
    rule_id          TEXT,
    user_feedback    TEXT,
    refocus_seconds  REAL
);

CREATE TABLE IF NOT EXISTS focus_sessions (
    id               INTEGER PRIMARY KEY,
    started_at       TEXT NOT NULL,
    ended_at         TEXT,
    planned_minutes  INTEGER NOT NULL,
    mode             TEXT NOT NULL CHECK (mode IN ('soft','strict')),
    completed        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS classification_overrides (
    id            INTEGER PRIMARY KEY,
    matcher_type  TEXT NOT NULL CHECK (matcher_type IN ('process','title_regex','domain')),
    pattern       TEXT NOT NULL,
    productivity  TEXT NOT NULL,
    subcategory   TEXT,
    created_at    TEXT NOT NULL
);

-- M6: cada vez que se pausa/desactiva algo (estadística de "veces que desactivaste").
CREATE TABLE IF NOT EXISTS disable_events (
    id      INTEGER PRIMARY KEY,
    at      TEXT    NOT NULL,
    action  TEXT    NOT NULL,           -- 'pause_all' | 'stop_focus' | 'disable_rule'
    target  TEXT,                       -- rule_id o minutos
    strict  INTEGER NOT NULL DEFAULT 0  -- 1 si requirió la fricción del modo strict
);

CREATE INDEX IF NOT EXISTS idx_activity_started ON activity_sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_attention_started ON attention_events(started_at);
