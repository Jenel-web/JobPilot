"""The JSON shapes the engine API sends to the dashboard.

Each class below is a contract: the dashboard can rely on exactly these fields. A field that is not listed
here can never leak out by accident, which matters for two of them:

* ``FillOut`` has no answer VALUES, only field labels and counts (a value could be your phone or email).
* ``AnswerOut`` does carry the answer text, because the answer bank editor needs it. That is safe only
  because the API answers this computer alone (see ``engine/api.py``).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["fixed", "open", "protected"]
FillStatus = Literal["filled", "submitted", "abandoned"]
Scope = Literal["any", "city", "remote", "abroad"]


class UnknownOut(BaseModel):
    """A form question with no saved answer yet."""

    id: int
    question: str
    times_seen: int
    page_url: str | None  # the page it was last met on
    field_type: str | None
    options: list[str]  # the choices of a dropdown or radio group, else empty
    first_seen: str
    last_seen: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> UnknownOut:
        return cls(
            id=row["id"], question=row["question_text"], times_seen=row["times_seen"], page_url=row["page_url"],
            field_type=row["field_type"], options=_json_list(row["options"]), first_seen=row["first_seen"],
            last_seen=row["last_seen"],
        )


class WordingOut(BaseModel):
    """A new way a form asked a saved question, waiting for your approval."""

    id: int
    wording: str
    matched_question: str
    score: float
    times_seen: int
    page_url: str | None
    protected: bool  # True: approving needs the extra confirmation
    kind: Kind  # the saved answer's kind, for the chip
    first_seen: str

    @classmethod
    def from_row(cls, row: sqlite3.Row, kind: Kind) -> WordingOut:
        return cls(
            id=row["id"], wording=row["wording"], matched_question=row["matched_question"], score=row["score"],
            times_seen=row["times_seen"], page_url=row["page_url"], protected=bool(row["protected"]), kind=kind,
            first_seen=row["first_seen"],
        )


class AnswerOut(BaseModel):
    """One saved answer, with the other wordings that find it."""

    id: int
    question: str
    answer: str
    kind: Kind
    location_scope: str
    city: str
    times_used: int
    last_used: str | None
    also_asked_as: list[str]

    @classmethod
    def from_row(cls, row: sqlite3.Row, wordings: list[str]) -> AnswerOut:
        return cls(
            id=row["id"], question=row["question"], answer=row["answer"], kind=row["kind"],
            location_scope=row["location_scope"], city=row["city"], times_used=row["times_used"],
            last_used=row["last_used"], also_asked_as=wordings,
        )


class FlaggedField(BaseModel):
    """A field you must look at after a fill: its label, what happened, and a short (scrubbed) note."""

    label: str
    outcome: str
    note: str = ""


class FillOut(BaseModel):
    """One filled page. Field labels and counts only, never the values that were typed."""

    id: int
    url: str
    job_title: str | None
    company: str | None
    resume_id: str | None
    filled_count: int
    flagged_count: int
    filled_fields: list[str]
    flagged_fields: list[FlaggedField]
    screenshot_path: str | None
    status: FillStatus
    filled_at: str
    submitted_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> FillOut:
        flagged = []
        for item in _json_list(row["flagged_fields"]):
            if isinstance(item, dict):
                flagged.append(FlaggedField(label=str(item.get("label", "")), outcome=str(item.get("outcome", "")), note=str(item.get("note", ""))))
        return cls(
            id=row["id"], url=row["url"], job_title=row["job_title"], company=row["company"], resume_id=row["resume_id"],
            filled_count=row["filled_count"], flagged_count=row["flagged_count"],
            filled_fields=[str(x) for x in _json_list(row["filled_fields"])], flagged_fields=flagged,
            screenshot_path=row["screenshot_path"], status=row["status"], filled_at=row["filled_at"],
            submitted_at=row["submitted_at"],
        )


def _json_list(text: str | None) -> list:
    """A JSON list stored in a text column; anything broken or missing becomes an empty list."""
    try:
        value = json.loads(text or "[]")
    except ValueError:
        return []
    return value if isinstance(value, list) else []


# ---- what you send (request bodies) ---------------------------------------------------------------


class UnknownAnswerIn(BaseModel):
    """Your answer to an unknown question. ``kind`` has no default: you choose it on purpose."""

    answer: str = Field(min_length=1)
    kind: Kind
    scope: Scope = "any"
    city: str = ""


class ApproveIn(BaseModel):
    """Approving a wording. ``confirm_protected`` must be true when the saved answer is protected."""

    confirm_protected: bool = False


class AnswerIn(BaseModel):
    """A new answer for the answer bank."""

    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    kind: Kind
    scope: Scope = "any"
    city: str = ""


class AnswerUpdateIn(BaseModel):
    """New values for an existing answer (the question text itself does not change).

    Everything but ``city`` and ``confirm_protected`` is required, so a missing field can never silently reset it.
    """

    answer: str = Field(min_length=1)
    kind: Kind
    scope: Scope
    city: str = ""
    confirm_protected: bool = False


class FillStatusIn(BaseModel):
    """You decide what happened to a filled page."""

    status: Literal["submitted", "abandoned"]


# ---- what comes back after a change ---------------------------------------------------------------


class ChangeInfo(BaseModel):
    """What happened behind a change. A failed re-index is a warning, not an error: your change is saved."""

    backup: str | None = None  # the copy of answers.json made before the change (None: the file did not change)
    reindexed: bool = False  # False for a change that needs no re-index (a rejected wording)
    warning: str | None = None


class UnknownAnswerOut(ChangeInfo):
    unknown_id: int
    answer: AnswerOut | None


class DecisionOut(ChangeInfo):
    """A wording you approved or rejected."""

    id: int
    wording: str
    matched_question: str
    status: Literal["approved", "rejected"]


class AnswerChangeOut(ChangeInfo):
    """An answer you added or edited, as it is now."""

    answer: AnswerOut


class AnswerDeleteOut(ChangeInfo):
    deleted_id: int
    question: str
    removed_wordings: int  # other wordings that went with it
