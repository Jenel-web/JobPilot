"""Tests for the answer engine's no-AI paths (engine/forms/answers.py: answer_field, answer_form).

Fake data, an in-memory database and a temporary answers.json only. RAG is faked with
``fake_match`` because mock vectors cannot judge meaning. The AI is replaced by a function
that FAILS the test if called: none of these paths may use it.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from engine import ai, learning, rag
from engine.db import connect, init_db
from engine.forms.answers import FieldAnswer, answer_field, answer_form
from engine.forms.reader import FormField
from engine.profile import load_answers

VISA = "Will you need visa sponsorship?"
START = "When can you start?"
RELOCATE = "Are you willing to relocate?"
WORK_AUTH = "Are you legally authorized to work in the Philippines?"

VALUES = {"email": "juan@example.com", "first_name": "Juan"}


@pytest.fixture
def answers_file(tmp_path: Path) -> Path:
    path = tmp_path / "answers.json"
    path.write_text(
        json.dumps(
            [
                {"question": VISA, "answer": "No", "kind": "protected"},
                {"question": START, "answer": "2 weeks notice", "kind": "fixed"},
                {"question": RELOCATE, "answer": "Yes, anywhere", "kind": "fixed", "location_scope": "remote"},
                {"question": RELOCATE, "answer": "Yes, within Metro Manila", "kind": "fixed", "location_scope": "any"},
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


@pytest.fixture(autouse=True)
def no_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    """These paths must never call the AI."""

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("the AI was called on a path that must not use it")

    monkeypatch.setattr(ai, "ask_ai", boom)


def fake_match(monkeypatch: pytest.MonkeyPatch, ref: str | None, score: float) -> None:
    """Pretend RAG found ``ref`` with ``score``."""
    hit = None if ref is None else rag.Hit(1, "answer", ref, ref, score)
    result = rag.SavedMatch(hit, hit is not None and score >= rag.MATCH_THRESHOLD, ("fixed",), rag.MATCH_THRESHOLD)
    monkeypatch.setattr(rag, "match_saved_question", lambda *args, **kwargs: result)


def field(label: str, type: str = "text", **kw: object) -> FormField:
    return FormField(label=label, type=type, **kw)  # type: ignore[arg-type]


def answer(conn: sqlite3.Connection, f: FormField, **kw: object) -> FieldAnswer:
    return answer_field(conn, f, VALUES, **kw)  # type: ignore[arg-type]


# ---- A: no label ------------------------------------------------------------------------


def test_unlabeled_field_needs_you_and_is_not_learned(conn: sqlite3.Connection) -> None:
    result = answer(conn, field(""))
    assert result.value == "" and result.flagged and result.source == "none"
    assert "needs you" in result.note
    assert learning.open_unknowns(conn) == []


# ---- B: personal fields ------------------------------------------------------------------


def test_personal_field_is_filled_by_code_without_triage(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("a personal field must not be triaged or searched")

    monkeypatch.setattr(learning, "triage_question", boom)
    result = answer(conn, field("Email", "email"))
    assert (result.value, result.source, result.flagged) == ("juan@example.com", "personal", False)


def test_personal_field_with_no_profile_value_is_flagged(conn: sqlite3.Connection) -> None:
    result = answer(conn, field("Phone", "tel"))
    assert result.value == "" and result.flagged and result.source == "personal"


# ---- E: matched answers -------------------------------------------------------------------


def test_protected_match_is_used_exactly_and_flagged(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_match(monkeypatch, VISA, 0.93)
    result = answer(conn, field("Do you require sponsorship to work here?"))
    assert (result.value, result.kind, result.source) == ("No", "protected", "bank")
    assert result.flagged and result.recommended
    assert result.matched_question == VISA and result.confidence == 0.93


def test_fixed_match_is_used_as_written_and_not_flagged(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_match(monkeypatch, START, 0.97)
    result = answer(conn, field("When can you start?"))
    assert (result.value, result.kind, result.flagged) == ("2 weeks notice", "fixed", False)


def test_strong_match_in_new_words_queues_a_wording(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_match(monkeypatch, START, 0.9)
    answer(conn, field("When could you begin?"), page_url="https://x.test/a")
    pending = learning.pending_wordings(conn)
    assert [row["wording"] for row in pending] == ["When could you begin?"]


@pytest.mark.parametrize(("scope", "expected"), [("remote", "Yes, anywhere"), ("any", "Yes, within Metro Manila")])
def test_job_location_scope_picks_the_right_row(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, scope: str, expected: str
) -> None:
    fake_match(monkeypatch, RELOCATE, 0.95)
    assert answer(conn, field(RELOCATE), job_scope=scope).value == expected


def test_scope_without_its_own_row_falls_back_to_any(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_match(monkeypatch, RELOCATE, 0.95)
    assert answer(conn, field(RELOCATE), job_scope="abroad").value == "Yes, within Metro Manila"


def test_radio_gets_the_matching_option(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_match(monkeypatch, VISA, 0.95)
    result = answer(conn, field("Sponsorship needed?", "radio", options=["Yes", "No"]))
    assert result.value == "No"


def test_radio_with_no_fitting_option_is_empty_and_flagged(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_match(monkeypatch, START, 0.95)
    result = answer(conn, field("When can you start?", "dropdown", options=["Immediately", "In a month"]))
    assert result.value == "" and result.flagged and "options" in result.note


# ---- F: no match ---------------------------------------------------------------------------


def test_sensitive_weak_match_fills_closest_as_not_recommended(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_match(monkeypatch, VISA, 0.78)
    result = answer(conn, field(WORK_AUTH))
    assert result.value == "No" and result.flagged and not result.recommended
    assert "NOT RECOMMENDED" in result.note
    assert result.unknown_id is not None  # also filed for you to answer properly


def test_sensitive_with_nothing_saved_is_empty_and_goes_to_unknown(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_match(monkeypatch, None, 0.0)
    result = answer(conn, field("Have you ever been employed by a government agency?"))
    assert result.value == "" and result.flagged and result.source == "none"
    assert "yourself" in result.note
    assert [r["question_text"] for r in learning.open_unknowns(conn)] == [
        "Have you ever been employed by a government agency?"
    ]


def test_protected_match_is_never_downgraded_by_the_word_list(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_match(monkeypatch, VISA, 0.9)
    result = answer(conn, field("Do you need a visa?"))
    assert result.value == "No" and result.kind == "protected" and result.recommended


# ---- answer_form -----------------------------------------------------------------------------


def test_answer_form_keeps_page_order(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_match(monkeypatch, START, 0.95)
    fields = [field("First name"), field("When can you start?"), field("")]
    results = answer_form(conn, fields)
    assert [r.label for r in results] == ["First name", "When can you start?", ""]
    assert results[1].value == "2 weeks notice"


def test_one_failing_field_does_not_stop_the_rest(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_match(monkeypatch, START, 0.95)
    real = learning.triage_question

    def flaky(c: sqlite3.Connection, question: str, **kwargs: object) -> object:
        if question == "Bad one":
            raise RuntimeError("search is down")
        return real(c, question, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(learning, "triage_question", flaky)
    results = answer_form(conn, [field("Bad one"), field("When can you start?")])
    assert results[0].value == "" and results[0].flagged and "error" in results[0].note
    assert results[1].value == "2 weeks notice"


def test_answer_form_logs_one_action_without_values(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_match(monkeypatch, START, 0.95)
    answer_form(conn, [field("When can you start?")], page_url="https://x.test/a")
    rows = conn.execute("SELECT kind, details FROM action_log").fetchall()
    assert len(rows) == 1 and rows[0]["kind"] == "read"
    assert "2 weeks" not in rows[0]["details"]
