"""Tests for the job post finder (``engine/forms/jobfinder.py``).

Pages are served from memory by Playwright routes on fake hosts (``careers.acme.test``), so no real website
is touched and nothing needs the network. The opener test uses a real ``window.open``.
"""

from __future__ import annotations

import socket
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, Route, sync_playwright

from engine import matcher
from engine.db import connect, init_db
from engine.forms import answers, jobfinder
from engine.forms.jobfinder import (
    JobPost, count_headings, find_job_post, job_text_of, list_tabs, looks_like_job_post, post_from_pasted,
    post_from_tab, repeated_line_share, same_site, site_of,
)
from engine.forms.reader import FormField
from engine.settings import Settings

MOCK = Settings(run_mode="mock")

POST_BODY = (
    "<h1>Backend Intern</h1><p>Acme builds payment tools in Makati. " + "We ship small things every week. " * 30 + "</p>"
    "<h2>Responsibilities</h2><ul><li>Write Python services</li><li>Review pull requests</li><li>Fix bugs</li></ul>"
    "<h2>Required Qualifications</h2><ul><li>Python or Java</li><li>SQL basics</li><li>Good communication</li></ul>"
)
POST_HTML = f"<html><head><title>Backend Intern - Acme</title></head><body>{POST_BODY}</body></html>"
FORM_ONLY = (
    "<html><head><title>Apply - Acme</title></head><body><h1>Apply</h1>"
    "<label>First name <input></label><label>Email <input></label><label>Resume <input type=file></label>"
    "</body></html>"
)
FORM_WITH_POST = f"<html><head><title>Apply - Acme</title></head><body>{POST_BODY}<label>First name <input></label></body></html>"
OTHER_SITE = "<html><head><title>News</title></head><body><h1>Cats</h1><p>Nothing to see.</p></body></html>"

PAGES = {
    "http://careers.acme.test/job/123": POST_HTML,
    "http://careers.acme.test/job/123/apply": FORM_ONLY,
    "http://careers.acme.test/job/123/apply-with-post": FORM_WITH_POST,
    "http://news.other.test/cats": OTHER_SITE,
    "http://news.other.test/jobs": POST_HTML,  # a real post, but on ANOTHER site
}


def _serve(route: Route) -> None:
    route.fulfill(status=200, content_type="text/html", body=PAGES.get(route.request.url, "<html><body>missing</body></html>"))


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def context(browser: Browser) -> Iterator[BrowserContext]:
    ctx = browser.new_context()
    ctx.route("**/*", _serve)
    yield ctx
    ctx.close()


def open_tab(context: BrowserContext, url: str) -> Page:
    tab = context.new_page()
    tab.goto(url)
    return tab


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    init_db(connection)
    yield connection
    connection.close()


# ---- is this text a job post? ----------------------------------------------------------------------


def test_a_post_with_headings_looks_like_a_post() -> None:
    text = "Responsibilities:\n" + "build things well " * 40 + "\nRequired Qualifications:\n" + "know python " * 20
    assert count_headings(text) == 2
    assert looks_like_job_post(text)


def test_a_bare_form_or_cookie_banner_is_not_a_post() -> None:
    assert not looks_like_job_post("First name\nEmail\nResume\nSubmit application")
    assert not looks_like_job_post("We use cookies to improve your experience. " * 40)


def test_long_prose_without_headings_is_not_a_post() -> None:
    assert not looks_like_job_post("word " * 600)


def test_one_heading_needs_more_words() -> None:
    assert not looks_like_job_post("Responsibilities:\n" + "word " * 50)
    assert looks_like_job_post("Responsibilities:\n" + "word " * 300)


def test_a_search_results_page_with_filter_labels_is_not_a_post() -> None:
    """Real miss (Prosple search page, Nov 20): sidebar filters like "Unpaid with benefits" are not headings."""
    filters = "\n".join(["Unpaid with benefits", "Experience requirement", "Job type", "Internship"] * 5)
    listing = "\n".join(f"Software Intern {n}\nAcme\nMakati\nApply by 30 Nov" for n in range(80))
    page = filters + "\n" + listing
    assert len(page.split()) > 250
    assert count_headings(page) == 0
    assert not looks_like_job_post(page)


