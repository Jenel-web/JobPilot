"""Learning from forms: the unknown questions list and suggested new wordings.

Two rules (your decision):

1. **Cannot answer it -> unknown questions list.** A form question with no close saved
   question is stored once in ``unknown_questions``. Meeting it again on another page
   only raises ``times_seen``. You answer it later and it goes into the answer bank.

2. **Matched in new words -> suggested wording, waiting for your OK.** If a form asks
   "How much pay do you want?" and RAG matches the saved "What is your expected
   monthly salary?", the new wording is saved as a *suggestion*. When you approve it,
   it is written into ``answers.json`` (``also_asked_as``), so next time it scores
   about 1.0.

Why approval and not automatic? A wrong match (say "Do you need sponsorship?" matched
to "Are you a citizen?") would be saved for good and then match at 1.0 on every form,
silently giving a legal answer to the wrong question. So:

* nothing is learned until you approve it;
* wordings that matched a **protected** answer need an extra explicit confirmation;
* the AI is never involved: this is plain code and SQLite.

Writing ``answers.json``: ``load`` rebuilds the aliases from that file every time, so a
wording only survives if it is in the file. Before the first change a timestamped
backup is made, and the file is replaced in one step so a crash cannot leave it half
written.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from engine import rag
from engine.profile import ANSWERS_PATH
from engine.settings import Settings


class LearningError(Exception):
    """Something you can fix (bad id, saved question gone, protected answer not confirmed)."""


def normalize(text: str) -> str:
    """Lowercase with single spaces: the form used to decide whether two wordings are identical."""
    return " ".join(text.lower().split())


# ---- the triage: matched or unknown -------------------------------------------------


@dataclass(frozen=True)
class Triage:
    """What happened to one form question."""

    outcome: Literal["matched", "unknown"]
    match: rag.SavedMatch
    suggestion_id: int | None = None  # set when a new wording was queued for your approval
    unknown_id: int | None = None  # set when the question went to the unknown list


def triage_question(
    conn: sqlite3.Connection,
    question: str,
    *,
    page_url: str = "",
    field_type: str = "",
    options: tuple[str, ...] = (),
    settings: Settings | None = None,
    record: bool = True,
) -> Triage:
    """Look up a form question in the answer bank and file it: matched or unknown.

    The answer engine calls this for every non-personal field. It never changes
    ``answers.json``; it only records suggestions and unknown questions in the database.
    With ``record=False`` (a preview) it only looks up: nothing is written and the ids stay ``None``.

    Raises:
        LearningError: ``question`` is blank (a field with no readable label is
            reported as "needs you", never learned).
    """
    text = " ".join(question.split())
    if not text:
        raise LearningError("A question with no text cannot be learned.")
    match = rag.match_saved_question(conn, text, settings=settings)
    if match.matched and match.hit is not None:
        suggestion = suggest_wording(conn, text, match.hit.ref, match.hit.score, page_url) if record else None
        return Triage("matched", match, suggestion_id=suggestion)
    unknown = record_unknown(conn, text, page_url, field_type, options) if record else None
    return Triage("unknown", match, unknown_id=unknown)


# ---- rule 1: unknown questions --------------------------------------------------------


def record_unknown(
    conn: sqlite3.Connection, question: str, page_url: str = "", field_type: str = "", options: tuple[str, ...] = ()
) -> int:
    """Add a question to the unknown list; if it is already open there, just count it again. Returns its id."""
    key = normalize(question)
    for row in conn.execute("SELECT id, question_text FROM unknown_questions WHERE status = 'open'"):
        if normalize(row["question_text"]) == key:
            with conn:
                conn.execute(
                    "UPDATE unknown_questions SET times_seen = times_seen + 1, last_seen = datetime('now') WHERE id = ?",
                    (row["id"],),
                )
            return int(row["id"])
    with conn:
        cursor = conn.execute(
            "INSERT INTO unknown_questions (question_text, page_url, field_type, options, last_seen)"
            " VALUES (?, ?, ?, ?, datetime('now'))",
            (question.strip(), page_url, field_type, json.dumps(list(options))),
        )
    return int(cursor.lastrowid or 0)


# ---- rule 2: suggested wordings ---------------------------------------------------------


def _known_wordings(conn: sqlite3.Connection, saved_question: str) -> set[str]:
    """The saved question itself plus every wording already stored for it."""
    known = {normalize(saved_question)}
    for row in conn.execute("SELECT alias FROM answer_aliases WHERE question = ?", (saved_question,)):
        known.add(normalize(row["alias"]))
    return known


def suggest_wording(
    conn: sqlite3.Connection, wording: str, saved_question: str, score: float, page_url: str = ""
) -> int | None:
    """Queue ``wording`` as a new way to ask ``saved_question``. Returns the suggestion id, or None.

    Nothing is queued when the wording is already known (the saved question or one of
    its wordings). A wording you rejected stays rejected: it is counted but never
    comes back as pending. Seeing a pending wording again just raises ``times_seen``.
    """
    key = normalize(wording)
    if not key or key in _known_wordings(conn, saved_question):
        return None
    existing = conn.execute(
        "SELECT id, status FROM suggested_wordings WHERE wording_key = ? AND matched_question = ?",
        (key, saved_question),
    ).fetchone()
    with conn:
        if existing:
            conn.execute("UPDATE suggested_wordings SET times_seen = times_seen + 1 WHERE id = ?", (existing["id"],))
            return int(existing["id"]) if existing["status"] == "pending" else None
        kinds = {r["kind"] for r in conn.execute("SELECT kind FROM answers WHERE question = ?", (saved_question,))}
        cursor = conn.execute(
            "INSERT INTO suggested_wordings (wording, wording_key, matched_question, score, page_url, protected)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (wording.strip(), key, saved_question, round(score, 4), page_url, int("protected" in kinds)),
        )
    return int(cursor.lastrowid or 0)


def pending_wordings(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Suggestions waiting for your decision, most-seen first."""
    return conn.execute(
        "SELECT * FROM suggested_wordings WHERE status = 'pending' ORDER BY times_seen DESC, id"
    ).fetchall()


