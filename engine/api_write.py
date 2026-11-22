"""The endpoints that CHANGE things (stage 4.4d). Reads are in ``engine/api.py``.

Every change to ``answers.json`` follows the same order, so you can reason about a failure at any step:

    1. check the request (is it valid? is the id real? is a protected answer confirmed?)   -> nothing changed yet
    2. back up ``answers.json`` and write the change into it (``engine/answers_file.py``)  -> the file is the truth
    3. update the database rows                                                             -> mirrors the file
    4. rebuild the search index                                                             -> may fail; the change stays

Step 4 failing (for example Ollama is not running) is reported as a warning in the response, never as an
error, and never undoes steps 2 and 3. Run ``python -m engine.cli rag reindex`` later to catch up.

Two safety rules live here:

* **Protected answers need ``confirm_protected``** to approve a wording for them, edit them or delete them.
  Without it the answer is a 409 with ``"code": "protected_needs_confirmation"`` and NOTHING changes.
* **Nothing here submits anything.** The only thing that changes about a filled page is the label you give it.

All of these run one at a time (``get_write_lock``) and only ever touch the ``answers.json`` the app was given.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from engine import answers_file, learning
from engine.api_deps import get_answers_path, get_conn, get_settings, get_write_lock
from engine.api_models import (
    AnswerChangeOut,
    AnswerDeleteOut,
    AnswerIn,
    AnswerOut,
    AnswerUpdateIn,
    ApproveIn,
    ChangeInfo,
    DecisionOut,
    FillOut,
    FillStatusIn,
    UnknownAnswerIn,
    UnknownAnswerOut,
)
from engine.forms import history
from engine.profile import load_answers
from engine.settings import Settings

router = APIRouter(dependencies=[Depends(get_write_lock)])

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
Config = Annotated[Settings, Depends(get_settings)]
AnswersPath = Annotated[Path, Depends(get_answers_path)]


# ---- helpers ------------------------------------------------------------------------------------


def _finish(conn: sqlite3.Connection, settings: Settings, path: Path, backup: Path | None) -> ChangeInfo:
    """Steps 3 and 4: mirror the file into the database, then rebuild the index (a failure there is a warning)."""
    load_answers(conn, path)
    warning = learning.reindex_after_change(conn, settings, path)
    return ChangeInfo(backup=str(backup) if backup else None, reindexed=warning is None, warning=warning)


def _answer_row(conn: sqlite3.Connection, answer_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM answers WHERE id = ?", (answer_id,)).fetchone()
    if row is None:
        raise learning.NotFound(f"There is no saved answer with id {answer_id}.")
    return row


def _answer_out(conn: sqlite3.Connection, answer_id: int | None) -> AnswerOut | None:
    if answer_id is None:
        return None
    row = conn.execute("SELECT * FROM answers WHERE id = ?", (answer_id,)).fetchone()
    if row is None:
        return None
    aliases = [r["alias"] for r in conn.execute("SELECT alias FROM answer_aliases WHERE question = ? ORDER BY alias", (row["question"],))]
    return AnswerOut.from_row(row, aliases)


def _require_confirmation(row: sqlite3.Row, confirmed: bool, action: str) -> None:
    """Editing or deleting a protected answer needs the same extra step as approving a wording for it."""
    if row["kind"] == "protected" and not confirmed:
        raise learning.ProtectedNotConfirmed(
            f"{row['question']!r} is a PROTECTED answer. Check that you really want to {action} it, then send confirm_protected."
        )


def _alias_count(conn: sqlite3.Connection, question: str) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM answer_aliases WHERE question = ?", (question,)).fetchone()[0])


# ---- unknown questions ----------------------------------------------------------------------------


@router.post("/unknown/{unknown_id}/answer")
def answer_unknown(unknown_id: int, body: UnknownAnswerIn, conn: Conn, settings: Config, path: AnswersPath) -> UnknownAnswerOut:
    """Answer a question the bot could not answer: it goes into the answer bank, so the next fill uses it."""
    backup = learning.answer_unknown(
        conn, unknown_id, answer=body.answer, kind=body.kind, scope=body.scope, city=body.city, answers_path=path
    )
    info = _finish(conn, settings, path, backup)
    answer_id = conn.execute("SELECT answer_id FROM unknown_questions WHERE id = ?", (unknown_id,)).fetchone()["answer_id"]
    return UnknownAnswerOut(unknown_id=unknown_id, answer=_answer_out(conn, answer_id), **info.model_dump())


# ---- suggested wordings ----------------------------------------------------------------------------


@router.post("/wordings/{wording_id}/approve")
def approve_wording(
    wording_id: int, conn: Conn, settings: Config, path: AnswersPath, body: ApproveIn | None = None
) -> DecisionOut:
    """Approve a wording: it is added to the saved answer's ``also_asked_as``. Protected answers need ``confirm_protected``."""
    body = body or ApproveIn()
    backup = learning.approve_wording(conn, wording_id, confirm_protected=body.confirm_protected, answers_path=path)
    info = _finish(conn, settings, path, backup)
    row = conn.execute("SELECT wording, matched_question FROM suggested_wordings WHERE id = ?", (wording_id,)).fetchone()
    return DecisionOut(id=wording_id, wording=row["wording"], matched_question=row["matched_question"], status="approved", **info.model_dump())


