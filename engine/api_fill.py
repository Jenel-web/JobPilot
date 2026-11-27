"""The "Fill this page" endpoints (stage 4.4e): ``POST /fill`` starts a fill, ``GET /fill/{job_id}`` reports on it.

A fill takes minutes (every field waits 1-4 seconds), so ``POST /fill`` does not wait. It checks that a fill can
start, starts it in a background thread, and answers at once with a job id. The screen then asks
``GET /fill/{job_id}`` every second or two: ``running``, then ``done`` (with the summary) or ``error``.

What runs is exactly what ``python -m engine.cli forms fill`` runs: ``fill_current_page()`` in
``engine/forms/orchestrator.py``. Nothing here decides anything about the form, and nothing here can click:
the only thing that touches the page is the filler, which only types into fields. **Never submits.**

Why a thread of its own for each fill? Playwright's sync API cannot run inside the web server's event loop, and
its objects must stay in the thread that made them. So the thread opens its own connection to the bot's browser
and its own database connection, and closes both when it is done.

Why one fill at a time? There is one bot browser. Two fills would type into the same window at once.
"""

from __future__ import annotations

import socket
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from playwright.sync_api import Page

from engine import db, learning, rag, safety
from engine.ai import AIError
from engine.api_deps import get_conn, get_settings
from engine.api_models import FillIn, FillJobOut, FillPostOut, FillResultOut, FlaggedField, TabOut
from engine.forms.browser import CDP_PORT
from engine.forms.history import private_values
from engine.forms.jobfinder import SOURCE_LABELS, _target_id, post_from_pasted, post_from_tab_url
from engine.forms.orchestrator import FillOutcome, fill_current_page
from engine.forms.reader import connect_to_bot_browser, find_current_page
from engine.matcher import PickError
from engine.settings import ROOT, Settings

MAX_JOBS = 20  # finished jobs kept in memory; older ones are forgotten (their history rows stay in the database)

router = APIRouter()


# ---- errors the endpoints can give -------------------------------------------------------------------


class FillBusy(Exception):
    """A fill is already running (the API answers 409)."""


class BrowserNotOpen(Exception):
    """The bot's browser is not running (the API answers 503)."""


class IndexNotReady(Exception):
    """The search index is empty or was built in another run mode (the API answers 409)."""


class AIUnavailable(Exception):
    """The embedding model cannot be reached, for example Ollama is not running (the API answers 503)."""


# ---- the checks done before a job starts ---------------------------------------------------------------


