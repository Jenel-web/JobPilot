"""Tests for engine/learning.py: unknown questions and suggested wordings.

Fake data, an in-memory database and a temporary answers.json only. Your real
data/answers.json is never touched.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from engine import learning, rag
from engine.db import connect, init_db
from engine.profile import load_answers

SALARY = "What is your expected monthly salary?"
CRIME = "Have you ever been convicted of a crime?"


@pytest.fixture
def answers_file(tmp_path: Path) -> Path:
    path = tmp_path / "answers.json"
    path.write_text(
        json.dumps(
            [
                {"question": SALARY, "answer": "PHP 20,000", "kind": "fixed", "also_asked_as": ["Expected salary"]},
                {"question": CRIME, "answer": "No", "kind": "protected"},
            ]
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def conn(answers_file: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    init_db(connection)
    load_answers(connection, answers_file)
    yield connection
    connection.close()


def fake_match(monkeypatch: pytest.MonkeyPatch, ref: str | None, score: float, kinds: tuple[str, ...] = ("fixed",)) -> None:
    """Pretend RAG found ``ref`` with ``score`` (mock vectors cannot judge meaning)."""
    hit = None if ref is None else rag.Hit(1, "answer", ref, ref, score)
    result = rag.SavedMatch(hit, hit is not None and score >= rag.MATCH_THRESHOLD, kinds, rag.MATCH_THRESHOLD)
    monkeypatch.setattr(rag, "match_saved_question", lambda *args, **kwargs: result)


# ---- rule 1: unknown questions ---------------------------------------------------------


def test_unmatched_question_goes_to_unknown_list(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_match(monkeypatch, SALARY, 0.5)
    result = learning.triage_question(conn, "Favourite pizza topping?", page_url="https://x.test/a", field_type="text")
    assert result.outcome == "unknown"
    row = conn.execute("SELECT * FROM unknown_questions").fetchone()
    assert row["question_text"] == "Favourite pizza topping?"
    assert row["status"] == "open" and row["times_seen"] == 1


def test_empty_bank_also_goes_to_unknown(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_match(monkeypatch, None, 0)
    assert learning.triage_question(conn, "Anything?").outcome == "unknown"


def test_same_unknown_question_is_counted_not_duplicated(conn: sqlite3.Connection) -> None:
    first = learning.record_unknown(conn, "Favourite pizza topping?")
    again = learning.record_unknown(conn, "  favourite   PIZZA topping?  ")
    assert first == again
    assert conn.execute("SELECT count(*) FROM unknown_questions").fetchone()[0] == 1
    assert conn.execute("SELECT times_seen FROM unknown_questions").fetchone()[0] == 2


def test_blank_question_is_refused(conn: sqlite3.Connection) -> None:
    with pytest.raises(learning.LearningError):
        learning.triage_question(conn, "   ")


def test_unknown_options_are_kept(conn: sqlite3.Connection) -> None:
    learning.record_unknown(conn, "Pick one", options=("a", "b"))
    assert json.loads(conn.execute("SELECT options FROM unknown_questions").fetchone()["options"]) == ["a", "b"]


# ---- rule 2: suggested wordings ----------------------------------------------------------


def test_new_wording_that_matches_becomes_a_pending_suggestion(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_match(monkeypatch, SALARY, 0.91)
    result = learning.triage_question(conn, "How much pay do you want?", page_url="https://x.test/a")
    assert result.outcome == "matched" and result.suggestion_id is not None
    row = conn.execute("SELECT * FROM suggested_wordings").fetchone()
    assert (row["status"], row["matched_question"], row["protected"]) == ("pending", SALARY, 0)
    assert conn.execute("SELECT count(*) FROM unknown_questions").fetchone()[0] == 0


def test_wrong_match_is_never_saved_without_approval(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, answers_file: Path
) -> None:
    """The point of the approval step: a matched wording must not reach answers.json or answer_aliases by itself."""
    before = answers_file.read_text(encoding="utf-8")
    fake_match(monkeypatch, SALARY, 0.86)
    learning.triage_question(conn, "Do you need sponsorship?")
    assert answers_file.read_text(encoding="utf-8") == before
    assert conn.execute("SELECT count(*) FROM answer_aliases WHERE alias = 'Do you need sponsorship?'").fetchone()[0] == 0


def test_known_wordings_are_not_suggested(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_match(monkeypatch, SALARY, 1.0)
    assert learning.triage_question(conn, SALARY).suggestion_id is None  # the saved question itself
    assert learning.triage_question(conn, "  expected   SALARY ").suggestion_id is None  # an existing wording
    assert conn.execute("SELECT count(*) FROM suggested_wordings").fetchone()[0] == 0


def test_seeing_a_wording_again_counts_it(conn: sqlite3.Connection) -> None:
    first = learning.suggest_wording(conn, "Pay you want?", SALARY, 0.9)
    again = learning.suggest_wording(conn, "pay  you want?", SALARY, 0.88)
    assert first == again
    assert conn.execute("SELECT times_seen FROM suggested_wordings").fetchone()[0] == 2


def test_rejected_wording_never_comes_back(conn: sqlite3.Connection) -> None:
    suggestion = learning.suggest_wording(conn, "Pay you want?", SALARY, 0.9)
    assert suggestion is not None
    learning.reject_wording(conn, suggestion)
    assert learning.suggest_wording(conn, "Pay you want?", SALARY, 0.9) is None
    assert learning.pending_wordings(conn) == []


# ---- approving: the file --------------------------------------------------------------------


def test_approve_writes_the_wording_into_answers_json(conn: sqlite3.Connection, answers_file: Path) -> None:
    suggestion = learning.suggest_wording(conn, "How much pay do you want?", SALARY, 0.9)
    assert suggestion is not None
    original = answers_file.read_text(encoding="utf-8")
    backup = learning.approve_wording(conn, suggestion, answers_path=answers_file)
    assert backup is not None and backup.read_text(encoding="utf-8") == original  # backup holds the old file
    saved = json.loads(answers_file.read_text(encoding="utf-8"))
    assert saved[0]["also_asked_as"] == ["Expected salary", "How much pay do you want?"]
    assert conn.execute("SELECT status FROM suggested_wordings").fetchone()[0] == "approved"
    assert not (answers_file.parent / "answers.json.tmp").exists()


def test_load_keeps_approved_wordings(conn: sqlite3.Connection, answers_file: Path) -> None:
    """``load`` rebuilds aliases from the file, so an approved wording must survive it."""
    suggestion = learning.suggest_wording(conn, "How much pay do you want?", SALARY, 0.9)
    assert suggestion is not None
    learning.approve_wording(conn, suggestion, answers_path=answers_file)
    load_answers(conn, answers_file)
    aliases = {r["alias"] for r in conn.execute("SELECT alias FROM answer_aliases WHERE question = ?", (SALARY,))}
    assert "How much pay do you want?" in aliases


def test_approving_twice_is_refused(conn: sqlite3.Connection, answers_file: Path) -> None:
    suggestion = learning.suggest_wording(conn, "Pay you want?", SALARY, 0.9)
    assert suggestion is not None
    learning.approve_wording(conn, suggestion, answers_path=answers_file)
    with pytest.raises(learning.LearningError, match="already approved"):
        learning.approve_wording(conn, suggestion, answers_path=answers_file)


def test_unknown_suggestion_id_is_refused(conn: sqlite3.Connection, answers_file: Path) -> None:
    with pytest.raises(learning.LearningError, match="no suggestion"):
        learning.approve_wording(conn, 999, answers_path=answers_file)


def test_protected_needs_explicit_confirmation(conn: sqlite3.Connection, answers_file: Path) -> None:
    suggestion = learning.suggest_wording(conn, "Any criminal record?", CRIME, 0.9)
    assert suggestion is not None
    assert conn.execute("SELECT protected FROM suggested_wordings").fetchone()[0] == 1
    before = answers_file.read_text(encoding="utf-8")
    with pytest.raises(learning.LearningError, match="PROTECTED"):
        learning.approve_wording(conn, suggestion, answers_path=answers_file)
    assert answers_file.read_text(encoding="utf-8") == before  # refused: file untouched
    learning.approve_wording(conn, suggestion, confirm_protected=True, answers_path=answers_file)
    assert "Any criminal record?" in json.loads(answers_file.read_text(encoding="utf-8"))[1]["also_asked_as"]


def test_approve_fails_clearly_if_saved_question_left_the_file(conn: sqlite3.Connection, answers_file: Path) -> None:
    suggestion = learning.suggest_wording(conn, "Pay you want?", SALARY, 0.9)
    assert suggestion is not None
    answers_file.write_text("[]", encoding="utf-8")
    with pytest.raises(learning.LearningError, match="not in answers.json"):
        learning.approve_wording(conn, suggestion, answers_path=answers_file)


def test_broken_answers_file_is_not_overwritten(conn: sqlite3.Connection, answers_file: Path) -> None:
    suggestion = learning.suggest_wording(conn, "Pay you want?", SALARY, 0.9)
    assert suggestion is not None
    answers_file.write_text("{not json", encoding="utf-8")
    with pytest.raises(learning.LearningError, match="Cannot read"):
        learning.approve_wording(conn, suggestion, answers_path=answers_file)
    assert answers_file.read_text(encoding="utf-8") == "{not json"


def test_old_database_gets_the_new_columns() -> None:
    """A database made before this feature must be upgraded by init_db, not break."""
    old = connect(":memory:")
    old.executescript(
        "CREATE TABLE unknown_questions (id INTEGER PRIMARY KEY AUTOINCREMENT, question_text TEXT NOT NULL,"
        " page_url TEXT, field_type TEXT, options TEXT NOT NULL DEFAULT '[]',"
        " first_seen TEXT NOT NULL DEFAULT (datetime('now')), status TEXT NOT NULL DEFAULT 'open', answer_id INTEGER);"
    )
    init_db(old)
    assert learning.record_unknown(old, "Old question?") > 0
    old.close()