def open_unknowns(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Unanswered questions, most-seen first."""
    return conn.execute("SELECT * FROM unknown_questions WHERE status = 'open' ORDER BY times_seen DESC, id").fetchall()


def approve_wording(
    conn: sqlite3.Connection,
    suggestion_id: int,
    *,
    confirm_protected: bool = False,
    answers_path: Path = ANSWERS_PATH,
) -> Path | None:
    """Write an approved wording into ``answers.json`` and the database. Returns the backup file made.

    Args:
        confirm_protected: required when the saved answer is ``protected``.

    Raises:
        LearningError: unknown id, already decided, protected without confirmation,
            or the saved question is no longer in ``answers.json``.
    """
    row = _pending_row(conn, suggestion_id)
    if row["protected"] and not confirm_protected:
        raise LearningError(
            f"Suggestion {suggestion_id} matches a PROTECTED answer ({row['matched_question']!r}). "
            "Check that the two questions really mean the same, then approve again with --yes-protected."
        )
    entries = _read_answers(answers_path)
    target = next((e for e in entries if str(e.get("question", "")).strip() == row["matched_question"]), None)
    if target is None:
        raise LearningError(f"The saved question {row['matched_question']!r} is not in {answers_path.name} any more.")
    wordings: list[str] = target.setdefault("also_asked_as", [])
    backup: Path | None = None
    if normalize(row["wording"]) not in {normalize(w) for w in wordings}:
        backup = _backup(answers_path)
        wordings.append(row["wording"])
        _write_answers(answers_path, entries)
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO answer_aliases (question, alias) VALUES (?, ?)",
            (row["matched_question"], row["wording"]),
        )
        conn.execute("UPDATE suggested_wordings SET status = 'approved' WHERE id = ?", (suggestion_id,))
    return backup


def reject_wording(conn: sqlite3.Connection, suggestion_id: int) -> None:
    """Mark a suggestion rejected. It will not be suggested again."""
    _pending_row(conn, suggestion_id)
    with conn:
        conn.execute("UPDATE suggested_wordings SET status = 'rejected' WHERE id = ?", (suggestion_id,))


def _pending_row(conn: sqlite3.Connection, suggestion_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM suggested_wordings WHERE id = ?", (suggestion_id,)).fetchone()
    if row is None:
        raise LearningError(f"There is no suggestion with id {suggestion_id}.")
    if row["status"] != "pending":
        raise LearningError(f"Suggestion {suggestion_id} was already {row['status']}.")
    return row


# ---- answers.json, safely -----------------------------------------------------------------


def _read_answers(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise LearningError(f"Cannot read {path.name}: {exc}") from exc
    if not isinstance(data, list):
        raise LearningError(f"{path.name} must be a list of answers.")
    return data


def _backup(path: Path) -> Path:
    """Copy the file to ``answers.backup-<date>-<time>.json`` next to it before changing it."""
    target = path.with_name(f"{path.stem}.backup-{datetime.now():%Y-%m-%d-%H%M%S}{path.suffix}")
    shutil.copy2(path, target)
    return target


def _write_answers(path: Path, entries: list[dict]) -> None:
    """Replace the file in one step: write a temp file, then swap it in."""
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp, path)
