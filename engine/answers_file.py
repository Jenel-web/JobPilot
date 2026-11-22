"""Safe reading and writing of ``data/answers.json``.

``answers.json`` is the ONE place your saved answers live: the database is rebuilt from it by
``profile.load_answers``. So every change to it goes through here, and every change follows the same rules:

* **Backup first.** A timestamped copy (``answers.backup-<date>-<time>.json``) is made before the file changes.
* **Replace in one step.** We write a temporary file, then swap it in, so a crash can never leave a
  half-written file.
* **Validate before writing.** An entry is checked with the same model ``load_answers`` uses
  (:class:`engine.profile.AnswerEntry`), so we never save something the loader would later reject.
  A refused change makes no backup and changes nothing.
* **An answer is identified by question + scope + city** (the database's unique key). ``add_entry`` refuses
  to overwrite one; ``update_entry`` is the only way to change one on purpose.

Used by ``engine/learning.py`` (approved wordings, answered unknown questions) and the answer bank API.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from engine.profile import ANSWERS_PATH, AnswerEntry


class AnswersFileError(Exception):
    """Something you can fix: the file is unreadable, an entry is invalid, or an entry was not found."""


class InvalidEntry(AnswersFileError):
    """The answer is not valid (blank text, bad kind or scope, ``city`` scope without a city)."""


class EntryExists(AnswersFileError):
    """An answer with the same question + scope + city is already saved."""


class EntryNotFound(AnswersFileError):
    """No saved answer has that question + scope + city."""


def read_answers(path: Path = ANSWERS_PATH) -> list[dict]:
    """Return the raw list of answers from ``path``.

    Raises:
        AnswersFileError: the file cannot be read or is not a JSON list.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise AnswersFileError(f"Cannot read {path.name}: {exc}") from exc
    if not isinstance(data, list):
        raise AnswersFileError(f"{path.name} must be a list of answers.")
    return data


def backup(path: Path = ANSWERS_PATH) -> Path:
    """Copy the file to ``answers.backup-<date>-<time>.json`` next to it and return the copy's path.

    A backup NEVER overwrites an older one: two changes in the same second get ``-2``, ``-3``... added to the
    name. (Otherwise a quick second edit would destroy the copy made before the first one.)
    """
    stamp = f"{datetime.now():%Y-%m-%d-%H%M%S}"
    target = path.with_name(f"{path.stem}.backup-{stamp}{path.suffix}")
    number = 2
    while target.exists():
        target = path.with_name(f"{path.stem}.backup-{stamp}-{number}{path.suffix}")
        number += 1
    shutil.copy2(path, target)
    return target


def write_answers(path: Path, entries: list[dict]) -> None:
    """Replace the file in one step: write a temp file, then swap it in."""
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _same_entry(entry: dict, question: str, scope: str, city: str) -> bool:
    """True when ``entry`` is the saved answer for this question + scope + city (the database's unique key)."""
    return (
        str(entry.get("question", "")).strip() == question
        and str(entry.get("location_scope", "any")) == scope
        and str(entry.get("city", "")).strip() == city
    )


def _clean(question: str, answer: str, kind: str, scope: str, city: str) -> tuple[str, str]:
    """Validate one answer; return ``(question, city)`` tidied. A city only means something for the 'city' scope.

    Raises:
        InvalidEntry: blank text, unknown kind or scope, or ``city`` scope without a city.
    """
    question, city = question.strip(), city.strip()
    try:
        AnswerEntry.model_validate(
            {"question": question, "answer": answer, "kind": kind, "location_scope": scope, "city": city}
        )
    except ValidationError as exc:
        first = exc.errors()[0]
        raise InvalidEntry(f"Invalid answer ({'.'.join(str(p) for p in first['loc'])}): {first['msg']}") from exc
    if scope == "city" and not city:
        raise InvalidEntry("Scope 'city' needs a city.")
    return question, (city if scope == "city" else "")