def test_a_list_of_cards_is_rejected_even_when_it_has_a_heading_and_many_words() -> None:
    """Real miss (Prosple, Nov 20): one stray heading + 1000 words, but the same labels on every card."""
    cards = "\n".join(
        f"Software Intern {n}\nAcme Corp\nClosing in {n} days\nApply on employer site\nHIRING STUDENTS FROM\nComputer Science"
        for n in range(40)
    )
    page = "Benefits\n" + cards
    assert count_headings(page) == 1
    assert len(page.split()) > 250
    assert repeated_line_share(page) > 0.15
    assert not looks_like_job_post(page)


def test_a_one_heading_post_with_a_few_similar_job_cards_is_still_a_post() -> None:
    """A real Prosple job page has one heading ("Qualifications") and a few "similar jobs" cards at the bottom."""
    about = "\n".join(f"We build useful software for students, point {n}." for n in range(40))
    skills = "\n".join(f"Currently enrolled student with skill number {n}." for n in range(30))
    post = "About us\n" + about + "\nQualifications\n" + skills
    cards = "\n".join(f"Intern {n}\nClosing in {n} days\nApply on employer site" for n in range(4))
    page = post + "\nSimilar jobs\n" + cards
    assert count_headings(page) == 1
    assert repeated_line_share(page) <= 0.15
    assert looks_like_job_post(page)


def test_a_prosple_page_with_no_main_area_and_its_own_headings_is_a_post() -> None:
    """Real miss (EastWest on Prosple, Nov 20): the headings were Your Role / About You / Qualifications & other requirements."""
    menu = "Search Jobs\nAdvice\nTop 100 Employers\nForum\nPhilippines\nEastwest Bank\nAdd a review\nSave\nOverview\nApply\n"
    body = (
        "Your Role\nKey responsibilities include:\n" + "\n".join(f"Support the team with task number {n} each week." for n in range(25))
        + "\nAbout You\nThe company is looking for:\n" + "\n".join(f"A student with skill number {n}." for n in range(25))
        + "\nQualifications & other requirements\nDegree or Certificate\nStudy field\nPhilippine Citizen\n"
    )
    page = menu + body
    assert count_headings(page) >= 2
    assert looks_like_job_post(page)
    assert not looks_like_job_post(menu + "Apply\nSave\n" * 3)


def test_the_real_heading_styles_are_still_recognised() -> None:
    for heading in (
        "Position Responsibilities:", "Required Qualifications:", "Your Role And Responsibilities", "Job Description",
        "About the job", "What You Could Work On", "Here's what you will be doing:", "Compensation & Benefits",
        "Requirements", "Preferred Qualifications:",
    ):
        assert count_headings(heading) == 1, heading


def test_headings_in_the_middle_of_a_long_line_do_not_count() -> None:
    assert count_headings("We list the responsibilities and qualifications of this role in a very long sentence here.") == 0


# ---- same site -------------------------------------------------------------------------------------


def test_site_of_handles_subdomains_and_country_domains() -> None:
    assert site_of("https://careers.acme.com/job/1") == "acme.com"
    assert site_of("https://jobs.acme.com.ph/x") == "acme.com.ph"
    assert site_of("http://localhost:3000/") == "localhost"


def test_same_site_normal_company_site() -> None:
    assert same_site("https://careers.acme.com/job/123", "https://www.acme.com/apply")
    assert not same_site("https://careers.acme.com/job/123", "https://other.com/job/123")


def test_same_site_on_shared_board_needs_the_same_company_path() -> None:
    assert same_site("https://apps.workable.com/angkas/j/ABC", "https://apps.workable.com/angkas/j/ABC/apply")
    assert not same_site("https://apps.workable.com/angkas/j/ABC", "https://apps.workable.com/globe/j/XYZ")


# ---- finding the post ------------------------------------------------------------------------------


