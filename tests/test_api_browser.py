"""Tests for the stage 4.5 engine additions: ``GET /status``, ``GET /jobpost``, ``GET /fills/{id}/screenshot``,
the new fill choices (``post_tab_url``, ``no_resume``) and the orchestrator's ``no_resume``.

Mock mode, no network, no bot browser: the readers that would attach to the bot's browser are swapped on
``app.state`` for fakes. Two tests use a headless test browser to prove ``post_from_tab_url`` and ``no_resume``
really work on a page.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Browser, Page
from tests.test_api_fill import Stub, wait_for_end
from tests.test_orchestrator import POST_TEXT, Spy, browser, conn, page, run, spy  # noqa: F401  (fixtures)

from engine import api, api_browser, api_fill, db
from engine.api_models import FillIn, FillPostOut, JobPostPreviewOut, TabOut
from engine.forms.jobfinder import post_from_tab_url
from engine.settings import Settings

MOCK = Settings(run_mode="mock")
LOCAL = "http://127.0.0.1:8000"
PNG = b"\x89PNG\r\n\x1a\nfake image bytes"


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(api_fill, "browser_is_open", lambda: True)
    monkeypatch.setattr(api_fill, "check_ready", lambda conn, settings: None)
    app = api.create_app(MOCK, db_path=tmp_path / "test.db", answers_path=tmp_path / "answers.json")
    app.state.fill_runner = Stub()
    app.state.page_reader = lambda: ("https://jobs.test/apply", "Apply – Acme")
    app.state.screenshots_dir = tmp_path / "shots"
    (tmp_path / "shots").mkdir()
    return app


@pytest.fixture
def client(app) -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(app, base_url=LOCAL)


def add_fill(db_path: Path, screenshot: str | None) -> int:
    conn = db.connect(db_path)
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO fills (url, filled_count, flagged_count, filled_fields, flagged_fields, screenshot_path, status) "
                "VALUES ('https://jobs.test/apply', 1, 0, '[]', '[]', ?, 'filled')",
                (screenshot,),
            )
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


# ---- GET /status ----------------------------------------------------------------------------------------------


def test_status_shows_mode_and_the_page_you_are_looking_at(client: TestClient) -> None:
    body = client.get("/status").json()
    assert body == {
        "run_mode": "mock", "browser_open": True, "page_url": "https://jobs.test/apply", "page_title": "Apply – Acme",
        "fill_running": False, "fill_job_id": None, "submit_offer": None,
    }


def test_status_with_the_browser_closed_reads_no_page(client: TestClient, app, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(api_fill, "browser_is_open", lambda: False)
    app.state.page_reader = lambda: pytest.fail("a closed browser must not be read")
    body = client.get("/status").json()
    assert (body["browser_open"], body["page_url"], body["page_title"]) == (False, None, None)


def test_status_with_no_web_page_open_is_not_an_error(client: TestClient, app) -> None:  # type: ignore[no-untyped-def]
    def no_page() -> tuple[str, str]:
        raise RuntimeError("No web page is open in the bot's browser.")

    app.state.page_reader = no_page
    response = client.get("/status")
    assert response.status_code == 200 and response.json()["page_url"] is None


def test_status_during_a_fill_names_the_job_and_leaves_the_browser_alone(client: TestClient, app) -> None:  # type: ignore[no-untyped-def]
    gate = threading.Event()
    app.state.fill_runner = Stub(gate=gate)
    job_id = client.post("/fill").json()["job_id"]
    app.state.page_reader = lambda: pytest.fail("the page must not be read while a fill owns the browser")
    try:
        body = client.get("/status").json()
        assert body["fill_running"] is True and body["fill_job_id"] == job_id and body["page_url"] is None
    finally:
        gate.set()
    wait_for_end(client, job_id)
    app.state.page_reader = lambda: ("https://jobs.test/apply", "Apply – Acme")
    after = client.get("/status").json()
    assert after["fill_job_id"] is None and after["page_url"] == "https://jobs.test/apply"


def test_status_never_changes_the_mode(client: TestClient) -> None:
    assert client.post("/status").status_code == 405  # read only: there is nothing to send
    assert client.get("/status").json()["run_mode"] == "mock"


# ---- GET /jobpost -----------------------------------------------------------------------------------------------


def preview(**kw: Any) -> JobPostPreviewOut:
    base: dict[str, Any] = dict(
        page_url="https://globex.test/apply",
        post=FillPostOut(label="Backend Intern – Globex (opener tab)", source="opener tab", tab_title="Backend Intern – Globex",
                         tab_url="https://globex.test/jobs/1"),
        tabs=[TabOut(index=0, title="Backend Intern – Globex", url="https://globex.test/jobs/1")],
    )
    return JobPostPreviewOut(**{**base, **kw})


def test_jobpost_returns_the_post_and_the_tabs(client: TestClient, app) -> None:  # type: ignore[no-untyped-def]
    seen: list[Settings] = []
    app.state.post_previewer = lambda conn, settings: (seen.append(settings), preview())[1]
    body = client.get("/jobpost").json()
    assert body["post"]["tab_title"] == "Backend Intern – Globex" and body["tabs"][0]["url"] == "https://globex.test/jobs/1"
    assert seen == [MOCK]


def test_jobpost_not_found_is_a_normal_answer(client: TestClient, app) -> None:  # type: ignore[no-untyped-def]
    app.state.post_previewer = lambda conn, settings: preview(post=None)
    response = client.get("/jobpost")
    assert response.status_code == 200 and response.json()["post"] is None


def test_jobpost_with_the_browser_closed_is_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_fill, "browser_is_open", lambda: False)
    response = client.get("/jobpost")
    assert response.status_code == 503 and response.json()["code"] == "browser_closed"


def test_jobpost_with_no_web_page_is_409_no_page(client: TestClient, app) -> None:  # type: ignore[no-untyped-def]
    def fail(conn: sqlite3.Connection, settings: Settings) -> JobPostPreviewOut:
        raise RuntimeError("No web page is open in the bot's browser.")

    app.state.post_previewer = fail
    response = client.get("/jobpost")
    assert response.status_code == 409 and response.json()["code"] == "no_page"


def test_jobpost_is_refused_while_a_fill_runs(client: TestClient, app) -> None:  # type: ignore[no-untyped-def]
    gate = threading.Event()
    app.state.fill_runner = Stub(gate=gate)
    job_id = client.post("/fill").json()["job_id"]
    app.state.post_previewer = lambda conn, settings: pytest.fail("must not read tabs during a fill")
    try:
        response = client.get("/jobpost")
        assert response.status_code == 409 and response.json()["code"] == "fill_running"
    finally:
        gate.set()
    wait_for_end(client, job_id)


# ---- GET /fills/{id}/screenshot -------------------------------------------------------------------------------


def test_screenshot_sends_the_png_of_that_fill(client: TestClient, app, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    shot = tmp_path / "shots" / "fill-1.png"
    shot.write_bytes(PNG)
    fill_id = add_fill(tmp_path / "test.db", str(shot))
    response = client.get(f"/fills/{fill_id}/screenshot")
    assert response.status_code == 200 and response.headers["content-type"] == "image/png" and response.content == PNG


@pytest.mark.parametrize("stored", [None, "", "MISSING"])
def test_no_screenshot_is_a_404(client: TestClient, tmp_path: Path, stored: str | None) -> None:
    path = str(tmp_path / "shots" / "gone.png") if stored == "MISSING" else stored
    fill_id = add_fill(tmp_path / "test.db", path)
    response = client.get(f"/fills/{fill_id}/screenshot")
    assert response.status_code == 404 and response.json()["code"] == "not_found"


def test_an_unknown_fill_is_a_404(client: TestClient) -> None:
    assert client.get("/fills/999/screenshot").status_code == 404


def test_a_stored_path_outside_the_screenshots_folder_is_never_sent(client: TestClient, tmp_path: Path) -> None:
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"\x89PNG not yours")
    for stored in (str(secret), str(tmp_path / "shots" / ".." / "secret.png")):
        fill_id = add_fill(tmp_path / "test.db", stored)
        response = client.get(f"/fills/{fill_id}/screenshot")
        assert response.status_code == 404 and b"not yours" not in response.content


def test_a_file_that_is_not_a_png_is_never_sent(client: TestClient, tmp_path: Path) -> None:
    other = tmp_path / "shots" / "answers.json"
    other.write_text('{"phone": "x"}', encoding="utf-8")
    fill_id = add_fill(tmp_path / "test.db", str(other))
    assert client.get(f"/fills/{fill_id}/screenshot").status_code == 404


def test_safe_screenshot_reads_a_relative_path_from_the_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "data" / "screenshots").mkdir(parents=True)
    (tmp_path / "data" / "screenshots" / "a.png").write_bytes(PNG)
    monkeypatch.setattr(api_browser, "ROOT", tmp_path)
    assert api_browser.safe_screenshot("data/screenshots/a.png", tmp_path / "data" / "screenshots") == (tmp_path / "data" / "screenshots" / "a.png").resolve()
    assert api_browser.safe_screenshot("data/screenshots/../../x.png", tmp_path / "data" / "screenshots") is None


def test_a_foreign_host_cannot_read_status_or_screenshots(app) -> None:  # type: ignore[no-untyped-def]
    evil = TestClient(app, base_url="http://evil.test")
    assert evil.get("/status").status_code == 403
    assert evil.get("/fills/1/screenshot").status_code == 403


# ---- the new fill choices -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("body", [
    {"post_text": "a post", "post_tab_url": "https://x.test/job"},
    {"no_resume": True, "resume": "A"},
    {"no_resume": True, "post_text": "a post"},
    {"no_resume": True, "post_tab_url": "https://x.test/job"},
])
def test_conflicting_choices_are_refused_and_nothing_starts(client: TestClient, app, body: dict) -> None:  # type: ignore[no-untyped-def]
    assert client.post("/fill", json=body).status_code == 422
    assert app.state.fill_runner.calls == []


def test_the_new_choices_reach_the_runner(client: TestClient, app) -> None:  # type: ignore[no-untyped-def]
    wait_for_end(client, client.post("/fill", json={"post_tab_url": "https://x.test/job"}).json()["job_id"])
    wait_for_end(client, client.post("/fill", json={"no_resume": True}).json()["job_id"])
    sent = [call[2] for call in app.state.fill_runner.calls]
    assert sent[0].post_tab_url == "https://x.test/job" and sent[0].no_resume is False
    assert sent[1].no_resume is True and sent[1].post_tab_url is None


def test_perform_fill_hands_no_resume_and_the_picked_tab_to_the_orchestrator(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def fake_fill(conn: Any, page: Any, **kw: Any) -> Any:
        seen.update(kw)
        raise RuntimeError("stop here")

    monkeypatch.setattr(api_fill, "fill_current_page", fake_fill)
    monkeypatch.setattr(api_fill, "post_from_tab_url", lambda page, url: f"POST FROM {url}")
    with pytest.raises(RuntimeError, match="stop here"):
        api_fill.perform_fill(None, None, MOCK, FillIn(post_tab_url="https://x.test/job"), tmp_path / "s.png")  # type: ignore[arg-type]
    assert seen["post"] == "POST FROM https://x.test/job" and seen["no_resume"] is False
    with pytest.raises(RuntimeError, match="stop here"):
        api_fill.perform_fill(None, None, MOCK, FillIn(no_resume=True), tmp_path / "s.png")  # type: ignore[arg-type]
    assert seen["post"] is None and seen["no_resume"] is True


def test_a_picked_tab_that_closed_stops_the_fill_with_a_plain_message(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(api_fill, "post_from_tab_url", lambda page, url: None)
    monkeypatch.setattr(api_fill, "fill_current_page", lambda *a, **kw: pytest.fail("must not fill without the chosen post"))
    with pytest.raises(RuntimeError, match="closed or changed"):
        api_fill.perform_fill(None, None, MOCK, FillIn(post_tab_url="https://x.test/job"), tmp_path / "s.png")  # type: ignore[arg-type]


def test_post_from_tab_url_reads_the_tab_with_that_exact_address(browser: Browser) -> None:  # noqa: F811
    context = browser.new_context()
    try:
        form = context.new_page()
        form.set_content("<form><input name=a></form>")
        job = context.new_page()
        job.route("https://globex.test/jobs/1", lambda route: route.fulfill(
            body="<html><head><title>Backend Intern</title></head><body><main>" + POST_TEXT + "</main></body></html>",
            content_type="text/html"))
        job.goto("https://globex.test/jobs/1")
        post = post_from_tab_url(form, "https://globex.test/jobs/1")
        assert post is not None and "Python services" in post.text and post.source == "chosen" and post.tab_title == "Backend Intern"
        assert post_from_tab_url(form, "https://globex.test/jobs/2") is None  # no such tab
    finally:
        context.close()


# ---- the orchestrator's no_resume ---------------------------------------------------------------------------------


def test_no_resume_fills_the_form_but_looks_for_no_post_and_uploads_nothing(
    conn: sqlite3.Connection, page: Page, spy: Spy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    from engine.forms import orchestrator

    monkeypatch.setattr(orchestrator, "find_job_post", lambda *a, **kw: pytest.fail("no_resume must not look for a post"))
    out = run(conn, page, tmp_path, no_resume=True)
    assert page.input_value("input[name=fn]") == "Maria"  # the rest of the form is filled
    assert page.eval_on_selector("input[name=cv]", "e => e.files.length") == 0  # nothing uploaded
    assert spy.pick_texts == [] and out.resume_id is None and out.post is None
    assert any("without a resume" in m for m in out.messages)
    row = conn.execute("SELECT resume_id, status FROM fills WHERE id = ?", (out.fill_id,)).fetchone()
    assert (row["resume_id"], row["status"]) == (None, "filled")


def test_no_resume_with_a_post_or_resume_is_refused(conn: sqlite3.Connection, page: Page, spy: Spy, tmp_path: Path) -> None:  # noqa: F811
    from engine.forms.jobfinder import JobPost

    with pytest.raises(ValueError):
        run(conn, page, tmp_path, no_resume=True, resume_id="A")
    with pytest.raises(ValueError):
        run(conn, page, tmp_path, no_resume=True, post=JobPost(POST_TEXT, "pasted"))
    assert page.input_value("input[name=fn]") == ""  # refused before anything was typed
