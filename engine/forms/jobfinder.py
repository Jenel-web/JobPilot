"""Where is the job post? Look on the form page, then the tab that opened it, then other tabs on the same site.

The application form is often on a different tab from the job description. The bot can see every tab in
its OWN browser (never your everyday Chrome), so it looks in this order and stops at the first hit:

  1. the form page itself        (many sites show the description beside the form)
  2. the opener tab              (clicking Apply opened the form in a new tab: ``page.opener()``)
  3. another tab on the same site (``careers.acme.com/job/123`` next to ``.../123/apply``)
  4. ask you                     (``FindResult.tabs`` lists your open tabs; you pick one or paste text)

It is READ-ONLY: it reads page text and never clicks, types or navigates. It is plain keyword code, not AI,
so a wrong guess can never invent a job. It never guesses a resume either: no post found means ``post`` is
``None`` and the resume is not uploaded (the field is flagged and you are asked).

This is not ``jobpost.py``: that file reads *where* the job is (remote / Metro Manila) from the text.
This file finds the text.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from engine import safety
from engine.settings import Settings

Source = Literal["form_page", "opener", "same_site", "chosen", "pasted"]

SOURCE_LABELS: dict[str, str] = {
    "form_page": "this page",
    "opener": "opener tab",
    "same_site": "same-site tab",
    "chosen": "tab you chose",
    "pasted": "text you pasted",
}

MAX_TEXT_CHARS = 8000  # plenty for a job post; the picker cuts it further (matcher.MAX_POST_CHARS)
READ_TIMEOUT_MS = 3000

# Rule 9: no LinkedIn automation. We do not even read a LinkedIn tab (open question in ROADMAP, Nov 13).
BLOCKED_SITES = frozenset({"linkedin.com"})

# Job-board hosts shared by MANY companies. Two tabs on the same host are not the same company here, so
# they must also share the first path segment (``/angkas/...``). Tune this list from real use.
SHARED_HOSTS = frozenset({
    "greenhouse.io", "lever.co", "workable.com", "myworkdayjobs.com", "ashbyhq.com", "smartrecruiters.com",
    "prosple.com", "bamboohr.com", "breezy.hr", "recruitee.com", "jobvite.com", "teamtailor.com",
})
_SECOND_LEVEL = frozenset({"com", "co", "org", "net", "gov", "edu", "ac"})  # example.com.ph, example.co.uk


@dataclass(frozen=True)
class JobPost:
    """The job post text and where it came from (so the controls page can say "used: ... (opener tab)")."""

    text: str
    source: Source
    tab_title: str = ""
    tab_url: str = ""

    @property
    def label(self) -> str:
        """Short human label such as ``Backend Intern, Acme (opener tab)``."""
        where = SOURCE_LABELS[self.source]
        return f"{self.tab_title} ({where})" if self.tab_title else where


@dataclass(frozen=True)
class TabInfo:
    """One open tab, for the "Which one is the job post?" list. ``index`` is its place in ``context.pages``."""

    index: int
    title: str
    url: str


@dataclass(frozen=True)
class FindResult:
    """What the finder found. ``post`` is None when nothing looked like a job post: then you are asked."""

    post: JobPost | None
    tabs: list[TabInfo] = field(default_factory=list)


# ---- is this text a job post? ---------------------------------------------------------------------

# A heading is a SHORT line that names a section of a job post. Calibrated on the 5 saved posts in
# data/job_posts/, which use very different words ("Position Responsibilities:", "Compensation & Benefits"...).
# Each pattern must match the WHOLE line (``fullmatch``): a filter label such as "Unpaid with benefits" or
# "Experience requirement" on a search page is not a heading. Found on a real Prosple search page (Nov 20).
_HEADINGS = (
    re.compile(r"(?:[\w&/-]+ ){0,3}responsibilities(?: include)?"),  # "Position Responsibilities", "Key responsibilities include:"
    re.compile(r"(?:[\w&/-]+ ){0,3}qualifications(?: (?:&|and) (?:other )?requirements)?"),  # "Required Qualifications"
    re.compile(r"(?:[\w&/-]+ ){0,2}requirements"),  # "Requirements", "Minimum Requirements"
    re.compile(r"your role|about you|the role|who you are|the company is looking for"),  # Prosple: "Your Role", "About You"
    re.compile(r"job description|role description|about the (?:job|role|position)"),
    re.compile(r"(?:here(?:'s|’s| is) )?what you(?:'ll| will| could| would)? (?:be doing|do|work on|bring|need)(?: to have)?"),
    re.compile(r"(?:required|preferred|key|desired) skills"),
    re.compile(r"(?:compensation|perks|salary)(?: (?:&|and) | )benefits|benefits"),
)
MAX_HEADING_CHARS = 60
MIN_WORDS_TWO_HEADINGS = 100
MIN_WORDS_ONE_HEADING = 250


def count_headings(text: str) -> int:
    """How many DIFFERENT job-post section headings the text has (each kind counts once)."""
    found: set[int] = set()
    for line in text.splitlines():
        line = line.strip(" \t:-•*#").lower()
        if not line or len(line) > MAX_HEADING_CHARS:
            continue
        for number, pattern in enumerate(_HEADINGS):
            if pattern.fullmatch(line):
                found.add(number)
    return len(found)


MIN_REPEATS = 4  # a short line seen this often ("Apply on employer site", "Closing in") belongs to a list of cards
MAX_REPEATED_SHARE = 0.15  # a results list is mostly such lines; a post with a few "similar jobs" cards is not


def repeated_line_share(text: str) -> float:
    """The share of non-empty lines that are short lines repeated :data:`MIN_REPEATS` or more times.

    Near 0 for a job post. High for a search results page, where every card repeats the same labels.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return 0.0
    counts = Counter(line for line in lines if len(line) <= MAX_HEADING_CHARS)
    return sum(n for n in counts.values() if n >= MIN_REPEATS) / len(lines)