def browser_is_open() -> bool:
    """Is something listening on the bot browser's debugging port (127.0.0.1 only)? A quick, harmless test."""
    try:
        with socket.create_connection(("127.0.0.1", CDP_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def check_ready(conn: sqlite3.Connection, settings: Settings) -> None:
    """Stop early, with a clear message, if the search index cannot answer.

    Without this a fill would "work" but leave most fields empty (same check as the command line).

    Raises:
        IndexNotReady: the index is empty or was built in a different run mode.
        AIUnavailable: the embedding model cannot be reached.
    """
    try:
        rag.retrieve(conn, "ready check", 1, settings=settings)
    except rag.RagError as exc:
        raise IndexNotReady(f"{exc} Nothing was filled. Run mode is {settings.run_mode!r}: the index must be built in the same mode.") from exc
    except AIError as exc:
        raise AIUnavailable(f"The search model cannot be reached ({exc}). Is Ollama running?") from exc


# ---- the work of one fill ---------------------------------------------------------------------------------


def to_result(conn: sqlite3.Connection, outcome: FillOutcome) -> FillResultOut:
    """Turn the orchestrator's outcome into the API shape. Labels and counts only; notes are scrubbed of your details."""
    report = outcome.report
    private = private_values(conn)
    flagged = (
        [FlaggedField(label=r.label, outcome=r.outcome, note=rag.scrub(r.note, private)[:200]) for r in report.results if r.flagged]
        if report
        else []
    )
    post = outcome.post
    return FillResultOut(
        url=outcome.url,
        fill_id=outcome.fill_id,
        filled=report.filled if report else 0,
        needs_you=report.needs_you if report else 0,
        failed=report.failed if report else 0,
        flagged=report.flagged if report else 0,
        flagged_fields=flagged,
        screenshot_path=str(report.screenshot_path) if report and report.screenshot_path else None,
        post=FillPostOut(label=post.label, source=SOURCE_LABELS[post.source], tab_title=post.tab_title, tab_url=post.tab_url) if post else None,
        tabs=[TabOut(index=t.index, title=t.title, url=t.url) for t in outcome.tabs],
        resume_id=outcome.resume_id,
        resume_reason=outcome.resume_reason,
        unknown_ids=outcome.unknown_ids,
        messages=outcome.messages,
    )


def perform_fill(
    conn: sqlite3.Connection,
    page: Page,
    settings: Settings,
    request: FillIn,
    screenshot_path: Path,
    sleep: Callable[[float], None] = time.sleep,
) -> FillResultOut:
    """Fill ``page`` and stop (the same call the command line makes). Always saves the history row and unknown questions."""
    post = None
    if request.post_text:
        post = post_from_pasted(request.post_text)
    elif request.post_tab_url:
        post = post_from_tab_url(page, request.post_tab_url)
        if post is None:
            raise RuntimeError("The tab you picked as the job post is closed or changed. Pick it again.")
    outcome = fill_current_page(
        conn, page, settings=settings, post=post, resume_id=request.resume, save=True, sleep=sleep,
        screenshot_path=screenshot_path, no_resume=request.no_resume,
    )
    return to_result(conn, outcome)


def _pick_page(browser: object, tab: str | None) -> Page:
    """The tab to fill: the one whose address contains ``tab``, else the page you are looking at."""
    if not tab:
        return find_current_page(browser)
    wanted = tab.lower()
    matches = [pg for ctx in browser.contexts for pg in ctx.pages if wanted in pg.url.lower()]  # type: ignore[attr-defined]
    if not matches:
        raise RuntimeError(f"No open tab has {tab!r} in its address.")
    return matches[0]


def tab_id(page: Page) -> str:
    """Chrome's own id for the tab (read-only); "" if it cannot be read."""
    try:
        return _target_id(page)
    except Exception:  # noqa: BLE001 - no id simply means no passive submit detection for this fill
        return ""


def bot_browser_runner(db_path: Path | str, settings: Settings, request: FillIn) -> FillResultOut:
    """The real job: attach to the bot's browser, pick the tab, fill it. Runs in the job's own thread.

    Raises:
        RuntimeError: the bot's browser is not open, or no tab matches.
        safety.SafetyError: this page may not be filled in the current run mode.
    """
    from playwright.sync_api import sync_playwright  # imported here: tests that stub the runner need no browser

    conn = db.connect(db_path)
    try:
        with sync_playwright() as p:
            page = _pick_page(connect_to_bot_browser(p), request.tab)
            shot = ROOT / "data" / "screenshots" / f"fill-{datetime.now():%Y%m%d-%H%M%S}.png"
            result = perform_fill(conn, page, settings, request, shot)
            result.target_id = tab_id(page)  # so the submit watcher can find this tab again, even after it navigates
            return result
    finally:
        conn.close()


# ---- jobs -----------------------------------------------------------------------------------------------------


@dataclass
class Job:
    """One fill. ``status`` only ever goes running -> done, or running -> error."""

    id: str
    started_at: str
    status: str = "running"
    finished_at: str | None = None
    result: FillResultOut | None = None
    error: str | None = None


def describe_error(exc: Exception) -> str:
    """A plain sentence for the screen. Errors we expect keep their own message; anything else is generic."""
    if isinstance(exc, (RuntimeError, ValueError, OSError, safety.SafetyError, PickError, AIError, rag.RagError, sqlite3.Error)):
        return str(exc) or type(exc).__name__
    return f"The fill stopped unexpectedly ({type(exc).__name__}). Check the page: nothing was submitted."


class JobManager:
    """Runs fills one at a time in background threads and remembers the last :data:`MAX_JOBS`."""

    def __init__(self, max_jobs: int = MAX_JOBS) -> None:
        self._max = max_jobs
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._lock = threading.Lock()
        self._busy = False

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    @property
    def running_id(self) -> str | None:
        """The id of the fill that is running now, or None."""
        with self._lock:
            return next((k for k, j in self._jobs.items() if j.status == "running"), None)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def start(self, work: Callable[[], FillResultOut]) -> Job:
        """Start ``work`` in a background thread.

        Raises:
            FillBusy: another fill is still running.
        """
        with self._lock:
            if self._busy:
                raise FillBusy("A fill is already running. Wait for it to finish.")
            job = Job(id=uuid4().hex[:12], started_at=f"{datetime.now():%Y-%m-%d %H:%M:%S}")
            self._busy = True
            self._jobs[job.id] = job
            while len(self._jobs) > self._max:  # forget the oldest FINISHED job; a running one is never dropped
                oldest = next((k for k, j in self._jobs.items() if j.status != "running"), None)
                if oldest is None:
                    break
                del self._jobs[oldest]
        threading.Thread(target=self._run, args=(job, work), name=f"fill-{job.id}", daemon=True).start()
        return job

    def _run(self, job: Job, work: Callable[[], FillResultOut]) -> None:
        result: FillResultOut | None = None
        error: str | None = None
        try:
            result = work()
        except Exception as exc:  # noqa: BLE001 - a job must always end as done or error, whatever went wrong
            error = describe_error(exc)
        except BaseException:  # the thread is being torn down: still leave a truthful state behind
            error = "The fill was interrupted."
            raise
        finally:
            with self._lock:
                job.result, job.error = result, error
                job.status = "done" if error is None else "error"
                job.finished_at = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
                self._busy = False


def _log_failure(db_path: Path | str, exc: Exception) -> None:
    """Rule 7: log the failure. Only the error's type is stored, never its text (it might mention a page's content)."""
    try:
        conn = db.connect(db_path)
        try:
            safety.log_action(conn, "error", "fill job", f"fill failed: {type(exc).__name__}")
        finally:
            conn.close()
    except sqlite3.Error:
        pass  # failing to log must not hide the real error


def _to_out(job: Job) -> FillJobOut:
    return FillJobOut(
        job_id=job.id, status=job.status, started_at=job.started_at, finished_at=job.finished_at,  # type: ignore[arg-type]
        result=job.result, error=job.error,
    )


# ---- endpoints --------------------------------------------------------------------------------------------------


@router.post("/fill", status_code=202)
def start_fill(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_conn)],
    settings: Annotated[Settings, Depends(get_settings)],
    body: FillIn | None = None,
) -> FillJobOut:
    """Start filling the page in the bot's browser, then stop before Submit. Answers at once with a job id."""
    body = body or FillIn()
    jobs: JobManager = request.app.state.fill_jobs
    if jobs.busy:
        raise FillBusy("A fill is already running. Wait for it to finish.")
    if not browser_is_open():
        raise BrowserNotOpen("The bot's browser is not open. Run: python -m engine.cli browser open")
    check_ready(conn, settings)
    db_path, runner = request.app.state.db_path, request.app.state.fill_runner

    watcher = request.app.state.submit_watcher

    def work() -> FillResultOut:
        try:
            result = runner(db_path, settings, body)
        except Exception as exc:
            _log_failure(db_path, exc)
            raise
        if result.fill_id is not None and result.target_id:
            watcher.watch(result.fill_id, result.target_id, result.url)  # read-only: offers "Looks submitted. Mark it?"
        return result

    return _to_out(jobs.start(work))


@router.get("/fill/{job_id}")
def fill_status(job_id: str, request: Request) -> FillJobOut:
    """How is this fill going? ``running``, ``done`` (with the summary) or ``error`` (with the reason)."""
    job = request.app.state.fill_jobs.get(job_id)
    if job is None:
        raise learning.NotFound(f"There is no fill job {job_id!r} (the engine may have restarted; see the filled pages history).")
    return _to_out(job)


def install_fill_handlers(app: FastAPI) -> None:
    """HTTP answers for the fill errors: 409 busy / index not ready, 503 browser closed / model unreachable."""

    def respond(status: int, code: str):  # type: ignore[no-untyped-def]
        async def handler(_request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse({"code": code, "detail": str(exc)}, status_code=status)

        return handler

    for exc_type, status, code in (
        (FillBusy, 409, "fill_running"),
        (IndexNotReady, 409, "index_not_ready"),
        (BrowserNotOpen, 503, "browser_closed"),
        (AIUnavailable, 503, "ai_unavailable"),
    ):
        app.add_exception_handler(exc_type, respond(status, code))
