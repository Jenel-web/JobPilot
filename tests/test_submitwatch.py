"""Tests for passive submit detection (``engine/forms/submitwatch.py``) and its place in the API.

No browser, no network: the watcher gets a fake ``read`` (what the tab shows) and a fake clock, and is driven with
``check_once()``. The rule under test: it only OFFERS "Looks submitted. Mark it?"; it never marks anything.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.test_api_fill import Stub, make_result, wait_for_end

from engine import api, api_fill, db
from engine.forms import submitwatch
from engine.forms.submitwatch import SubmitWatcher, TabView, looks_submitted
from engine.settings import ROOT, Settings

FORM_URL = "https://jobs.test/apply/42"


def add_fill(db_path: Path, title: str = "Backend Intern", company: str = "Globex") -> int:
    conn = db.connect(db_path)
    try:
        db.init_db(conn)
        with conn:
            cur = conn.execute(
                "INSERT INTO fills (url, job_title, company, filled_count, flagged_count, filled_fields, flagged_fields, status) "
                "VALUES (?, ?, ?, 3, 0, '[]', '[]', 'filled')", (FORM_URL, title, company),
            )
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


def status_of(db_path: Path, fill_id: int) -> str:
    conn = db.connect(db_path)
    try:
        return conn.execute("SELECT status FROM fills WHERE id = ?", (fill_id,)).fetchone()["status"]
    finally:
        conn.close()


class Tab:
    """A fake tab: set ``view`` to what it shows; ``None`` = closed."""

    def __init__(self, view: TabView | None) -> None:
        self.view = view
        self.reads = 0

    def __call__(self, target_id: str) -> TabView | None:
        self.reads += 1
        return self.view


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


# ---- the decision (by code) -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "Thank you for applying! We will be in touch.",
    "Thanks for your application to Globex.",
    "Your application has been received.",
    "Application submitted",
    "We've received your application and will review it.",
    "You have successfully applied for Backend Intern.",
    "Your response has been recorded.",  # Google Forms
])
def test_confirmation_words_are_a_strong_offer(text: str) -> None:
    found = looks_submitted(FORM_URL, TabView(FORM_URL, text, 0))
    assert found is not None and found[1] is True and "The page now says" in found[0]


@pytest.mark.parametrize("text", [
    "Thank you for your interest in Globex. Apply below.",  # job posts say this BEFORE you apply
    "Submit your application",
    "Application form",
    "Please complete your application.",
])
def test_ordinary_form_words_are_not_an_offer(text: str) -> None:
    assert looks_submitted(FORM_URL, TabView(FORM_URL, text, 8)) is None


def test_a_new_page_with_no_form_is_a_weak_offer() -> None:
    assert looks_submitted(FORM_URL, TabView("https://jobs.test/done", "All set.", 0)) == ("The page changed after filling and no form is left.", False)


def test_the_next_step_of_a_multi_step_form_is_not_an_offer() -> None:
    assert looks_submitted(FORM_URL, TabView("https://jobs.test/apply/42?step=2", "Step 2 of 3", 6)) is None


def test_a_moved_fragment_is_the_same_page() -> None:
    assert looks_submitted(FORM_URL, TabView(FORM_URL + "#review", "Review your answers", 0)) is None


# ---- the watcher ------------------------------------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


def test_a_confirmation_becomes_an_offer_is_logged_and_watching_stops(db_path: Path) -> None:
    fill_id = add_fill(db_path)
    tab = Tab(TabView(FORM_URL, "Name Email", 5))
    w = SubmitWatcher(db_path, read=tab, start_thread=False)
    w.watch(fill_id, "T1", FORM_URL)
    w.check_once()
    assert w.offers() == [] and w.watching == [fill_id]
    tab.view = TabView("https://jobs.test/thanks", "Thank you for applying!", 0)
    w.check_once()
    [offer] = w.offers()
    assert offer.fill_id == fill_id and offer.strong and w.watching == []
    assert status_of(db_path, fill_id) == "filled"  # offered, NEVER marked
    conn = db.connect(db_path)
    try:
        logged = conn.execute("SELECT kind, details FROM action_log WHERE fill_id = ?", (fill_id,)).fetchall()
    finally:
        conn.close()
    assert [(r["kind"], "offered, not marked" in r["details"]) for r in logged] == [("read", True)]


def test_a_weak_offer_keeps_watching_and_turns_strong(db_path: Path) -> None:
    fill_id = add_fill(db_path)
    tab = Tab(TabView("https://jobs.test/next", "Loading", 0))
    w = SubmitWatcher(db_path, read=tab, start_thread=False)
    w.watch(fill_id, "T1", FORM_URL)
    w.check_once()
    assert not w.offers()[0].strong and w.watching == [fill_id]
    tab.view = TabView("https://jobs.test/next", "Application received", 0)
    w.check_once()
    assert w.offers()[0].strong and w.watching == []


def test_a_closed_tab_stops_watching_without_an_offer(db_path: Path) -> None:
    fill_id = add_fill(db_path)
    w = SubmitWatcher(db_path, read=Tab(None), start_thread=False)
    w.watch(fill_id, "T1", FORM_URL)
    w.check_once()
    assert w.watching == [] and w.offers() == []


def test_a_page_you_already_marked_is_not_watched_or_offered(db_path: Path) -> None:
    fill_id = add_fill(db_path)
    tab = Tab(TabView(FORM_URL, "Thank you for applying", 0))
    w = SubmitWatcher(db_path, read=tab, start_thread=False)
    w.watch(fill_id, "T1", FORM_URL)
    conn = db.connect(db_path)
    with conn:
        conn.execute("UPDATE fills SET status = 'abandoned' WHERE id = ?", (fill_id,))
    conn.close()
    w.check_once()
    assert w.watching == [] and w.offers() == [] and tab.reads == 0


def test_watching_stops_after_30_minutes(db_path: Path) -> None:
    fill_id = add_fill(db_path)
    clock = Clock()
    tab = Tab(TabView(FORM_URL, "Name Email", 5))
    w = SubmitWatcher(db_path, read=tab, clock=clock, start_thread=False)
    w.watch(fill_id, "T1", FORM_URL)
    clock.now = submitwatch.WATCH_FOR_S + 1
    w.check_once()
    assert w.watching == [] and tab.reads == 0


def test_no_tab_id_means_no_watching(db_path: Path) -> None:
    w = SubmitWatcher(db_path, read=Tab(None), start_thread=False)
    w.watch(add_fill(db_path), "", FORM_URL)
    assert w.watching == []


def test_the_watcher_code_only_reads() -> None:
    source = (ROOT / "engine" / "forms" / "submitwatch.py").read_text(encoding="utf-8")
    for banned in (".click(", ".fill(", ".press(", ".type(", "dispatch_event", "add_init_script", "expose_binding", "mark_fill", "goto("):
        assert banned not in source, f"submitwatch.py must not contain {banned!r}"


# ---- in the API: offered in /status, cleared when you decide -----------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(api_fill, "browser_is_open", lambda: False)
    monkeypatch.setattr(api_fill, "check_ready", lambda conn, settings: None)
    app = api.create_app(Settings(run_mode="mock"), db_path=tmp_path / "test.db", answers_path=tmp_path / "answers.json")
    app.state.submit_watcher = SubmitWatcher(tmp_path / "test.db", read=Tab(TabView(FORM_URL, "Application received", 0)), start_thread=False)
    return TestClient(app, base_url="http://127.0.0.1:8000")


def test_a_fill_starts_watching_and_the_offer_shows_in_status(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fill_id = add_fill(tmp_path / "test.db")
    monkeypatch.setattr(api_fill, "browser_is_open", lambda: True)
    client.app.state.fill_runner = Stub(result=make_result(fill_id=fill_id, url=FORM_URL, target_id="T1"))  # type: ignore[attr-defined]
    wait_for_end(client, client.post("/fill").json()["job_id"])
    watcher = client.app.state.submit_watcher  # type: ignore[attr-defined]
    assert watcher.watching == [fill_id]
    monkeypatch.setattr(api_fill, "browser_is_open", lambda: False)
    watcher.check_once()
    offer = client.get("/status").json()["submit_offer"]
    assert offer == {"fill_id": fill_id, "title": "Backend Intern – Globex", "reason": 'The page now says "Application received".', "strong": True}
    assert status_of(tmp_path / "test.db", fill_id) == "filled"


def test_the_tab_id_is_never_sent_to_the_dashboard(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_fill, "browser_is_open", lambda: True)
    client.app.state.fill_runner = Stub(result=make_result(target_id="SECRET-TAB-ID"))  # type: ignore[attr-defined]
    job = wait_for_end(client, client.post("/fill").json()["job_id"])
    assert "SECRET-TAB-ID" not in str(job) and "target_id" not in job["result"]


def test_marking_the_page_clears_the_offer(client: TestClient, tmp_path: Path) -> None:
    fill_id = add_fill(tmp_path / "test.db")
    watcher = client.app.state.submit_watcher  # type: ignore[attr-defined]
    watcher.watch(fill_id, "T1", FORM_URL)
    watcher.check_once()
    assert client.get("/status").json()["submit_offer"]["fill_id"] == fill_id
    assert client.post(f"/fills/{fill_id}/status", json={"status": "submitted"}).status_code == 200
    assert watcher.offers() == [] and watcher.watching == []  # the endpoint itself forgets it (before any /status call)
    assert client.get("/status").json()["submit_offer"] is None


def test_a_page_marked_elsewhere_drops_its_offer_from_status(client: TestClient, tmp_path: Path) -> None:
    fill_id = add_fill(tmp_path / "test.db")
    watcher = client.app.state.submit_watcher  # type: ignore[attr-defined]
    watcher.watch(fill_id, "T1", FORM_URL)
    watcher.check_once()
    conn = db.connect(tmp_path / "test.db")
    with conn:
        conn.execute("UPDATE fills SET status = 'abandoned' WHERE id = ?", (fill_id,))
    conn.close()
    assert client.get("/status").json()["submit_offer"] is None


def test_the_background_thread_runs_and_stops_by_itself(db_path: Path) -> None:
    fill_id = add_fill(db_path)
    seen = threading.Event()

    def read(target_id: str) -> TabView:
        seen.set()
        return TabView(FORM_URL, "Thank you for applying", 0)

    w = SubmitWatcher(db_path, read=read, every=0.01)
    w.watch(fill_id, "T1", FORM_URL)
    assert seen.wait(5)
    for _ in range(200):
        if w.watching == []:
            break
        threading.Event().wait(0.01)
    assert w.watching == [] and w.offers()[0].strong
