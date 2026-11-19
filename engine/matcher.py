"""Resume picker (v0 Phase 3): which resume, A or B, fits a job post better?

How it works, step by step:
  1. Empty post -> no pick, and no AI call.
  2. Search the index for the resume chunks closest to the post (``rag.retrieve``, sources=("resume",)),
     then keep the best few chunks of EACH resume.
  3. Send the post and those chunks to ``ask_ai("resume_pick", ...)``. Resumes are labelled only
     "Resume A" / "Resume B": file names and labels never reach the AI, so they cannot sway the pick.
  4. Return a ``ResumePick``: the resume, a reason, and the resume lines that back it up.

Privacy (CLAUDE.md rule 3): resume chunks are already scrubbed when indexed, and the post is scrubbed
again here (a post can contain a recruiter's email or phone).

The BM25 pre-filter and job scoring arrive in v1.
"""

from __future__ import annotations

import re
import sqlite3

from engine import ai, rag
from engine.ai import AIError, ResumePick
from engine.settings import ROOT, Settings

PROMPT_PATH = ROOT / "prompts" / "resume.md"
CHUNKS_PER_RESUME = 3
MAX_POST_CHARS = 3000  # the embedder and the prompt both have limited room
MAX_CHUNK_CHARS = 700


class PickError(Exception):
    """The picker could not run (message says why and what to do)."""


def load_prompt(section: str, **values: str) -> str:
    """Read one ``## SECTION`` of ``prompts/resume.md`` and fill its ``{{placeholders}}`` in one pass."""
    try:
        text = PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise PickError(f"Cannot read {PROMPT_PATH.name}: {exc}") from exc
    sections = dict(re.findall(r"^## (\w+)\s*\n(.*?)(?=^## |\Z)", text, flags=re.MULTILINE | re.DOTALL))
    if section not in sections:
        raise PickError(f"{PROMPT_PATH.name} has no section {section!r}")
    return re.sub(r"\{\{(\w+)\}\}", lambda m: values[m.group(1)], sections[section]).strip()


def _best_chunks_per_resume(
    conn: sqlite3.Connection, post: str, settings: Settings | None
) -> dict[str, list[str]]:
    """The closest chunks of each resume, best first, keyed by resume id (``"A"``, ``"B"``)."""
    rag.init_rag(conn)  # makes sure the index tables exist
    total = conn.execute("SELECT count(*) FROM chunks WHERE source = 'resume'").fetchone()[0]
    if total == 0:
        raise PickError("No resume is indexed. Run: python -m engine.cli load, then rag reindex")
    try:
        hits = rag.retrieve(conn, post, total, sources=("resume",), settings=settings)
    except rag.RagError as exc:
        raise PickError(str(exc)) from exc
    grouped: dict[str, list[str]] = {}
    for hit in hits:  # hits are best first; a ref looks like "A#2"
        chunks = grouped.setdefault(hit.ref.split("#")[0], [])
        if len(chunks) < CHUNKS_PER_RESUME:
            chunks.append(hit.text[:MAX_CHUNK_CHARS])
    return grouped


def pick_resume(conn: sqlite3.Connection, job_text: str, settings: Settings | None = None) -> ResumePick | None:
    """Pick resume A or B for a job post, judged only by what each resume says.

    Args:
        job_text: the text of the job post (not a file name).

    Returns:
        A ``ResumePick`` (resume, reason, evidence), or ``None`` when the post is empty
        ("no job post, no pick"; the AI is not called).

    Raises:
        PickError: a resume is missing from the index, or the AI gave no valid answer.
    """
    post = rag.scrub(job_text or "").strip()
    if not post:
        return None
    post = post[:MAX_POST_CHARS]

    grouped = _best_chunks_per_resume(conn, post, settings)
    if len(grouped) < 2:
        raise PickError(f"Need two indexed resumes, found {sorted(grouped)}. Run: python -m engine.cli load")
    excerpts = "\n\n".join(
        f"Resume {rid}:\n" + "\n".join(f"- {c}" for c in chunks) for rid, chunks in sorted(grouped.items())
    )
    prompt = load_prompt("PICK", post=post, excerpts=excerpts)
    try:
        return ResumePick(**ai.ask_ai("resume_pick", prompt, settings=settings))
    except AIError as exc:
        raise PickError(f"The AI gave no usable pick: {exc}") from exc