def _fresh(question: str, answer: str, kind: str, scope: str, city: str) -> dict:
    """A new file entry. Optional keys are only written when they carry information."""
    entry: dict = {"question": question, "answer": answer}
    if scope != "any":
        entry["location_scope"] = scope
    if city:
        entry["city"] = city
    entry["kind"] = kind
    return entry


def add_entry(path: Path, *, question: str, answer: str, kind: str, scope: str = "any", city: str = "") -> Path:
    """Add a NEW answer. Returns the backup made.

    Raises:
        InvalidEntry: the answer is not valid.
        EntryExists: that question + scope + city is already saved (use :func:`update_entry`: an existing,
            possibly protected, answer is never overwritten by an add).
    """
    question, city = _clean(question, answer, kind, scope, city)
    entries = read_answers(path)
    if any(_same_entry(e, question, scope, city) for e in entries):
        raise EntryExists(f"There is already a saved answer for {question!r} (scope {scope!r}).")
    made = backup(path)
    entries.append(_fresh(question, answer, kind, scope, city))
    write_answers(path, entries)
    return made


def update_entry(
    path: Path,
    *,
    question: str,
    old_scope: str,
    old_city: str,
    answer: str,
    kind: str,
    scope: str,
    city: str,
) -> Path:
    """Change one saved answer, found by its current question + scope + city. Returns the backup made.

    The question text stays the same (to rename a question, delete it and add a new one). The entry keeps its
    place in the file and its ``also_asked_as`` wordings.

    Raises:
        EntryNotFound: nothing is saved under the old key.
        EntryExists: the new scope + city would collide with another saved answer for this question.
        InvalidEntry: the new values are not valid.
    """
    question, city = _clean(question, answer, kind, scope, city)
    old_city = old_city.strip()
    entries = read_answers(path)
    target = next((e for e in entries if _same_entry(e, question, old_scope, old_city)), None)
    if target is None:
        raise EntryNotFound(f"No saved answer for {question!r} (scope {old_scope!r}) in {path.name}.")
    moved = (scope, city) != (old_scope, old_city)
    if moved and any(_same_entry(e, question, scope, city) for e in entries):
        raise EntryExists(f"There is already a saved answer for {question!r} (scope {scope!r}).")
    made = backup(path)
    target["answer"], target["kind"] = answer, kind
    for key, value in (("location_scope", scope if scope != "any" else None), ("city", city or None)):
        if value is None:
            target.pop(key, None)
        else:
            target[key] = value
    write_answers(path, entries)
    return made


def upsert_entry(
    path: Path,
    *,
    question: str,
    answer: str,
    kind: str,
    scope: str = "any",
    city: str = "",
) -> Path:
    """Add an answer, or overwrite the one with the same question + scope + city. Returns the backup made.

    Prefer :func:`add_entry` / :func:`update_entry`: this one silently replaces an existing answer.
    An updated entry keeps its ``also_asked_as`` wordings.

    Raises:
        InvalidEntry: the entry is invalid.
        AnswersFileError: the file cannot be read.
    """
    question, city = _clean(question, answer, kind, scope, city)
    entries = read_answers(path)
    made = backup(path)
    existing = next((e for e in entries if _same_entry(e, question, scope, city)), None)
    if existing is None:
        entries.append(_fresh(question, answer, kind, scope, city))
    else:
        existing["answer"], existing["kind"] = answer, kind
    write_answers(path, entries)
    return made


def delete_entry(path: Path, *, question: str, scope: str = "any", city: str = "") -> Path:
    """Remove one answer (matched on question + scope + city). Returns the backup made.

    Raises:
        EntryNotFound: no such answer.
        AnswersFileError: the file cannot be read.
    """
    question, city = question.strip(), city.strip()
    entries = read_answers(path)
    kept = [e for e in entries if not _same_entry(e, question, scope, city)]
    if len(kept) == len(entries):
        raise EntryNotFound(f"No saved answer for {question!r} (scope {scope!r}) in {path.name}.")
    made = backup(path)
    write_answers(path, kept)
    return made
