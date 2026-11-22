"""Tests for engine/answers_file.py: safe changes to answers.json (temporary files only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine import answers_file
from engine.answers_file import AnswersFileError


@pytest.fixture
def path(tmp_path: Path) -> Path:
    file = tmp_path / "answers.json"
    file.write_text(
        json.dumps([{"question": "When can you start?", "answer": "Now", "kind": "fixed", "also_asked_as": ["Start date?"]}]),
        encoding="utf-8",
    )
    return file


def read(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_upsert_adds_entry_and_backs_up_the_old_file(path: Path) -> None:
    before = path.read_text(encoding="utf-8")
    backup = answers_file.upsert_entry(path, question=" Do you drive? ", answer="Yes", kind="fixed")
    assert backup.read_text(encoding="utf-8") == before  # the backup is the file as it was
    assert read(path)[-1] == {"question": "Do you drive?", "answer": "Yes", "kind": "fixed"}


def test_upsert_updates_same_key_and_keeps_wordings(path: Path) -> None:
    answers_file.upsert_entry(path, question="When can you start?", answer="Next month", kind="open")
    entries = read(path)
    assert len(entries) == 1
    assert entries[0]["answer"] == "Next month" and entries[0]["kind"] == "open"
    assert entries[0]["also_asked_as"] == ["Start date?"]


def test_city_scope_is_stored_and_needs_a_city(path: Path) -> None:
    answers_file.upsert_entry(path, question="Salary?", answer="20k", kind="fixed", scope="city", city="Makati")
    assert read(path)[-1]["location_scope"] == "city" and read(path)[-1]["city"] == "Makati"
    with pytest.raises(AnswersFileError, match="city"):
        answers_file.upsert_entry(path, question="Salary?", answer="20k", kind="fixed", scope="city")


@pytest.mark.parametrize("bad", [{"kind": "secret"}, {"scope": "mars"}, {"answer": ""}, {"question": "  "}])
def test_invalid_entry_changes_nothing(path: Path, bad: dict) -> None:
    before = path.read_text(encoding="utf-8")
    args = {"question": "Q?", "answer": "A", "kind": "fixed", **bad}
    with pytest.raises(AnswersFileError):
        answers_file.upsert_entry(path, **args)
    assert path.read_text(encoding="utf-8") == before
    assert len(list(path.parent.glob("answers.backup-*"))) == 0  # no backup for a refused change


def test_delete_removes_one_entry_with_backup(path: Path) -> None:
    backup = answers_file.delete_entry(path, question="When can you start?")
    assert read(path) == [] and backup.exists()
    with pytest.raises(AnswersFileError, match="No saved answer"):
        answers_file.delete_entry(path, question="When can you start?")


def test_unreadable_file_is_a_clear_error(tmp_path: Path) -> None:
    bad = tmp_path / "answers.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(AnswersFileError, match="Cannot read"):
        answers_file.read_answers(bad)
