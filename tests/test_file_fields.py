"""Tests for file-upload fields and for the preview mode of ``forms answer``.

1. A ``file`` field is never looked up in the answer bank and never filed as an unknown
   question: the engine only says what kind of file is wanted (resume / none).
2. ``record=False`` (the CLI preview) reads and decides but writes nothing to the
   unknown questions list or the suggested wordings.

Fake data and an in-memory database only. The AI is replaced by a function that fails if called.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from engine import ai, cli, learning, rag
from engine.db import connect, init_db
from engine.forms import answers as answers_module
from engine.forms import drafting
from engine.forms.answers import FieldAnswer, answer_field, answer_form
from engine.forms.reader import FormField
from engine.profile import load_answers

ROOT = Path(__file__).resolve().parent.parent
START = "When can you start?"
RESUME_QUESTION = "Do you have a resume available to upload?"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    path = tmp_path / "answers.json"
    path.write_text(
        json.dumps(
            [
                {"question": START, "answer": "2 weeks notice", "kind": "fixed"},
                {"question": RESUME_QUESTION, "answer": "Yes, PDF format", "kind": "fixed"},
            ]
        ),
        encoding="utf-8",
    )
    connection = connect(":memory:")
    init_db(connection)
    load_answers(connection, path)
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def no_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("the AI was called on a path that must not use it")

    monkeypatch.setattr(ai, "ask_ai", boom)


def fake_match(monkeypatch: pytest.MonkeyPatch, ref: str | None, score: float) -> None:
    hit = None if ref is None else rag.Hit(1, "answer", ref, ref, score)
    result = rag.SavedMatch(hit, hit is not None and score >= rag.MATCH_THRESHOLD, ("fixed",), rag.MATCH_THRESHOLD)
    monkeypatch.setattr(rag, "match_saved_question", lambda *args, **kwargs: result)


def file_field(label: str) -> FormField:
    return FormField(label=label, type="file")


def count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def answer(conn: sqlite3.Connection, f: FormField, **kw: object) -> FieldAnswer:
    return answer_field(conn, f, {}, **kw)  # type: ignore[arg-type]


# ---- file fields ------------------------------------------------------------------------


@pytest.mark.parametrize("label", ["Resume", "Resume/CV", "Upload your CV", "Curriculum Vitae"])
def test_resume_file_field_is_a_resume_upload(conn: sqlite3.Connection, label: str) -> None:
    result = answer(conn, file_field(label))
    assert result.source == "resume" and result.value == ""
    assert result.flagged and "job post" in result.note  # no job post given: the picker has nothing to read


def test_resume_file_field_with_a_job_post_is_not_flagged(conn: sqlite3.Connection) -> None:
    result = answer(conn, file_field("Resume"), job_text="Backend intern, Makati")
    assert result.source == "resume" and not result.flagged


@pytest.mark.parametrize("label", ["Attach", "Upload", "Choose file"])
def test_generic_attach_is_a_flagged_resume_guess(conn: sqlite3.Connection, label: str) -> None:
    result = answer(conn, file_field(label), job_text="Backend intern")
    assert result.source == "resume" and result.flagged and "guess" in result.note


@pytest.mark.parametrize("label", ["Photo", "Cover letter", "Transcript of records"])
def test_other_files_need_you(conn: sqlite3.Connection, label: str) -> None:
    result = answer(conn, file_field(label))
    assert result.source == "none" and result.value == "" and result.flagged and "needs you" in result.note


def test_file_field_with_a_resume_and_a_cover_letter_word_is_not_a_resume(conn: sqlite3.Connection) -> None:
    assert answer(conn, file_field("Cover letter (not your resume)")).source == "none"


def test_file_fields_never_reach_the_bank_or_the_lists(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("a file field must not be looked up")

    monkeypatch.setattr(rag, "match_saved_question", boom)
    for label in ("Resume", "Attach", "Photo", "Cover letter"):
        answer(conn, file_field(label))
    assert count(conn, "unknown_questions") == 0 and count(conn, "suggested_wordings") == 0


def test_a_text_field_with_resume_in_its_label_is_not_a_file_upload(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_match(monkeypatch, RESUME_QUESTION, 0.99)
    result = answer(conn, FormField(label=RESUME_QUESTION, type="text"))
    assert result.source == "bank" and result.value == "Yes, PDF format"


# ---- preview mode: record=False ----------------------------------------------------------


def test_preview_does_not_record_unknown_questions(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_match(monkeypatch, None, 0.0)
    f = FormField(label="Pick a colour", type="select", options=["Red", "Blue"])
    result = answer(conn, f, record=False)
    assert result.source == "none" and result.unknown_id is None
    assert count(conn, "unknown_questions") == 0
    assert answer(conn, f).unknown_id is not None  # the default still records
    assert count(conn, "unknown_questions") == 1


def test_preview_does_not_record_suggested_wordings(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_match(monkeypatch, START, 0.9)
    f = FormField(label="When do you start?", type="text")
    result = answer(conn, f, record=False)
    assert result.value == "2 weeks notice"  # still answered from the bank
    assert count(conn, "suggested_wordings") == 0
    answer(conn, f)
    assert count(conn, "suggested_wordings") == 1


def test_answer_form_passes_record_through(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_match(monkeypatch, None, 0.0)
    f = FormField(label="Pick a colour", type="select", options=["Red", "Blue"])
    answer_form(conn, [f], record=False)
    assert count(conn, "unknown_questions") == 0
    answer_form(conn, [f])
    assert count(conn, "unknown_questions") == 1


def test_triage_without_record_reports_unknown_but_saves_nothing(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_match(monkeypatch, None, 0.0)
    result = learning.triage_question(conn, "Favourite pizza?", record=False)
    assert result.outcome == "unknown" and result.unknown_id is None
    assert count(conn, "unknown_questions") == 0


# ---- the CLI command ---------------------------------------------------------------------


def run_cli(monkeypatch: pytest.MonkeyPatch, conn: sqlite3.Connection, *argv: str) -> dict[str, object]:
    """Run ``forms answer`` with the database and the answer engine replaced; returns what the engine was called with."""
    seen: dict[str, object] = {}

    def fake_answer_form(connection: object, fields: list[FormField], **kwargs: object) -> list[FieldAnswer]:
        seen.update(kwargs, field_count=len(fields))
        return [FieldAnswer("Resume", "", "resume", False)]

    monkeypatch.setattr(cli, "connect", lambda: conn)
    monkeypatch.setattr(answers_module, "answer_form", fake_answer_form)
    monkeypatch.chdir(ROOT)
    seen["exit"] = cli.main(["forms", "answer", *argv])
    return seen


def test_cli_accepts_a_relative_path_and_previews_by_default(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = run_cli(monkeypatch, conn, "--fixture", "fixtures/forms/sample_form.html")
    assert seen["exit"] == 0 and seen["record"] is False and seen["field_count"] > 0
    out = capsys.readouterr().out
    assert "preview only" in out and "resume: picked at fill time" in out


def test_cli_record_flag_turns_recording_on(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = run_cli(monkeypatch, conn, "--fixture", "sample_form", "--record")
    assert seen["exit"] == 0 and seen["record"] is True


def test_cli_missing_fixture_is_an_error(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = run_cli(monkeypatch, conn, "--fixture", "does_not_exist")
    assert seen["exit"] == 1 and "not found" in capsys.readouterr().err


# ---- forms elaborate -----------------------------------------------------------------------


def test_elaborate_command_shows_the_notes_and_result_and_saves_nothing(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, object] = {}

    def fake_answer_form(connection: object, fields: list[FormField], **kwargs: object) -> list[FieldAnswer]:
        seen.update(kwargs, types={f.type for f in fields})
        note = "saved 'Yes' elaborated from your notes (EconLens PH): check it"
        return [FieldAnswer(f.label, "Yes. I used Docker.", "bank", True, note, kind="fixed", matched_question="Q") for f in fields]

    monkeypatch.setattr(cli, "connect", lambda: conn)
    monkeypatch.setattr(answers_module, "answer_form", fake_answer_form)
    monkeypatch.setattr(drafting, "gather_facts", lambda *a, **k: [rag.Hit(1, "project", "EconLens PH", "Docker.", 0.8)])
    monkeypatch.chdir(ROOT)
    assert cli.main(["forms", "elaborate", "--fixture", "sample_form", "--as-text"]) == 0
    out = capsys.readouterr().out
    assert seen["record"] is False and seen["types"] <= {"text", "textarea", "email", "tel", "file", "url", "number", "date"}
    assert "ELABORATED" in out and "[used]" in out and "Yes. I used Docker." in out


def test_elaborate_question_option_skips_the_ai_for_a_logistics_question(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "connect", lambda: conn)
    monkeypatch.setattr(drafting, "gather_facts", lambda *a, **k: [])

    def boom(*a: object, **k: object) -> None:
        raise AssertionError("the AI must not be called for a logistics question")

    monkeypatch.setattr(ai, "ask_ai", boom)
    assert cli.main(["forms", "elaborate", "--question", "Are you open to a hybrid setup?"]) == 0
    assert "NOT elaborated" in capsys.readouterr().out
