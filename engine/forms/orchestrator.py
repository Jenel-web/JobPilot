"""Fill this page: the whole chain in one function, then STOP.

    reader -> job post finder -> answer engine -> resume picker -> filler -> screenshot -> ``fills`` row

Each piece already exists and is tested on its own; this module only runs them in order and keeps the
bookkeeping (which job post was used, which resume, what the history row says). It decides nothing itself.

It never clicks Submit: the only thing that touches the page is :func:`engine.forms.filler.fill_page`,
which only types into inputs, selects and textareas.

Order matters:
  1. ``safety.check("fill")`` first, before anything is read or any AI is asked.
  2. No form fields on the page (you are on the job page, not the form)? Stop. Nothing is saved.
  3. The job post: your ``--post`` text if you gave one, else the finder (form page, opener tab, same-site tab).
     No job post means no resume pick, no upload, and the resume field stays flagged.
  4. The post text is scrubbed of your name, email, phone and address before it goes anywhere (rule 3).
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from engine import matcher, rag, safety
from engine.ai import AIError
from engine.forms import drafting, jobpost
from engine.forms.answers import answer_form
from engine.forms.filler import DELAY_RANGE, FillReport, ResumeFile, fill_page, load_resume_file
from engine.forms.history import last_log_id, pick_company, private_values, save_fill
from engine.forms.jobfinder import JobPost, TabInfo, find_job_post, job_text_of
from engine.forms.reader import read_fields
from engine.settings import Settings


@dataclass
class FillOutcome:
    """What one "Fill this page" did, for the screen or the CLI to show."""

    url: str
    report: FillReport | None = None  # None: nothing was filled (see ``messages``)
    fill_id: int | None = None  # the ``fills`` row, when one was saved
    post: JobPost | None = None  # the job post that was used (None = none found)
    tabs: list[TabInfo] = field(default_factory=list)  # your other tabs, for "Which one is the job post?"
    resume_id: str | None = None
    resume_reason: str = ""
    company: str = ""  # the employer's name for the history row (empty when no reliable name was found)
    unknown_ids: list[int] = field(default_factory=list)  # questions with no saved answer (already on the list)
    messages: list[str] = field(default_factory=list)  # plain sentences for you: what was skipped and why


def job_location(job_text: str | None) -> tuple[str, str]:
    """``(job_scope, job_city)`` for the answer bank, from the job post's text.

    Remote -> ``("remote", "")``. A Metro Manila place -> ``("city", that place)``. Anything else, or no
    post at all, -> ``("any", "")`` so the general saved answers are used. Saved answers only match a city
    exactly; when none does, the lookup falls back to the general answer, so a miss is safe.
    """
    if not job_text:
        return "any", ""
    location = jobpost.read_job_location(job_text)
    if location.kind == "remote":
        return "remote", ""
    if location.kind == "metro_manila":
        return "city", location.evidence
    return "any", ""


def _choose_resume(
    conn: sqlite3.Connection, job_text: str | None, resume_id: str | None, settings: Settings | None, outcome: FillOutcome
) -> ResumeFile | None:
    """The resume to upload: the one you asked for, else the picker's choice from the post. None = upload nothing."""
    if resume_id is None and job_text:
        try:
            pick = matcher.pick_resume(conn, job_text, settings)
        except (matcher.PickError, AIError) as exc:
            outcome.messages.append(f"Resume not picked, so none is uploaded: {exc}")
            return None
        if pick is not None:
            resume_id, outcome.resume_reason = pick.resume, pick.reason
    if resume_id is None:
        if not job_text:
            outcome.messages.append("No job post found, so no resume was picked or uploaded. Open the job post or paste it, then fill again.")
        return None
    try:
        file = load_resume_file(conn, resume_id)
    except ValueError as exc:
        outcome.messages.append(f"Resume {resume_id} not uploaded: {exc}")
        return None
    outcome.resume_id = resume_id.upper()
    return file


def _site_name(page: Page) -> str:
    """The page's ``og:site_name`` (a fallback company name), or "". Read-only; any page problem gives ""."""
    try:
        return str(
            page.evaluate("document.querySelector('meta[property=\"og:site_name\"]')?.content || ''")
        ).strip()
    except PlaywrightError:
        return ""


def fill_current_page(
    conn: sqlite3.Connection,
    page: Page,
    *,
    settings: Settings | None = None,
    post: JobPost | None = None,
    resume_id: str | None = None,
    save: bool = True,
    sleep: Callable[[float], None] = time.sleep,
    delay_range: tuple[float, float] = DELAY_RANGE,
    screenshot_path: Path | None = None,
) -> FillOutcome:
    """Run the whole fill on ``page`` and stop before Submit.

    Args:
        post: a job post you chose or pasted. Without it the finder looks through your open tabs.
        resume_id: ``"A"`` or ``"B"`` to skip the picker. Without it, the picker chooses from the job post.
        save: False for a preview run: no unknown questions, wordings or ``fills`` row are saved.
        sleep, delay_range: the pause between actions. Tests pass a fake ``sleep``.

    Returns:
        A :class:`FillOutcome`. ``report`` is ``None`` when the page has no form fields.

    Raises:
        safety.SafetyError: this page may not be filled in the current mode.
    """
    safety.check("fill", page.url, settings=settings)
    outcome = FillOutcome(url=page.url)

    fields = read_fields(page)
    if not fields:
        outcome.messages.append("No form fields on this page. Open the application form tab and fill again.")
        safety.log_action(conn, "read", page.url, "fill stopped: no form fields")
        return outcome

    if post is None:
        found = find_job_post(page, settings=settings, conn=conn)
        post, outcome.tabs = found.post, found.tabs
    outcome.post = post
    job_text = job_text_of(post)
    if job_text is not None:  # rule 3: nothing personal goes to the AI, even if the page showed it
        job_text = rag.scrub(job_text, private_values(conn)).strip() or None
    if job_text is None:
        outcome.post = None

    resume = _choose_resume(conn, job_text, resume_id, settings, outcome)
    scope, city = job_location(job_text)
    # The company brief is read from the post ONCE: it names the company for the history row, and company questions
    # on the form reuse it (answer_form gets it through ``brief_cache``). No post means no brief and no AI call.
    briefs: dict[str, drafting.CompanyBrief | None] = {}
    if job_text:
        briefs[job_text] = drafting.build_company_brief(job_text, settings)
    brief = briefs.get(job_text or "")
    outcome.company = pick_company(brief.company if brief else "", _site_name(page))
    answers = answer_form(
        conn, fields, job_scope=scope, job_city=city, page_url=page.url, settings=settings, job_text=job_text, record=save,
        brief_cache=briefs,
    )
    outcome.unknown_ids = [a.unknown_id for a in answers if a.unknown_id is not None]

    log_after = last_log_id(conn)
    outcome.report = fill_page(
        page, fields, answers, conn=conn, resume=resume, settings=settings, sleep=sleep, delay_range=delay_range,
        screenshot_path=screenshot_path,
    )
    if save:
        title = outcome.post.tab_title if outcome.post else ""
        outcome.fill_id = save_fill(
            conn, outcome.report, job_title=title, company=outcome.company, resume_id=outcome.resume_id, log_after=log_after
        )
    return outcome