def test_post_is_on_the_form_page(context: BrowserContext, conn: sqlite3.Connection) -> None:
    form = open_tab(context, "http://careers.acme.test/job/123/apply-with-post")
    result = find_job_post(form, settings=MOCK, conn=conn)
    assert result.post is not None
    assert result.post.source == "form_page"
    assert "Required Qualifications" in result.post.text
    assert result.post.label == "Apply - Acme (this page)"
    row = conn.execute("SELECT kind, details FROM action_log").fetchone()
    assert (row["kind"], row["details"]) == ("read", "job post: form_page")  # a label only, never the text


def test_the_post_text_is_the_main_content_without_the_site_menu(context: BrowserContext) -> None:
    """Real case (Prosple, Nov 20): the page text began with the site menu and the signed-in name."""
    page_html = (
        "<html><head><title>Backend Intern - Acme</title></head><body>"
        "<header><nav>Search Jobs | Advice | Forum | Signed in: Maria Santos</nav></header>"
        f"<main>{POST_BODY}</main><footer>Terms | Privacy | Cookies</footer></body></html>"
    )
    PAGES["http://careers.acme.test/job/main"] = page_html
    tab = open_tab(context, "http://careers.acme.test/job/main")
    result = find_job_post(tab, settings=MOCK)
    assert result.post is not None
    assert "Required Qualifications" in result.post.text
    assert "Maria Santos" not in result.post.text and "Search Jobs" not in result.post.text
    assert "Privacy" not in result.post.text


def test_a_page_without_a_main_area_falls_back_to_the_whole_page(context: BrowserContext) -> None:
    tab = open_tab(context, "http://careers.acme.test/job/123")  # POST_HTML has no <main>
    assert "Required Qualifications" in jobfinder.tab_text(tab)


def test_post_is_in_the_opener_tab(context: BrowserContext) -> None:
    job = open_tab(context, "http://careers.acme.test/job/123")
    with context.expect_page() as opened:  # clicking Apply opens the form in a NEW tab
        job.evaluate("window.open('http://careers.acme.test/job/123/apply')")
    form = opened.value
    form.wait_for_load_state()
    assert form.opener() == job
    result = find_job_post(form, settings=MOCK)
    assert result.post is not None
    assert result.post.source == "opener"
    assert result.post.tab_title == "Backend Intern - Acme"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_opener_is_found_when_attaching_to_a_browser_that_is_already_running(browser: Browser, tmp_path: Path) -> None:
    """The real situation (Prosple, Nov 20): the bot's browser is already open, JobPilot attaches afterwards.

    Playwright's own ``opener()`` then says None for every tab, but Chrome still knows who opened whom.
    """
    port = _free_port()
    chromium = browser.browser_type  # reuse the module's running Playwright (two sync_playwright() can't nest)
    # 1) "You" browse in the bot's browser: job post, then Apply opens the form in a new tab.
    bot = chromium.launch_persistent_context(
        str(tmp_path), headless=True, args=[f"--remote-debugging-port={port}", "--remote-debugging-address=127.0.0.1"]
    )
    try:
        bot.route("**/*", _serve)
        job = bot.new_page()
        job.goto("http://careers.acme.test/job/123")
        with bot.expect_page() as opened:
            job.evaluate("window.open('http://careers.acme.test/job/123/apply')")
        opened.value.wait_for_load_state()

        # 2) JobPilot attaches LATER, like `connect_over_cdp` in reader.py.
        attached = chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        pages = attached.contexts[0].pages
        form = next(pg for pg in pages if pg.url.endswith("/apply"))
        job_seen = next(pg for pg in pages if pg.url.endswith("/job/123"))

        # Playwright's own form.opener() is unreliable here: sometimes None (Prosple, Nov 20), sometimes right.
        # So we do not assert on it. Ours must work either way.
        assert jobfinder.opener_of(form) == job_seen  # Chrome's own record
        assert jobfinder.opener_of(job_seen) is None  # nobody opened the first tab
        result = find_job_post(form, settings=MOCK)
        assert result.post is not None
        assert result.post.source == "opener"
        assert result.post.tab_url == "http://careers.acme.test/job/123"
    finally:
        bot.close()


def test_post_is_in_a_same_site_tab(context: BrowserContext) -> None:
    open_tab(context, "http://news.other.test/cats")  # noise
    open_tab(context, "http://careers.acme.test/job/123")  # the post, but NOT the opener
    form = open_tab(context, "http://careers.acme.test/job/123/apply")
    assert form.opener() is None
    result = find_job_post(form, settings=MOCK)
    assert result.post is not None
    assert result.post.source == "same_site"
    assert result.post.tab_url == "http://careers.acme.test/job/123"