def looks_like_job_post(text: str) -> bool:
    """True if the text reads like a job description: section headings AND enough words, and not a list.

    Two or more different headings with 100+ words, or one heading with 250+ words (a real Prosple job page
    has just one: "Qualifications"). A bare form, a cookie banner or a login page has neither. A search
    results page is rejected by :func:`repeated_line_share` even if a filter label looks like a heading.
    """
    headings = count_headings(text)
    words = len(text.split())
    enough = (headings >= 2 and words >= MIN_WORDS_TWO_HEADINGS) or (headings >= 1 and words >= MIN_WORDS_ONE_HEADING)
    return enough and repeated_line_share(text) <= MAX_REPEATED_SHARE


# ---- which tabs are on the same site? -------------------------------------------------------------


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def site_of(url: str) -> str:
    """The site a web address belongs to: ``careers.acme.com`` -> ``acme.com``, ``x.acme.com.ph`` -> ``acme.com.ph``."""
    labels = _host(url).split(".")
    if len(labels) <= 2:
        return ".".join(labels)
    keep = 3 if len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL else 2
    return ".".join(labels[-keep:])


def _path_parts(url: str) -> list[str]:
    return [p for p in urlparse(url).path.split("/") if p]


def _common_prefix(a: list[str], b: list[str]) -> int:
    count = 0
    for x, y in zip(a, b):
        if x != y:
            break
        count += 1
    return count


def same_site(url_a: str, url_b: str) -> bool:
    """True if both addresses are the same site or company.

    Normal sites: the same registered domain. Shared job boards (Workable, Greenhouse...): the same host
    AND the same first path segment, so two different companies on one board are not mixed up.
    """
    site = site_of(url_a)
    if not site or site != site_of(url_b):
        return False
    if site in SHARED_HOSTS:
        a, b = _path_parts(url_a), _path_parts(url_b)
        return _host(url_a) == _host(url_b) and _common_prefix(a, b) >= 1
    return True


# ---- reading tabs (read-only) ---------------------------------------------------------------------


def _readable(url: str) -> bool:
    """Web pages and saved files only; blank tabs, ``chrome://`` and blocked sites are skipped."""
    if not url.startswith(("http://", "https://", "file:")):
        return False
    return site_of(url) not in BLOCKED_SITES


MIN_MAIN_WORDS = 100  # a <main>/<article> shorter than this is probably not the whole description

# The page's main content: the longest <main>, <article> or role=main. Site menus, headers (with your name
# when you are signed in) and footers sit outside it, so they never reach the resume picker.
_MAIN_JS = (
    "() => [...document.querySelectorAll('main, article, [role=main]')]"
    ".map(e => e.innerText || '').sort((a, b) => b.length - a.length)[0] || ''"
)


def _texts(tab: Page) -> list[str]:
    """The tab's text, best first: its main content (when it has enough words), then the whole body.

    Returns an empty list if the tab cannot be read (closed, still loading).
    """
    try:
        body = tab.inner_text("body", timeout=READ_TIMEOUT_MS).strip()
        main = str(tab.evaluate(_MAIN_JS)).strip()
    except PlaywrightError:
        return []
    texts = [main] if len(main.split()) >= MIN_MAIN_WORDS else []
    return [t[:MAX_TEXT_CHARS] for t in (*texts, body) if t]


def tab_text(tab: Page) -> str:
    """The text of a tab (main content if it has any, else the whole page), or "" if it cannot be read."""
    texts = _texts(tab)
    return texts[0] if texts else ""


def _title(tab: Page) -> str:
    try:
        return tab.title().strip()
    except PlaywrightError:
        return ""


