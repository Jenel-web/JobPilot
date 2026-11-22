"""Tests for the filled pages history helpers in engine/forms/history.py."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from engine.db import connect, init_db
from engine.forms.history import FillNotFound, FillStatusError, list_fills, mark_fill


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    init_db(connection)
    for url in ("https://a.test/1", "https://a.test/2"):
        connection.execute("INSERT INTO fills (url) VALUES (?)", (url,))
    connection.commit()
    yield connection
    connection.close()


def test_list_is_newest_first_and_filters(conn: sqlite3.Connection) -> None:
    assert [r["url"] for r in list_fills(conn)] == ["https://a.test/2", "https://a.test/1"]
    mark_fill(conn, 1, "abandoned")
    assert [r["id"] for r in list_fills(conn, "filled")] == [2]


def test_submitted_sets_the_time_abandoned_does_not(conn: sqlite3.Connection) -> None:
    mark_fill(conn, 1, "submitted")
    mark_fill(conn, 2, "abandoned")
    rows = {r["id"]: r for r in list_fills(conn)}
    assert rows[1]["status"] == "submitted" and rows[1]["submitted_at"]
    assert rows[2]["status"] == "abandoned" and rows[2]["submitted_at"] is None


def test_decided_row_cannot_change_again(conn: sqlite3.Connection) -> None:
    mark_fill(conn, 1, "submitted")
    with pytest.raises(FillStatusError, match="already submitted"):
        mark_fill(conn, 1, "abandoned")


def test_bad_status_and_bad_id(conn: sqlite3.Connection) -> None:
    with pytest.raises(FillStatusError):
        mark_fill(conn, 1, "filled")
    with pytest.raises(FillNotFound):
        mark_fill(conn, 99, "submitted")
