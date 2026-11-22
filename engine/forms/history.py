"""The filled pages history: one ``fills`` row per "Fill this page".

A row says WHAT was done to a page (URL, job, resume, counts, screenshot) and which fields need a look.
It never holds an answer value: values can be your phone or email, so only field LABELS and short notes
are saved, and the notes are scrubbed of your private details first.

Why the ``action_log`` rows are linked afterwards: the filler writes its log rows while it types, before the
``fills`` row exists (we do not know its id yet, and a crash must not leave a half-made "filled" row). So we
note the last log id before the fill, and link every NEW log row to the fill once the row is saved.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import re

from engine import rag
from engine.forms.filler import FillReport
from engine.forms.jobfinder import SHARED_HOSTS

# Names of job boards and application systems. A page that says "Workable" or "Prosple" is not telling you the
# employer, so these are never saved as the company.
JOB_BOARD_NAMES = frozenset(
    {host.split(".")[0] for host in SHARED_HOSTS}
    | {"careerspage", "indeed", "jobstreet", "linkedin", "glassdoor", "kalibrr", "workday", "careers", "jobs", "apply"}
)
MAX_COMPANY_CHARS = 80


def _board_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def pick_company(*candidates: str) -> str:
    """The first usable company name, in the order given; ``""`` when none is reliable (it never guesses).

    A candidate is skipped when it is empty, too long to be a name, or the name of a job board (``Prosple``,
    ``Workable``...). Callers pass the most reliable source first: the company brief (checked against the job post),
    then the page's ``og:site_name``.
    """
    for raw in candidates:
        name = " ".join((raw or "").split())
        if name and len(name) <= MAX_COMPANY_CHARS and _board_key(name) not in JOB_BOARD_NAMES:
            return name
    return ""


def last_log_id(conn: sqlite3.Connection) -> int:
    """The id of the newest ``action_log`` row (0 if the log is empty). Call this BEFORE a fill."""
    return int(conn.execute("SELECT COALESCE(MAX(id), 0) FROM action_log").fetchone()[0])


def private_values(conn: sqlite3.Connection) -> list[str]:
    """Your full name, email, phone and address, exactly as saved, to scrub out of text.

    Whole values only. Name PARTS are left alone on purpose: scrubbing "Mark" would also damage "Marketing".
    """
    row = conn.execute("SELECT full_name, email, phone, address FROM profile WHERE id = 1").fetchone()
    if row is None:
        return []
    return [str(row[key]).strip() for key in ("full_name", "email", "phone", "address") if row[key] and str(row[key]).strip()]


def save_fill(
    conn: sqlite3.Connection,
    report: FillReport,
    *,
    job_title: str = "",
    company: str = "",
    resume_id: str | None = None,
    log_after: int = 0,
) -> int:
    """Save the ``fills`` row (status ``filled``) for a finished fill and link its log rows. Returns the row id.

    Args:
        job_title: the job post's tab title, as seen.
        company: from :func:`pick_company`; empty (saved as NULL) when no reliable name was found.
        resume_id: ``"A"`` / ``"B"``, or ``None`` when no resume was uploaded.
        log_after: ``last_log_id(conn)`` taken before the fill; every newer unlinked log row belongs to this fill.
    """
    private = private_values(conn)
    filled = [r.label for r in report.results if r.outcome == "filled"]  # includes outlined guesses, like filled_count
    flagged = [
        {"label": r.label, "outcome": r.outcome, "note": rag.scrub(r.note, private)[:200]}
        for r in report.results
        if r.flagged
    ]
    shot: Path | None = report.screenshot_path
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO fills (url, job_title, company, resume_id, filled_count, flagged_count,
                               filled_fields, flagged_fields, screenshot_path, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'filled')
            """,
            (
                report.url, job_title or None, company or None, resume_id, report.filled, report.flagged,
                json.dumps(filled, ensure_ascii=False), json.dumps(flagged, ensure_ascii=False),
                str(shot) if shot else None,
            ),
        )
        fill_id = int(cursor.lastrowid or 0)
        conn.execute("UPDATE action_log SET fill_id = ? WHERE id > ? AND fill_id IS NULL", (fill_id, log_after))
    return fill_id


class FillNotFound(Exception):
    """No ``fills`` row has that id (the API answers 404)."""


class FillStatusError(Exception):
    """The status change is not allowed (the API answers 409)."""


def list_fills(conn: sqlite3.Connection, status: str | None = None, limit: int = 100) -> list[sqlite3.Row]:
    """The filled pages history, newest first. ``status`` filters to ``filled``, ``submitted`` or ``abandoned``."""
    if status is None:
        return conn.execute("SELECT * FROM fills ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return conn.execute("SELECT * FROM fills WHERE status = ? ORDER BY id DESC LIMIT ?", (status, limit)).fetchall()


def mark_fill(conn: sqlite3.Connection, fill_id: int, status: str) -> None:
    """Mark a ``filled`` page as ``submitted`` or ``abandoned`` (you decide, never the code on its own).

    Only a row that is still ``filled`` can change, so a submitted page cannot quietly become abandoned.
    ``submitted_at`` is set when you mark it submitted.

    Raises:
        FillNotFound: no such row.
        FillStatusError: ``status`` is not ``submitted`` / ``abandoned``, or the row was already decided.
    """
    if status not in ("submitted", "abandoned"):
        raise FillStatusError(f"A fill can only be marked 'submitted' or 'abandoned', not {status!r}.")
    row = conn.execute("SELECT status FROM fills WHERE id = ?", (fill_id,)).fetchone()
    if row is None:
        raise FillNotFound(f"There is no filled page with id {fill_id}.")
    if row["status"] != "filled":
        raise FillStatusError(f"Filled page {fill_id} is already {row['status']}.")
    with conn:
        conn.execute(
            "UPDATE fills SET status = ?, submitted_at = CASE WHEN ? = 'submitted' THEN datetime('now') END WHERE id = ?",
            (status, status, fill_id),
        )
