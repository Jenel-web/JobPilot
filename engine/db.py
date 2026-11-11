"""SQLite database: connection and schema (the 6 tables of v0 Phase 1).

SQLite is just a file (``data/jobpilot.db``) that Python can read and write
with the built-in ``sqlite3`` module. There is no server and no password.

Tables
------
``profile``            one row: your fixed details (code fills forms from here)
``resumes``            two rows (A and B): file path and the text extracted from the PDF
``answers``            your answer bank: question, answer, location scope, kind
``answer_aliases``     other wordings of a saved question (helps RAG find it)
``unknown_questions``  questions the bot could not answer; you answer each once
``fills``              history: one row per "Fill this page"
``action_log``         every step the bot took

Later phases add ``chunks`` (RAG, Phase 3) and, in v1/v2, ``jobs``,
``applications``, ``contacts`` and ``emails``.

Lists (skills, projects...) are stored as JSON text in one column.
The database file can always be deleted and rebuilt from
``data/profile.json`` and ``data/answers.json``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from engine.settings import ROOT

DB_PATH = ROOT / "data" / "jobpilot.db"

LOCATION_SCOPES = ("any", "city", "remote", "abroad")

# What each answer kind means (see SPEC.md):
#   fixed      use as written (the AI may add "yes, plus reasons" in a free-text box)
#   open       the AI may rewrite it to fit the job, from your own facts only
#   protected  the AI never sees or changes it; always highlighted for your review
ANSWER_KINDS = ("fixed", "open", "protected")

FILL_STATUSES = ("filled", "submitted", "abandoned")
QUESTION_STATUSES = ("open", "answered")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS profile (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),   -- always exactly one row
    full_name           TEXT NOT NULL,                        -- built from the parts below
    first_name          TEXT NOT NULL DEFAULT '',
    middle_name         TEXT NOT NULL DEFAULT '',
    last_name           TEXT NOT NULL DEFAULT '',
    email               TEXT,
    phone               TEXT,
    address             TEXT,
    school              TEXT,
    degree              TEXT,
    year_level          TEXT,
    grad_year           INTEGER,
    gpa                 TEXT,
    location            TEXT,
    open_to_remote      INTEGER NOT NULL DEFAULT 0,           -- 0 / 1
    github              TEXT,
    linkedin            TEXT,
    portfolio           TEXT,
    job_types           TEXT NOT NULL DEFAULT '[]',           -- JSON list
    target_roles        TEXT NOT NULL DEFAULT '[]',           -- JSON list
    preferred_locations TEXT NOT NULL DEFAULT '[]',           -- JSON list
    skills              TEXT NOT NULL DEFAULT '[]',           -- JSON list
    summary             TEXT,
    projects            TEXT NOT NULL DEFAULT '[]',           -- JSON list of {{name, tech, blurb}}
    upload_name         TEXT                                  -- file name the employer sees
);

CREATE TABLE IF NOT EXISTS resumes (
    id             TEXT PRIMARY KEY CHECK (id IN ('A', 'B')),
    label          TEXT,                                      -- display only, never used to decide
    file_path      TEXT NOT NULL,
    extracted_text TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS answers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    question       TEXT NOT NULL,
    answer         TEXT NOT NULL,
    location_scope TEXT NOT NULL DEFAULT 'any'
                   CHECK (location_scope IN {LOCATION_SCOPES!r}),
    city           TEXT NOT NULL DEFAULT '',
    kind           TEXT NOT NULL DEFAULT 'protected'          -- safest default
                   CHECK (kind IN {ANSWER_KINDS!r}),
    times_used     INTEGER NOT NULL DEFAULT 0,
    last_used      TEXT,
    UNIQUE (question, location_scope, city)
);

-- Other ways a form may word a saved question (``also_asked_as`` in answers.json).
-- Shared by every location variant of that question. Rebuilt from the file on each load.
CREATE TABLE IF NOT EXISTS answer_aliases (
    question TEXT NOT NULL,
    alias    TEXT NOT NULL,
    UNIQUE (question, alias)
);

CREATE TABLE IF NOT EXISTS unknown_questions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    question_text TEXT NOT NULL,
    page_url      TEXT,
    field_type    TEXT,
    options       TEXT NOT NULL DEFAULT '[]',                 -- JSON list
    first_seen    TEXT NOT NULL DEFAULT (datetime('now')),
    status        TEXT NOT NULL DEFAULT 'open'
                  CHECK (status IN {QUESTION_STATUSES!r}),
    answer_id     INTEGER REFERENCES answers(id)              -- set once you answer it
);

CREATE TABLE IF NOT EXISTS fills (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT NOT NULL,
    job_title       TEXT,
    company         TEXT,
    resume_id       TEXT REFERENCES resumes(id),
    filled_count    INTEGER NOT NULL DEFAULT 0,
    flagged_count   INTEGER NOT NULL DEFAULT 0,
    filled_fields   TEXT NOT NULL DEFAULT '[]',               -- JSON list
    flagged_fields  TEXT NOT NULL DEFAULT '[]',               -- JSON list
    screenshot_path TEXT,
    status          TEXT NOT NULL DEFAULT 'filled'
                    CHECK (status IN {FILL_STATUSES!r}),
    filled_at       TEXT NOT NULL DEFAULT (datetime('now')),
    submitted_at    TEXT
);

CREATE TABLE IF NOT EXISTS action_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    time            TEXT NOT NULL DEFAULT (datetime('now')),
    kind            TEXT NOT NULL,                            -- navigate, fill, upload, error...
    target          TEXT,
    details         TEXT,
    screenshot_path TEXT,
    fill_id         INTEGER REFERENCES fills(id)
);

CREATE INDEX IF NOT EXISTS idx_answers_question ON answers(question);
CREATE INDEX IF NOT EXISTS idx_unknown_status ON unknown_questions(status);
CREATE INDEX IF NOT EXISTS idx_fills_status ON fills(status);
CREATE INDEX IF NOT EXISTS idx_log_fill ON action_log(fill_id);
"""

TABLES = ("profile", "resumes", "answers", "answer_aliases", "unknown_questions", "fills", "action_log")


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Open the database (creating the file and its folder if needed).

    Rows come back as ``sqlite3.Row`` so you can read ``row["answer"]`` by
    column name. Foreign keys are switched on (SQLite has them off by default).
    Pass ``":memory:"`` for a throwaway database (tests do this).
    """
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Columns added after a table was first created. ``CREATE TABLE IF NOT EXISTS`` never
# changes an existing table, so ``init_db`` adds these to older databases itself.
ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "profile": [
        ("first_name", "TEXT NOT NULL DEFAULT ''"),
        ("middle_name", "TEXT NOT NULL DEFAULT ''"),
        ("last_name", "TEXT NOT NULL DEFAULT ''"),
    ],
}


def init_db(conn: sqlite3.Connection) -> None:
    """Create every table that does not exist yet, and add any newer columns. Safe to run many times."""
    conn.executescript(SCHEMA)
    for table, columns in ADDED_COLUMNS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, definition in columns:
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.commit()


def table_names(conn: sqlite3.Connection) -> list[str]:
    """Names of the tables in the database (handy for tests and debugging)."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return sorted(row["name"] for row in rows)
