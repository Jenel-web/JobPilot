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

from engine import rag
from engine.forms.filler import FillReport


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
        job_title: the job post's tab title, as seen. ``company`` stays empty until a reliable way to read it exists.
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