@router.post("/wordings/{wording_id}/reject")
def reject_wording(wording_id: int, conn: Conn) -> DecisionOut:
    """Reject a wording: it never comes back as a suggestion. ``answers.json`` is not touched."""
    learning.reject_wording(conn, wording_id)
    row = conn.execute("SELECT wording, matched_question FROM suggested_wordings WHERE id = ?", (wording_id,)).fetchone()
    return DecisionOut(id=wording_id, wording=row["wording"], matched_question=row["matched_question"], status="rejected")


# ---- the answer bank --------------------------------------------------------------------------------


@router.post("/answers", status_code=201)
def create_answer(body: AnswerIn, conn: Conn, settings: Config, path: AnswersPath) -> AnswerChangeOut:
    """Add an answer. If one with the same question and scope already exists it is refused (409): edit it instead."""
    try:
        backup = answers_file.add_entry(path, question=body.question, answer=body.answer, kind=body.kind, scope=body.scope, city=body.city)
    except answers_file.InvalidEntry as exc:
        raise learning.InvalidAnswer(str(exc)) from exc
    info = _finish(conn, settings, path, backup)
    city = body.city.strip() if body.scope == "city" else ""
    row = conn.execute(
        "SELECT id FROM answers WHERE question = ? AND location_scope = ? AND city = ?", (body.question.strip(), body.scope, city)
    ).fetchone()
    return AnswerChangeOut(answer=_answer_out(conn, row["id"]), **info.model_dump())  # type: ignore[arg-type]


@router.put("/answers/{answer_id}")
def update_answer(answer_id: int, body: AnswerUpdateIn, conn: Conn, settings: Config, path: AnswersPath) -> AnswerChangeOut:
    """Edit an answer's text, kind, scope or city. A protected answer needs ``confirm_protected``."""
    row = _answer_row(conn, answer_id)
    _require_confirmation(row, body.confirm_protected, "change")
    try:
        backup = answers_file.update_entry(
            path, question=row["question"], old_scope=row["location_scope"], old_city=row["city"],
            answer=body.answer, kind=body.kind, scope=body.scope, city=body.city,
        )
    except answers_file.InvalidEntry as exc:
        raise learning.InvalidAnswer(str(exc)) from exc
    with conn:  # update the SAME row, so its id and times_used survive a change of scope or city
        conn.execute(
            "UPDATE answers SET answer = ?, kind = ?, location_scope = ?, city = ? WHERE id = ?",
            (body.answer, body.kind, body.scope, body.city.strip() if body.scope == "city" else "", answer_id),
        )
    info = _finish(conn, settings, path, backup)
    return AnswerChangeOut(answer=_answer_out(conn, answer_id), **info.model_dump())  # type: ignore[arg-type]


@router.delete("/answers/{answer_id}")
def delete_answer(
    answer_id: int, conn: Conn, settings: Config, path: AnswersPath, confirm_protected: bool = False
) -> AnswerDeleteOut:
    """Delete an answer (and with it any wordings only it had). A protected answer needs ``?confirm_protected=true``."""
    row = _answer_row(conn, answer_id)
    _require_confirmation(row, confirm_protected, "delete")
    wordings_before = _alias_count(conn, row["question"])
    backup = answers_file.delete_entry(path, question=row["question"], scope=row["location_scope"], city=row["city"])
    with conn:  # an answered unknown question may point at this row; let it go first (foreign key)
        conn.execute("UPDATE unknown_questions SET answer_id = NULL WHERE answer_id = ?", (answer_id,))
        conn.execute("DELETE FROM answers WHERE id = ?", (answer_id,))
    info = _finish(conn, settings, path, backup)  # also rebuilds the wordings from the file, so the lost ones vanish
    removed = wordings_before - _alias_count(conn, row["question"])
    return AnswerDeleteOut(deleted_id=answer_id, question=row["question"], removed_wordings=max(removed, 0), **info.model_dump())


# ---- filled pages -------------------------------------------------------------------------------------


@router.post("/fills/{fill_id}/status")
def set_fill_status(fill_id: int, body: FillStatusIn, conn: Conn) -> FillOut:
    """Say what happened to a filled page: ``submitted`` or ``abandoned``. Only you decide; only a ``filled`` row can change."""
    history.mark_fill(conn, fill_id, body.status)
    return FillOut.from_row(conn.execute("SELECT * FROM fills WHERE id = ?", (fill_id,)).fetchone())


# ---- errors -> HTTP answers -----------------------------------------------------------------------------


def install_error_handlers(app: FastAPI) -> None:
    """Turn the engine's plain errors into clear HTTP answers: ``{"code": ..., "detail": ...}``.

    404 = no such id, 409 = not allowed in the current state (including the protected confirmation),
    422 = the request itself is invalid, 500 = the answers file is unreadable.
    """

    def respond(status: int, code: str):  # type: ignore[no-untyped-def]
        async def handler(_request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse({"code": code, "detail": str(exc)}, status_code=status)

        return handler

    table: list[tuple[type[Exception], int, str]] = [
        (learning.NotFound, 404, "not_found"),
        (history.FillNotFound, 404, "not_found"),
        (answers_file.EntryNotFound, 404, "not_found"),
        (learning.ProtectedNotConfirmed, 409, "protected_needs_confirmation"),
        (learning.AlreadyDecided, 409, "already_decided"),
        (answers_file.EntryExists, 409, "already_exists"),
        (history.FillStatusError, 409, "not_allowed"),
        (learning.InvalidAnswer, 422, "invalid"),
        (answers_file.InvalidEntry, 422, "invalid"),
        (learning.LearningError, 409, "cannot_apply"),
        (answers_file.AnswersFileError, 500, "answers_file_error"),
    ]
    for exc_type, status, code in table:
        app.add_exception_handler(exc_type, respond(status, code))