def test_a_post_on_another_site_is_not_used(context: BrowserContext) -> None:
    open_tab(context, "http://news.other.test/jobs")  # looks like a post, but it is a different site
    form = open_tab(context, "http://careers.acme.test/job/123/apply")
    result = find_job_post(form, settings=MOCK)
    assert result.post is None


def test_no_post_means_none_and_the_resume_is_not_uploaded(context: BrowserContext, conn: sqlite3.Connection) -> None:
    open_tab(context, "http://news.other.test/cats")
    form = open_tab(context, "http://careers.acme.test/job/123/apply")
    result = find_job_post(form, settings=MOCK, conn=conn)
    assert result.post is None
    assert job_text_of(result.post) is None
    assert [t.url for t in result.tabs] == ["http://news.other.test/cats"]  # the "which one?" list for asking you
    assert conn.execute("SELECT details FROM action_log").fetchone()["details"] == "job post: not found"
    # What the rest of the engine does with "no post": the resume field is flagged, and the picker never runs.
    field = FormField(label="Resume", type="file", required=True)
    flagged = answers.file_answer(field, has_job_post=job_text_of(result.post) is not None)
    assert flagged.source == "resume"
    assert flagged.flagged
    assert matcher.pick_resume(conn, job_text_of(result.post) or "") is None


def test_a_blank_tab_and_linkedin_tabs_are_not_listed_or_read(context: BrowserContext) -> None:
    blank = context.new_page()  # about:blank
    form = open_tab(context, "http://careers.acme.test/job/123/apply")
    assert blank.url == "about:blank"
    assert list_tabs(form) == []
    assert jobfinder.site_of("https://www.linkedin.com/jobs/view/1") in jobfinder.BLOCKED_SITES
    assert not jobfinder._readable("https://www.linkedin.com/jobs/view/1")


# ---- "Change": your choice replaces the text before upload -----------------------------------------


def test_pasted_text_replaces_the_found_post() -> None:
    assert post_from_pasted("   ") is None
    pasted = post_from_pasted("  Data Analyst Intern. Excel and SQL.  ")
    assert pasted == JobPost("Data Analyst Intern. Excel and SQL.", "pasted")
    assert pasted.label == "text you pasted"


def test_choosing_a_tab_replaces_the_found_post(context: BrowserContext) -> None:
    other = open_tab(context, "http://news.other.test/cats")
    form = open_tab(context, "http://careers.acme.test/job/123/apply")
    assert find_job_post(form, settings=MOCK).post is None
    (tab,) = list_tabs(form)
    chosen = post_from_tab(form, tab)  # no keyword check: you decided
    assert chosen is not None
    assert chosen.source == "chosen"
    assert "Nothing to see" in chosen.text
    other.close()
    assert post_from_tab(form, tab) is None  # the tab is gone: no stale text


def test_the_changed_text_is_what_reaches_the_resume_picker(
    context: BrowserContext, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(matcher, "pick_resume", lambda c, text, settings=None: seen.append(text))
    form = open_tab(context, "http://careers.acme.test/job/123/apply-with-post")
    found = find_job_post(form, settings=MOCK)
    replacement = post_from_pasted("Data Analyst Intern. Excel and SQL.")
    chosen = replacement or found.post  # "Change": the replacement wins
    matcher.pick_resume(conn, job_text_of(chosen) or "")
    assert seen == ["Data Analyst Intern. Excel and SQL."]


def test_found_text_reaches_answer_form_for_the_relocation_stance(conn: sqlite3.Connection) -> None:
    """``job_text=None`` (no post) and a real post take different paths in ``answer_form``."""
    field = FormField(label="Are you willing to relocate?", type="radio", options=["Yes", "No"])
    post = JobPost("Backend Intern in Makati. " + POST_BODY, "opener")
    assert answers.wants_relocation_stance(field, job_text_of(post))
    assert not answers.wants_relocation_stance(field, job_text_of(None))
