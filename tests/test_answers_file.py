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


def test_backups_in_the_same_second_never_overwrite_each_other(path: Path) -> None:
    first = answers_file.backup(path)
    path.write_text("[]", encoding="utf-8")
    second = answers_file.backup(path)
    assert first != second and first.exists() and second.exists()
    assert "Now" in first.read_text(encoding="utf-8") and second.read_text(encoding="utf-8") == "[]"


def test_add_entry_refuses_to_overwrite(path: Path) -> None:
    before = path.read_text(encoding="utf-8")
    with pytest.raises(answers_file.EntryExists):
        answers_file.add_entry(path, question="When can you start?", answer="Never", kind="open")
    assert path.read_text(encoding="utf-8") == before and list(path.parent.glob("answers.backup-*")) == []


def test_update_entry_changes_in_place_and_checks_collisions(path: Path) -> None:
    answers_file.add_entry(path, question="When can you start?", answer="Later", kind="open", scope="remote")
    answers_file.update_entry(
        path, question="When can you start?", old_scope="any", old_city="", answer="Soon", kind="fixed", scope="city", city="Makati"
    )
    first = read(path)[0]
    assert first["answer"] == "Soon" and first["location_scope"] == "city" and first["city"] == "Makati"
    assert first["also_asked_as"] == ["Start date?"]
    with pytest.raises(answers_file.EntryExists):  # moving onto the remote answer's key
        answers_file.update_entry(
            path, question="When can you start?", old_scope="city", old_city="Makati", answer="x", kind="open", scope="remote", city=""
        )
    with pytest.raises(answers_file.EntryNotFound):
        answers_file.update_entry(path, question="Nope?", old_scope="any", old_city="", answer="x", kind="open", scope="any", city="")
