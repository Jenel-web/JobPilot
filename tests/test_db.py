"""Tests for engine/db.py. They use an in-memory database, never data/jobpilot.db."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from engine.db import TABLES, connect, init_db, table_names


@pytest.fixture()
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    init_db(connection)
    yield connection
    connection.close()


def test_init_creates_all_six_tables(conn: sqlite3.Connection) -> None:
    assert table_names(conn) == sorted(TABLES)


def test_init_is_safe_to_run_twice(conn: sqlite3.Connection) -> None:
    init_db(conn)
    assert table_names(conn) == sorted(TABLES)


def test_answer_defaults_to_protected(conn: sqlite3.Connection) -> None:
    """A forgotten kind must be the safest one (the AI never touches it)."""
    conn.execute("INSERT INTO answers (question, answer) VALUES ('Q?', 'A')")
    row = conn.execute("SELECT kind, location_scope FROM answers").fetchone()
    assert row["kind"] == "protected"
    assert row["location_scope"] == "any"


@pytest.mark.parametrize(
    ("sql", "params"),
    [
        ("INSERT INTO answers (question, answer, kind) VALUES (?, ?, ?)", ("q", "a", "legal")),
        ("INSERT INTO answers (question, answer, location_scope) VALUES (?, ?, ?)", ("q", "a", "mars")),
        ("INSERT INTO resumes (id, file_path) VALUES (?, ?)", ("C", "x.pdf")),
        ("INSERT INTO fills (url, status) VALUES (?, ?)", ("http://x", "sent")),
    ],
)
def test_bad_values_are_rejected(conn: sqlite3.Connection, sql: str, params: tuple[str, ...]) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, params)


def test_same_question_can_have_one_answer_per_scope(conn: sqlite3.Connection) -> None:
    insert = "INSERT INTO answers (question, answer, location_scope, city) VALUES (?, ?, ?, ?)"
    conn.execute(insert, ("Expected salary?", "PHP 20,000", "city", "Metro Manila"))
    conn.execute(insert, ("Expected salary?", "USD 600", "remote", ""))
    with pytest.raises(sqlite3.IntegrityError):  # exact duplicate
        conn.execute(insert, ("Expected salary?", "other", "remote", ""))


def test_profile_holds_only_one_row(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO profile (id, full_name) VALUES (1, 'A')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO profile (id, full_name) VALUES (2, 'B')")


def test_foreign_keys_are_enforced(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO fills (url, resume_id) VALUES ('http://x', 'A')")  # no resume A yet
