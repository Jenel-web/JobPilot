"""Tests for the on-page Fill panel (``engine/forms/panel.py``): the bridge's guards and the panel's states.

Mock mode, headless test browser, saved pages only, no engine: the API is a fake that records every call.
The panel runs with an OPEN shadow root here so the tests can look inside; the real browser uses a closed one
(checked by its own test).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from engine.forms import panel
from engine.forms.panel import PanelBridge, fill_body, install_panel, panel_script

TOKEN = "test-token-123"
FORM = (
    "<html><head><title>Apply – Acme</title></head><body><header style='height:40px'>Acme Careers</header>"
    "<form onsubmit='event.preventDefault(); window.__submitted = true'>"
    "<label>Full name <input name=a></label><label>Email <input name=b></label><label>Why us? <textarea name=c></textarea></label>"
    "<button type=submit>Submit application</button></form></body></html>"
)
ARTICLE = "<html><body><h1>About Acme</h1><p>We make things.</p><input type=search placeholder=Search></body></html>"
POST = {"label": "Junior Java Developer – Acme (opener tab)", "source": "opener tab", "tab_title": "Junior Java Developer – Acme", "tab_url": "https://jobs.test/job/1"}
TABS = [{"index": 0, "title": "Junior Java Developer – Acme", "url": "https://jobs.test/job/1"}]
RESULT = {"url": "https://jobs.test/apply", "fill_id": 9, "filled": 12, "needs_you": 1, "failed": 0, "flagged": 2, "flagged_fields": [],
          "screenshot_path": None, "post": POST, "tabs": TABS, "resume_id": "A", "resume_reason": "Java", "unknown_ids": [5], "messages": []}


@dataclass
class FakeApi:
    """Stands in for the engine API. ``job_polls`` = how many GET /fill/{id} answers say "running" before "done"."""

    post: dict[str, Any] | None = field(default_factory=lambda: dict(POST))
    down: bool = False
    fill_error: str | None = None
    job_polls: int = 1
    calls: list[tuple[str, str, Any]] = field(default_factory=list)

    def __call__(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        self.calls.append((method, path, body))
        if self.down:
            return {"ok": False, "code": "engine_unreachable", "error": "The engine isn't running. Start it with: python -m engine.api"}
        if path == "/status":
            return {"ok": True, "data": {"run_mode": "dry_run", "browser_open": True, "page_url": "x", "page_title": "x", "fill_running": False, "fill_job_id": None}}
        if path == "/jobpost":
            return {"ok": True, "data": {"page_url": "https://jobs.test/apply", "post": self.post, "tabs": TABS}}
        if path == "/fill":
            if self.fill_error:
                return {"ok": False, "status": 409, "code": "index_not_ready", "error": self.fill_error}
            return {"ok": True, "data": {"job_id": "abc123", "status": "running"}}
        if path.startswith("/fill/"):
            self.job_polls -= 1
            if self.job_polls >= 0:
                return {"ok": True, "data": {"job_id": "abc123", "status": "running", "result": None, "error": None}}
            return {"ok": True, "data": {"job_id": "abc123", "status": "done", "result": RESULT, "error": None}}
        return {"ok": False, "error": "unexpected"}

    def paths(self) -> list[str]:
        return [p for _, p, _ in self.calls]


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture
def context(browser: Browser, api: FakeApi) -> Iterator[BrowserContext]:
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    install_panel(ctx, TOKEN, api=api, shadow_mode="open")
    yield ctx
    ctx.close()


def open_page(context: BrowserContext, html: str = FORM, url: str = "https://jobs.test/apply") -> Page:
    page = context.new_page()
    page.route(url, lambda route: route.fulfill(body=html, content_type="text/html"))
    page.goto(url)
    return page


def panel_text(page: Page) -> str:
    return page.locator("jobpilot-panel .panel, jobpilot-panel .tab").first.inner_text()


# ---- what the page and the website can (not) do -------------------------------------------------------------------


def test_the_website_cannot_see_the_bridge(context: BrowserContext) -> None:
    page = open_page(context)
    assert page.evaluate("typeof window.__jobpilot_bridge") == "undefined"
    assert page.evaluate("() => { const f = document.createElement('iframe'); document.body.appendChild(f); return typeof f.contentWindow.__jobpilot_bridge; }") == "undefined"


def test_the_real_panel_uses_a_closed_shadow_root(browser: Browser, api: FakeApi) -> None:
    ctx = browser.new_context()
    try:
        install_panel(ctx, TOKEN, api=api)  # the default, as in the bot's browser
        page = open_page(ctx)
        page.wait_for_function("!!document.querySelector('jobpilot-panel')")
        assert page.evaluate("document.querySelector('jobpilot-panel').shadowRoot") is None  # the site cannot look inside
    finally:
        ctx.close()


def test_a_click_faked_by_a_script_is_ignored(context: BrowserContext, api: FakeApi) -> None:
    page = open_page(context)
    page.locator("jobpilot-panel [data-act=fill]").wait_for()
    page.evaluate("document.querySelector('jobpilot-panel').shadowRoot.querySelector('[data-act=fill]').click()")
    page.wait_for_timeout(300)
    assert "/fill" not in api.paths()


# ---- the bridge's guards (no browser) -------------------------------------------------------------------------------


class FakePage:
    url = "https://jobs.test/apply"
    main_frame = object()


def source(frame: object | None = None) -> dict[str, Any]:
    page = FakePage()
    return {"page": page, "frame": frame if frame is not None else page.main_frame}


def test_a_call_without_the_right_token_is_refused_and_reaches_no_api(api: FakeApi) -> None:
    bridge = PanelBridge(TOKEN, api)
    for payload in ({"token": "guess", "action": "fill"}, {"action": "fill"}, "fill", None):
        assert bridge(source(), payload)["code"] == "refused"
    assert api.calls == []


def test_a_call_from_an_embedded_frame_is_refused_even_with_the_token(api: FakeApi) -> None:
    assert PanelBridge(TOKEN, api)(source(frame=object()), {"token": TOKEN, "action": "status"})["code"] == "refused"
    assert api.calls == []


def test_only_four_actions_exist(api: FakeApi) -> None:
    bridge = PanelBridge(TOKEN, api)
    for action in ("submit", "navigate", "answers", "delete"):
        assert bridge(source(), {"token": TOKEN, "action": action})["code"] == "refused"
    assert bridge(source(), {"token": TOKEN, "action": "job", "data": {"job_id": "../answers"}})["code"] == "refused"
    assert api.calls == []


def test_the_page_to_fill_is_always_the_panels_own_page() -> None:
    body = fill_body({"tab": "https://other.test", "resume": "B", "post_tab_url": "https://jobs.test/job/1", "evil": 1}, "https://jobs.test/apply")
    assert body == {"tab": "https://jobs.test/apply", "post_tab_url": "https://jobs.test/job/1"}
    assert fill_body({"no_resume": True, "post_text": "x"}, "https://a.test") == {"tab": "https://a.test", "no_resume": True}
    assert fill_body({"no_resume": "yes"}, "https://a.test") == {"tab": "https://a.test"}  # only a real true counts


def test_the_panel_script_takes_its_colours_from_tokens_css() -> None:
    script = panel_script(TOKEN)
    assert "--jp-brand: #1F6B4F;" in script and "closed" in script
    for banned in (".submit(", "requestSubmit", "dispatchEvent", ".click()"):
        assert banned not in script, f"the panel script must not contain {banned!r}"
    with pytest.raises(ValueError):
        panel_script(TOKEN, shadow_mode="none")


# ---- the panel's states ----------------------------------------------------------------------------------------------


def test_on_an_application_form_it_opens_by_itself_ready_with_the_job_post(context: BrowserContext, api: FakeApi) -> None:
    page = open_page(context)
    page.locator("jobpilot-panel [data-act=fill]").wait_for()
    text = panel_text(page)
    assert "DRY RUN" in text and "Junior Java Developer – Acme (opener tab)" in text and "Change" in text
    assert "click Submit yourself" in text
    assert api.paths() == ["/status", "/jobpost"]


def test_on_other_pages_it_stays_a_collapsed_tab_and_asks_nothing(context: BrowserContext, api: FakeApi) -> None:
    page = open_page(context, ARTICLE, "https://jobs.test/about")
    page.locator("jobpilot-panel .tab").wait_for()
    page.wait_for_timeout(300)
    assert api.calls == []  # collapsed: no engine calls, no reads logged
    page.locator("jobpilot-panel .tab").click()
    page.locator("jobpilot-panel .panel").wait_for()
    assert "/status" in api.paths()


def test_fill_this_page_runs_the_same_fill_as_the_dashboard_and_shows_the_result(context: BrowserContext, api: FakeApi) -> None:
    page = open_page(context)
    page.locator("jobpilot-panel [data-act=fill]").click()
    page.locator("jobpilot-panel >> text=Filling").first.wait_for()
    page.locator("jobpilot-panel >> text=Done. Review the form").wait_for(timeout=10000)
    text = panel_text(page)
    assert "12 filled" in text and "1 new question" in text and "Resume A" in text and "2 flagged" in text
    assert "Open dashboard" in text and "Fill this page again" in text
    fills = [b for m, p, b in api.calls if p == "/fill"]
    assert fills == [{"tab": "https://jobs.test/apply"}]  # this page, finder decides the post
    assert page.evaluate("window.__submitted === true") is False


def test_job_post_not_found_offers_tabs_paste_and_fill_without_resume(browser: Browser) -> None:
    api = FakeApi(post=None)
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    try:
        install_panel(ctx, TOKEN, api=api, shadow_mode="open")
        page = open_page(ctx)
        page.locator("jobpilot-panel >> text=Job post not found.").wait_for()
        use = page.locator("jobpilot-panel [data-act=use]")
        assert use.is_disabled()
        page.locator("jobpilot-panel [data-act=pick]").click()
        page.locator("jobpilot-panel [data-act=use]").click()
        page.locator("jobpilot-panel >> text=Done. Review the form").wait_for(timeout=10000)
        page.locator("jobpilot-panel [data-act=change]").click()
        page.locator("jobpilot-panel [data-act=noresume]").click()
        page.wait_for_timeout(500)
        fills = [b for m, p, b in api.calls if p == "/fill"]
        assert fills == [
            {"tab": "https://jobs.test/apply", "post_tab_url": "https://jobs.test/job/1"},
            {"tab": "https://jobs.test/apply", "no_resume": True},
        ]
    finally:
        ctx.close()


def test_pasted_text_is_sent_as_the_job_post(browser: Browser) -> None:
    api = FakeApi(post=None)
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    try:
        install_panel(ctx, TOKEN, api=api, shadow_mode="open")
        page = open_page(ctx)
        page.locator("jobpilot-panel textarea").fill("Backend Intern. Responsibilities: Python.")
        page.locator("jobpilot-panel [data-act=use]").click()
        page.wait_for_timeout(500)
        assert [b for m, p, b in api.calls if p == "/fill"] == [{"tab": "https://jobs.test/apply", "post_text": "Backend Intern. Responsibilities: Python."}]
    finally:
        ctx.close()


def test_engine_down_and_fill_errors_are_shown_in_plain_words(browser: Browser) -> None:
    for api, words in ((FakeApi(down=True), "The engine isn't running"), (FakeApi(fill_error="The search index is empty."), "The search index is empty.")):
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        try:
            install_panel(ctx, TOKEN, api=api, shadow_mode="open")
            page = open_page(ctx)
            if not api.down:
                page.locator("jobpilot-panel [data-act=fill]").click()
            page.locator(f"jobpilot-panel >> text={words}").wait_for(timeout=5000)
            assert "Try again" in panel_text(page)
        finally:
            ctx.close()


def test_it_never_covers_the_sites_submit_button(context: BrowserContext) -> None:
    html = FORM.replace("<button type=submit>", "<button type=submit style='position:fixed;top:60px;right:30px;width:200px;height:40px'>")
    page = open_page(context, html)
    page.locator("jobpilot-panel .panel").wait_for()
    page.wait_for_timeout(200)
    panel_box = page.locator("jobpilot-panel .panel").bounding_box()
    submit_box = page.locator("button[type=submit]").bounding_box()
    assert panel_box and submit_box
    apart = panel_box["x"] + panel_box["width"] <= submit_box["x"] or submit_box["x"] + submit_box["width"] <= panel_box["x"] \
        or panel_box["y"] + panel_box["height"] <= submit_box["y"] or submit_box["y"] + submit_box["height"] <= panel_box["y"]
    assert apart, f"panel {panel_box} covers Submit {submit_box}"


def test_it_collapses_out_of_the_way(context: BrowserContext) -> None:
    page = open_page(context)
    page.locator("jobpilot-panel [data-act=min]").click()
    page.locator("jobpilot-panel .tab").wait_for()
    assert page.locator("jobpilot-panel .panel").count() == 0


def test_install_adds_the_bridge_before_the_script(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []

    class Ctx:
        pages: list[Any] = []

        def expose_binding(self, name: str, fn: Any) -> None:
            order.append(f"binding:{name}")

        def add_init_script(self, script: str) -> None:
            order.append("script")

    install_panel(Ctx(), TOKEN, api=FakeApi())
    assert order == [f"binding:{panel.BRIDGE_NAME}", "script"]
