"""Read-only browser endpoints for the controls page (stage 4.5): status line, job post preview, screenshots.

* ``GET /status``: is the bot's browser open, which page are you looking at, is a fill running? The dashboard asks
  every few seconds for its status line ("Browser ready · current page: acme.com/careers/apply").
* ``GET /jobpost``: the job post a fill WOULD use for the page you are looking at, plus your other tabs, so the
  screen can show "Job post: Backend Intern – Globex (opener tab)" with Change *before* you press Fill.
* ``GET /fills/{id}/screenshot``: the screenshot taken after that fill, for the history drawer.

Nothing here types, clicks or navigates. The browser endpoints attach to the bot's browser the same way the
reader does (``connect_over_cdp`` on 127.0.0.1), look, and let go. The screenshot endpoint only ever sends a
PNG that a ``fills`` row points to AND that sits inside ``data/screenshots/``, so a request can never read any
other file on your PC (for example with ``../`` in a stored path).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from engine import api_fill, db, learning, safety
from engine.api_deps import get_conn, get_settings
from engine.api_models import FillPostOut, JobPostPreviewOut, StatusOut, SubmitOfferOut, TabOut
from engine.forms.jobfinder import SOURCE_LABELS, find_job_post
from engine.forms.reader import connect_to_bot_browser, find_current_page
from engine.forms.submitwatch import SubmitWatcher
from engine.settings import ROOT, Settings

SCREENSHOTS_DIR = ROOT / "data" / "screenshots"

router = APIRouter()


class NoPageOpen(Exception):
    """The bot's browser is open but shows no web page (the API answers 409)."""


# ---- the real readers (tests swap these on app.state) --------------------------------------------------


def read_current_tab() -> tuple[str, str]:
    """``(url, title)`` of the page you are looking at in the bot's browser. Look only.

    Raises:
        RuntimeError: the browser is not open, or it has no web page open.
    """
    from playwright.sync_api import sync_playwright  # imported here: tests that swap the reader need no browser

    with sync_playwright() as p:
        page = find_current_page(connect_to_bot_browser(p))
        return page.url, page.title()


def preview_job_post(conn: sqlite3.Connection, settings: Settings) -> JobPostPreviewOut:
    """Run the job post finder on the page you are looking at, without filling anything.

    Logs one ``read`` row (the source label only, never the post text), like every other read.

    Raises:
        RuntimeError: the browser is not open, or it has no web page open.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        page = find_current_page(connect_to_bot_browser(p))
        safety.check("read", page.url, settings=settings)
        found = find_job_post(page, settings=settings, conn=conn)
        post = found.post
        return JobPostPreviewOut(
            page_url=page.url,
            post=FillPostOut(label=post.label, source=SOURCE_LABELS[post.source], tab_title=post.tab_title, tab_url=post.tab_url)
            if post else None,
            tabs=[TabOut(index=t.index, title=t.title, url=t.url) for t in found.tabs],
        )


# ---- endpoints ---------------------------------------------------------------------------------------------


@router.get("/status")
def status(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> StatusOut:
    """The status line: run mode, browser open or not, the current page, and the running fill (if any).

    While a fill runs, the page is not read (the screen shows "Filling…" anyway, and the fill owns the browser).
    """
    jobs: api_fill.JobManager = request.app.state.fill_jobs
    running = jobs.running_id
    browser_open = api_fill.browser_is_open()
    url = title = None
    if browser_open and running is None:
        try:
            url, title = request.app.state.page_reader()
        except RuntimeError:
            pass  # open but no web page (or it closed a moment ago): the screen says "no page open"
    return StatusOut(
        run_mode=settings.run_mode, browser_open=browser_open, page_url=url, page_title=title,
        fill_running=running is not None, fill_job_id=running, submit_offer=newest_offer(request),
    )


def newest_offer(request: Request) -> SubmitOfferOut | None:
    """The newest "Looks submitted. Mark it?" offer for a page that is still ``filled``, with its history title."""
    offers = request.app.state.submit_watcher.offers()
    if not offers:
        return None
    conn = db.connect(request.app.state.db_path)
    try:
        for offer in offers:
            row = conn.execute("SELECT job_title, company, status FROM fills WHERE id = ?", (offer.fill_id,)).fetchone()
            if row is None or row["status"] != "filled":
                request.app.state.submit_watcher.forget(offer.fill_id)
                continue
            title = " – ".join(x for x in (row["job_title"], row["company"]) if x) or "Form without a job post"
            return SubmitOfferOut(fill_id=offer.fill_id, title=title, reason=offer.reason, strong=offer.strong)
    finally:
        conn.close()
    return None


@router.get("/jobpost")
def job_post(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_conn)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JobPostPreviewOut:
    """Which job post would "Fill this page" use right now? Read only; also lists your other tabs for Change."""
    if request.app.state.fill_jobs.busy:
        raise api_fill.FillBusy("A fill is running. The job post can be checked when it is done.")
    if not api_fill.browser_is_open():
        raise api_fill.BrowserNotOpen("The bot's browser is not open. Run: python -m engine.cli browser open")
    try:
        return request.app.state.post_previewer(conn, settings)
    except RuntimeError as exc:
        raise NoPageOpen(str(exc) or "No web page is open in the bot's browser.") from exc


def safe_screenshot(stored: str | None, folder: Path) -> Path | None:
    """The screenshot file to send, or None when it is missing or not a PNG inside ``folder``.

    A relative stored path is read from the project folder. ``resolve()`` turns ``..`` and links into the real
    location first, so ``data/screenshots/../../secrets.png`` is caught.
    """
    if not stored:
        return None
    path = Path(stored)
    if not path.is_absolute():
        path = ROOT / path
    try:
        path, base = path.resolve(), folder.resolve()
    except OSError:
        return None
    if not path.is_relative_to(base) or path.suffix.lower() != ".png" or not path.is_file():
        return None
    return path


@router.get("/fills/{fill_id}/screenshot")
def fill_screenshot(fill_id: int, request: Request, conn: Annotated[sqlite3.Connection, Depends(get_conn)]) -> FileResponse:
    """The PNG taken right after this fill (the history drawer shows it)."""
    row = conn.execute("SELECT screenshot_path FROM fills WHERE id = ?", (fill_id,)).fetchone()
    if row is None:
        raise learning.NotFound(f"There is no filled page {fill_id}.")
    path = safe_screenshot(row["screenshot_path"], Path(request.app.state.screenshots_dir))
    if path is None:
        raise learning.NotFound("There is no screenshot for this filled page.")
    return FileResponse(path, media_type="image/png")


def install_browser(app: FastAPI) -> None:
    """Add the routes, the real readers (tests replace them) and the 409 for "no page open"."""
    app.state.page_reader = read_current_tab
    app.state.post_previewer = preview_job_post
    app.state.screenshots_dir = SCREENSHOTS_DIR
    app.state.submit_watcher = SubmitWatcher(app.state.db_path)  # passive submit detection (read-only)
    app.include_router(router)

    async def no_page(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"code": "no_page", "detail": str(exc)}, status_code=409)

    app.add_exception_handler(NoPageOpen, no_page)