def _read_post(tab: Page, source: Source, settings: Settings | None) -> JobPost | None:
    """Read one tab and return a post if its text looks like one. Calls ``safety.check("read")`` first."""
    if not _readable(tab.url):
        return None
    try:
        safety.check("read", tab.url, settings=settings)
    except safety.SafetyError:
        return None
    for text in _texts(tab):  # main content first; if only the whole page reads like a post, use that
        if looks_like_job_post(text):
            return JobPost(text, source, _title(tab), tab.url)
    return None


def _target_id(tab: Page) -> str:
    """Chrome's own id for a tab (a CDP "target id"). Read-only."""
    session = tab.context.new_cdp_session(tab)
    try:
        return str(session.send("Target.getTargetInfo")["targetInfo"]["targetId"])
    finally:
        session.detach()


def _chrome_opener_id(tab: Page) -> str:
    session = tab.context.new_cdp_session(tab)
    try:
        return str(session.send("Target.getTargetInfo")["targetInfo"].get("openerId") or "")
    finally:
        session.detach()


def opener_of(tab: Page) -> Page | None:
    """The tab that opened ``tab``, or None.

    Playwright's ``tab.opener()`` only knows about tabs it saw being created. The bot's browser is already
    running when JobPilot attaches (``connect_over_cdp``), so it says ``None`` for every tab (seen on Prosple,
    Nov 20). Chrome itself still remembers who opened whom (``openerId``), so when Playwright has no answer
    we ask Chrome. Both ways are read-only.
    """
    opener = tab.opener()
    if opener is not None:
        return opener
    try:
        wanted = _chrome_opener_id(tab)
        if not wanted:
            return None
        for other in tab.context.pages:
            if other != tab and not other.is_closed() and _target_id(other) == wanted:
                return other
    except PlaywrightError:
        return None
    return None


def list_tabs(form_page: Page) -> list[TabInfo]:
    """Every other readable tab in the same browser window set, for the "Which one is the job post?" list."""
    tabs: list[TabInfo] = []
    for index, tab in enumerate(form_page.context.pages):
        if tab == form_page or tab.is_closed() or not _readable(tab.url):
            continue
        tabs.append(TabInfo(index, _title(tab), tab.url))
    return tabs


def find_job_post(
    form_page: Page, *, settings: Settings | None = None, conn: sqlite3.Connection | None = None
) -> FindResult:
    """Find the job post for ``form_page``: form page, then opener tab, then a same-site tab.

    Read-only. Returns ``FindResult(post=None, tabs=[...])`` when nothing looks like a job post, so the
    caller can flag the resume upload and ask you (pick a tab with :func:`post_from_tab` or paste with
    :func:`post_from_pasted`). Logs one ``read`` row (a source label only, never the text) when ``conn`` is given.
    """
    post = _read_post(form_page, "form_page", settings)

    if post is None:
        opener = opener_of(form_page)
        if opener is not None and not opener.is_closed():
            post = _read_post(opener, "opener", settings)

    if post is None:
        post = _same_site_post(form_page, settings)

    result = FindResult(post, list_tabs(form_page))
    if conn is not None:
        found = f"job post: {post.source}" if post else "job post: not found"
        safety.log_action(conn, "read", form_page.url, found)
    return result


def _same_site_post(form_page: Page, settings: Settings | None) -> JobPost | None:
    """The best same-site tab that holds a post. The one whose address shares most with the form's wins."""
    form_parts = _path_parts(form_page.url)
    candidates = [
        tab for tab in form_page.context.pages
        if tab != form_page and not tab.is_closed() and same_site(tab.url, form_page.url)
    ]
    candidates.sort(key=lambda tab: -_common_prefix(_path_parts(tab.url), form_parts))  # stable: ties keep tab order
    for tab in candidates:
        post = _read_post(tab, "same_site", settings)
        if post is not None:
            return post
    return None


# ---- "ask you": your choice always wins -----------------------------------------------------------


def post_from_pasted(text: str) -> JobPost | None:
    """A post from text you pasted. Empty text means no post. No keyword check: you decided."""
    text = text.strip()[:MAX_TEXT_CHARS]
    return JobPost(text, "pasted") if text else None


def post_from_tab(form_page: Page, tab: TabInfo) -> JobPost | None:
    """A post from the tab you picked in the list. No keyword check: you decided.

    Returns None if that tab is gone or changed since the list was shown (tab numbers can shift).
    """
    pages = form_page.context.pages
    if not 0 <= tab.index < len(pages):
        return None
    chosen = pages[tab.index]
    if chosen.is_closed() or chosen.url != tab.url or not _readable(chosen.url):
        return None
    text = tab_text(chosen)
    return JobPost(text, "chosen", _title(chosen), chosen.url) if text else None


def job_text_of(post: JobPost | None) -> str | None:
    """The text to hand to ``pick_resume`` and ``answer_form(job_text=...)``; None means "no job post".

    ``None`` (not ``""``) matters to ``answer_form``: it then uses the saved answers and their location
    scope instead of reading the job's location from text.
    """
    return post.text if post else None
