"""Safe reading and writing of ``data/answers.json``.

``answers.json`` is the ONE place your saved answers live: the database is rebuilt from it by
``profile.load_answers``. So every change to it goes through here, and every change follows the same rules:

* **Backup first.** A timestamped copy (``answers.backup-<date>-<time>.json``) is made before the file changes.
* **Replace in one step.** We write a temporary file, then swap it in, so a crash can never leave a
  half-written file.
* **Validate before writing.** An entry is checked with the same model ``load_answers`` uses
  (:class:`engine.profile.AnswerEntry`), so we never save something the loader would later reject.

Used by ``engine/learning.py`` (approved wordings, answered unknown questions) and, later, the answer bank API.
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
    """Copy the file to ``answers.backup-<date>-<time>.json`` next to it and return the copy's path."""
    target = path.with_name(f"{path.stem}.backup-{datetime.now():%Y-%m-%d-%H%M%S}{path.suffix}")
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


def upsert_entry(
    path: Path,
    *,
    question: str,
    answer: str,
    kind: str,
    scope: str = "any",
    city: str = "",
) -> Path:
    """Add an answer, or update the one with the same question + scope + city. Returns the backup made.

    An updated entry keeps its ``also_asked_as`` wordings. Optional keys (``location_scope``, ``city``) are
    only written when they carry information, so the file stays easy to read.

    Raises:
        AnswersFileError: the entry is invalid (blank text, bad kind or scope, ``city`` scope without a city)
            or the file cannot be read.
    """
    question, city = question.strip(), city.strip()
    try:
        AnswerEntry.model_validate(
            {"question": question, "answer": answer, "kind": kind, "location_scope": scope, "city": city}
        )
    except ValidationError as exc:
        first = exc.errors()[0]
        raise AnswersFileError(f"Invalid answer ({'.'.join(str(p) for p in first['loc'])}): {first['msg']}") from exc
    if scope == "city" and not city:
        raise AnswersFileError("Scope 'city' needs a city.")
    if scope != "city":
        city = ""  # a city only means something for the 'city' scope

    entries = read_answers(path)
    made = backup(path)
    existing = next((e for e in entries if _same_entry(e, question, scope, city)), None)
    if existing is None:
        fresh: dict = {"question": question, "answer": answer}
        if scope != "any":
            fresh["location_scope"] = scope
        if city:
            fresh["city"] = city
        fresh["kind"] = kind
        entries.append(fresh)
    else:
        existing["answer"], existing["kind"] = answer, kind
    write_answers(path, entries)
    return made


def delete_entry(path: Path, *, question: str, scope: str = "any", city: str = "") -> Path:
    """Remove one answer (matched on question + scope + city). Returns the backup made.

    Raises:
        AnswersFileError: no such answer, or the file cannot be read.
    """
    question, city = question.strip(), city.strip()
    entries = read_answers(path)
    kept = [e for e in entries if not _same_entry(e, question, scope, city)]
    if len(kept) == len(entries):
        raise AnswersFileError(f"No saved answer for {question!r} (scope {scope!r}) in {path.name}.")
    made = backup(path)
    write_answers(path, kept)
    return made
