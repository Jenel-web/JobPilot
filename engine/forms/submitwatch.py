"""Passive submit detection: after a fill, watch the tab READ-ONLY and offer "Looks submitted. Mark it?".

You click Submit yourself (JobPilot never does). This module only notices that you probably did, so the filled
pages history can be kept right without you remembering to press "Mark as submitted".

How it works:

* When a fill finishes, the engine notes Chrome's own id for that tab (a CDP "target id", which stays the same
  when the page inside the tab changes) and starts watching it.
* Every few seconds it looks at that tab: its address, its visible text and how many form fields it shows.
  Looking means reading only: nothing is clicked, typed, added to the page or listened to.
* :func:`looks_submitted` decides, by code (no AI):
    - confirmation words ("Thank you for applying", "Application received", "Your response has been recorded")
      -> a strong offer, and watching stops;
    - the address changed and the new page has no form left -> a weak offer ("Did you submit it?"), watching goes
      on in case a confirmation appears; a new page that still has a form is the next step of a multi-step form,
      so it is NOT an offer.
* Watching stops when the tab closes, the page is marked submitted / abandoned, or after 30 minutes.
* It NEVER marks anything itself: the dashboard shows the offer and you press "Mark as submitted".
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from engine import db, safety

CHECK_EVERY_S = 4.0
WATCH_FOR_S = 30 * 60
MIN_FORM_FIELDS = 3  # a page with this many visible fields is still a form (the next step), not a confirmation
TEXT_LIMIT = 20_000

# Confirmation words a site shows after you submit. Whole phrases only: "Thank you for your interest" is NOT here,
# because many job posts say it BEFORE you apply.
CONFIRMATION = re.compile(
    r"\b("
    r"thanks? (you )?(so much )?for (applying|your application|submitting( your application)?)|"
    r"(your )?application (has been |was )?(received|submitted|sent|completed?)|"
    r"we('ve| have) (successfully )?received your (application|submission|response|cv|resume)|"
    r"(successfully|you('ve| have)( successfully)?) (submitted|applied)|"
    r"submission (received|successful|complete)|"
    r"your response has been recorded"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TabView:
    """What the watcher read from the tab: its address, visible text and number of visible form fields."""

    url: str
    text: str
    fields: int


@dataclass(frozen=True)
class Suggestion:
    """An offer to mark a filled page as submitted. ``strong`` = confirmation words were seen."""

    fill_id: int
    reason: str
    strong: bool
    url: str
    seen_at: str


def _same_page(a: str, b: str) -> bool:
    """Same address, ignoring a #fragment (a site moving within the page is not a new page)."""
    pa, pb = urlsplit(a), urlsplit(b)
    return (pa.scheme, pa.netloc, pa.path.rstrip("/"), pa.query) == (pb.scheme, pb.netloc, pb.path.rstrip("/"), pb.query)


def looks_submitted(filled_url: str, view: TabView) -> tuple[str, bool] | None:
    """Does the tab look submitted? ``(reason, strong)`` or ``None``. By code, no AI; see the module notes."""
    found = CONFIRMATION.search(view.text or "")
    if found:
        return f'The page now says "{found.group(0)}".', True
    if view.url and not _same_page(view.url, filled_url) and view.fields < MIN_FORM_FIELDS:
        return "The page changed after filling and no form is left.", False
    return None


def read_tab(target_id: str) -> TabView | None:
    """Read the tab with this Chrome id from the bot's browser. ``None`` = the tab (or the browser) is gone. Read-only."""
    from playwright.sync_api import sync_playwright  # imported here: tests pass their own reader

    from engine.forms.jobfinder import _target_id
    from engine.forms.reader import connect_to_bot_browser

    try:
        with sync_playwright() as p:
            browser = connect_to_bot_browser(p)
            for context in browser.contexts:
                for page in context.pages:
                    if page.is_closed() or _target_id(page) != target_id:
                        continue
                    data = page.evaluate(
                        """(limit) => ({
                          text: document.body ? document.body.innerText.slice(0, limit) : '',
                          fields: [...document.querySelectorAll('input, select, textarea')].filter(e =>
                            !['hidden', 'submit', 'button', 'image', 'reset', 'search'].includes((e.type || '').toLowerCase())
                            && e.getClientRects().length > 0).length,
                        })""",
                        TEXT_LIMIT,
                    )
                    return TabView(page.url, str(data["text"]), int(data["fields"]))
    except Exception:  # noqa: BLE001 - browser closed, tab closing, page navigating: treat as "gone" this time
        return None
    return None


@dataclass
class _Watch:
    fill_id: int
    target_id: str
    url: str
    started: float


class SubmitWatcher:
    """Watches finished fills in one background thread and keeps the offers for ``GET /status``."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        read: Callable[[str], TabView | None] = read_tab,
        every: float = CHECK_EVERY_S,
        watch_for: float = WATCH_FOR_S,
        clock: Callable[[], float] = time.monotonic,
        start_thread: bool = True,
    ) -> None:
        self._db_path, self._read, self._every, self._watch_for, self._clock = db_path, read, every, watch_for, clock
        self._start_thread = start_thread
        self._watches: dict[int, _Watch] = {}
        self._offers: dict[int, Suggestion] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # -- what the API calls --

    def watch(self, fill_id: int, target_id: str, url: str) -> None:
        """Start watching the tab a fill just filled."""
        if not target_id:
            return
        with self._lock:
            self._watches[fill_id] = _Watch(fill_id, target_id, url, self._clock())
            self._offers.pop(fill_id, None)
            if self._start_thread and (self._thread is None or not self._thread.is_alive()):
                self._thread = threading.Thread(target=self._loop, name="submit-watch", daemon=True)
                self._thread.start()

    def offers(self) -> list[Suggestion]:
        """Current offers, newest first."""
        with self._lock:
            return sorted(self._offers.values(), key=lambda s: s.seen_at, reverse=True)

    def forget(self, fill_id: int) -> None:
        """You decided (submitted or abandoned): no more offers or watching for this page."""
        with self._lock:
            self._watches.pop(fill_id, None)
            self._offers.pop(fill_id, None)

    @property
    def watching(self) -> list[int]:
        with self._lock:
            return list(self._watches)

    # -- the work --

    def check_once(self) -> None:
        """Look at every watched tab once. Called by the background thread (tests call it directly)."""
        with self._lock:
            watches = list(self._watches.values())
        for w in watches:
            if not self._still_open(w.fill_id):  # you marked it already: no offer needed
                self.forget(w.fill_id)
                continue
            if self._clock() - w.started > self._watch_for:  # 30 minutes: stop looking (an offer already made stays)
                self._stop(w.fill_id)
                continue
            view = self._read(w.target_id)
            if view is None:  # the tab was closed: you may have given up; the decision stays yours
                self._stop(w.fill_id)
                continue
            found = looks_submitted(w.url, view)
            if found is None:
                continue
            reason, strong = found
            offer = Suggestion(w.fill_id, reason, strong, view.url, f"{datetime.now():%Y-%m-%d %H:%M:%S}")
            with self._lock:
                is_new = w.fill_id not in self._offers or (strong and not self._offers[w.fill_id].strong)
                self._offers[w.fill_id] = offer
                if strong:
                    self._watches.pop(w.fill_id, None)
            if is_new:
                self._log(w.fill_id, view.url, f"looks submitted ({'confirmation seen' if strong else 'page changed'}); offered, not marked")

    def _stop(self, fill_id: int) -> None:
        with self._lock:
            self._watches.pop(fill_id, None)

    def _still_open(self, fill_id: int) -> bool:
        """Is the page still ``filled`` (not yet marked by you)?"""
        try:
            conn = db.connect(self._db_path)
            try:
                row = conn.execute("SELECT status FROM fills WHERE id = ?", (fill_id,)).fetchone()
            finally:
                conn.close()
        except sqlite3.Error:
            return True
        return row is not None and row["status"] == "filled"

    def _log(self, fill_id: int, url: str, details: str) -> None:
        """Rule 7: an offer is logged (a read), with the page address and no page text."""
        try:
            conn = db.connect(self._db_path)
            try:
                safety.log_action(conn, "read", url, details, fill_id=fill_id)
            finally:
                conn.close()
        except sqlite3.Error:
            pass

    def _loop(self) -> None:
        while True:
            with self._lock:
                if not self._watches:
                    self._thread = None
                    return
            self.check_once()
            time.sleep(self._every)
