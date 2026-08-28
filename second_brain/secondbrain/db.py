"""SQLite schema and connection handling (spec PHASE 1).

The brain is a single file. Every table is small on purpose: we store
compressed meaning (decisions, state, facts, references), never transcripts.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ACTIVE',
    summary     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS role_profiles (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    goal              TEXT NOT NULL DEFAULT '',
    priority          TEXT NOT NULL DEFAULT '',
    visible_context   TEXT NOT NULL DEFAULT '[]',
    hidden_context    TEXT NOT NULL DEFAULT '[]',
    evaluation_axes   TEXT NOT NULL DEFAULT '[]',
    prohibitions      TEXT NOT NULL DEFAULT '[]',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT '',
    context_profile TEXT NOT NULL,
    model           TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY (context_profile) REFERENCES role_profiles(id)
);

CREATE TABLE IF NOT EXISTS facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL,
    key         TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL,
    tags        TEXT NOT NULL DEFAULT '[]',
    source      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS decisions (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'PROPOSED',
    phase       TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

-- States are append-only: the newest row for a project is the current state,
-- older rows are the phase history.
CREATE TABLE IF NOT EXISTS states (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    TEXT NOT NULL,
    phase         TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'IN_PROGRESS',
    owner         TEXT NOT NULL DEFAULT '',
    note          TEXT NOT NULL DEFAULT '',
    deliverables  TEXT NOT NULL DEFAULT '[]',
    created_at    TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

-- Handoff bodies are never copied into the brain; we index the file only.
CREATE TABLE IF NOT EXISTS handoffs (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL,
    phase       TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL DEFAULT '',
    file_path   TEXT NOT NULL,
    owner       TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'ACTIVE',
    file_exists INTEGER NOT NULL DEFAULT 0,
    checked_at  TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS relations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL,
    src         TEXT NOT NULL,
    rel         TEXT NOT NULL,
    dst         TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (project_id, src, rel, dst),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

-- Feeds RECENT CHANGES in the UI and gives agents a cheap "what moved" read.
CREATE TABLE IF NOT EXISTS changes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL DEFAULT '',
    entity      TEXT NOT NULL,
    entity_id   TEXT NOT NULL DEFAULT '',
    action      TEXT NOT NULL,
    summary     TEXT NOT NULL DEFAULT '',
    actor       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_facts_project ON facts(project_id);
CREATE INDEX IF NOT EXISTS idx_decisions_project ON decisions(project_id, status);
CREATE INDEX IF NOT EXISTS idx_states_project ON states(project_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_handoffs_project ON handoffs(project_id, status);
CREATE INDEX IF NOT EXISTS idx_relations_project ON relations(project_id, src);
CREATE INDEX IF NOT EXISTS idx_relations_dst ON relations(project_id, dst);
CREATE INDEX IF NOT EXISTS idx_changes_created ON changes(created_at DESC);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the brain database."""
    path = Path(db_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create the schema. Safe to call on every start."""
    with conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO meta(key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )
