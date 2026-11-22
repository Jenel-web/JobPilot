"""Tests for engine/api_fill.py: POST /fill and GET /fill/{job_id} (stage 4.4e).

Mock mode, no network, and no bot browser. Most tests swap the job's runner for a stub so they check the JOB
logic (start, running, done, error, one at a time). Two tests run the real fill chain on a tiny inline page in a
headless test browser, with the answer engine and resume picker stubbed, to prove the endpoints reach the
orchestrator and that nothing is clicked.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.test_filler import bad_clicks, install_recorder
from tests.test_orchestrator import EMAIL, FORM, NAME, PHONE, POST_TEXT, spy  # noqa: F401  (spy is a fixture)

from engine import api, api_fill, db, rag
from engine.ai import AIError
from engine.api_models import FillIn, FillResultOut
from engine.settings import Settings

MOCK = Settings(run_mode="mock")
LOCAL = "http://127.0.0.1:8000"


def make_result(**kw: Any) -> FillResultOut:
    base: dict[str, Any] = dict(
        url="https://jobs.test/apply", fill_id=1, filled=5, needs_you=1, failed=0, flagged=2, flagged_fields=[],
        screenshot_path=None, post=None, tabs=[], resume_id="B", resume_reason="backend projects", unknown_ids=[], messages=[],
    )
    return FillResultOut(**{**base, **kw})


@dataclass
class Stub:
    """A runner that records what it was given and can be told to wait, fail or return a result."""

    calls: list[tuple[Any, Settings, FillIn]] = field(default_factory=list)
    gate: threading.Event | None = None  # if set, the job waits here: it stays "running" until the test opens it
    error: Exception | None = None
    result: FillResultOut = field(default_factory=make_result)

    def __call__(self, db_path: Any, settings: Settings, request: FillIn) -> FillResultOut:
        self.calls.append((db_path, settings, request))
        if self.gate is not None:
            assert self.gate.wait(timeout=10), "the test never opened the gate"
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bot browser is 'open' and the search index is 'ready' (each has its own test below)."""
    monkeypatch.setattr(api_fill, "browser_is_open", lambda: True)
    monkeypatch.setattr(api_fill, "check_ready", lambda conn, settings: None)


@pytest.fixture
def app(tmp_path: Path, ready: None):  # type: ignore[no-untyped-def]
    app = api.create_app(MOCK, db_path=tmp_path / "test.db", answers_path=tmp_path / "answers.json")
    app.state.fill_runner = Stub()
    return app


@pytest.fixture
def client(app) -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(app, base_url=LOCAL)


def wait_for_end(client: TestClient, job_id: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/fill/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.02)
    raise AssertionError("the job never finished")


# ---- starting a fill and following it ------------------------------------------------------------------------


def test_post_answers_at_once_then_the_job_finishes_with_a_summary(client: TestClient, app) -> None:  # type: ignore[no-untyped-def]
    gate = threading.Event()
    app.state.fill_runner = Stub(gate=gate)
    started = client.post("/fill")
    assert started.status_code == 202  # it did not wait for the fill
    job = started.json()
    assert job["status"] == "running" and job["result"] is None and job["finished_at"] is None
    assert client.get(f"/fill/{job['job_id']}").json()["status"] == "running"
    gate.set()
    done = wait_for_end(client, job["job_id"])
    assert done["status"] == "done" and done["error"] is None and done["finished_at"]
    assert done["result"]["filled"] == 5 and done["result"]["resume_id"] == "B" and done["result"]["fill_id"] == 1


def test_the_choices_you_send_reach_the_runner_and_settings_come_from_the_app(client: TestClient, app) -> None:  # type: ignore[no-untyped-def]
    stub = app.state.fill_runner
    job = client.post("/fill", json={"tab": "jobs.test", "post_text": "  Backend Intern in Makati  ", "resume": "A"}).json()
    wait_for_end(client, job["job_id"])
    _db, settings, request = stub.calls[0]
    assert (request.tab, request.post_text, request.resume) == ("jobs.test", "Backend Intern in Makati", "A")  # trimmed
    assert settings == MOCK


def test_an_empty_request_means_all_defaults(client: TestClient, app) -> None:  # type: ignore[no-untyped-def]
    job = client.post("/fill").json()
    wait_for_end(client, job["job_id"])
    assert app.state.fill_runner.calls[0][2] == FillIn()
    job = client.post("/fill", json={}).json()
    assert wait_for_end(client, job["job_id"])["status"] == "done"


@pytest.mark.parametrize("body", [{"resume": "C"}, {"resume": "a"}, {"post_text": ""}, {"post_text": "   "}, {"tab": ""}, {"tab": "x" * 301}])
def test_bad_choices_are_refused_and_nothing_starts(client: TestClient, app, body: dict) -> None:  # type: ignore[no-untyped-def]
    assert client.post("/fill", json=body).status_code == 422
    assert app.state.fill_runner.calls == [] and not app.state.fill_jobs.busy


def test_an_unknown_job_is_404(client: TestClient) -> None:
    response = client.get("/fill/nope")
    assert response.status_code == 404 and response.json()["code"] == "not_found"


# ---- one at a time -----------------------------------------------------------------------------------------------


def test_a_second_fill_while_one_runs_is_refused_then_allowed_after(client: TestClient, app) -> None:  # type: ignore[no-untyped-def]
    gate = threading.Event()
    stub = Stub(gate=gate)
    app.state.fill_runner = stub
    first = client.post("/fill").json()
    deadline = time.time() + 5
    while not stub.calls and time.time() < deadline:  # wait until the first job really is inside the runner
        time.sleep(0.01)
    second = client.post("/fill")
    assert second.status_code == 409 and second.json()["code"] == "fill_running"
    assert len(stub.calls) == 1  # the second never reached the runner
    gate.set()
    wait_for_end(client, first["job_id"])
    third = client.post("/fill")
    assert third.status_code == 202 and third.json()["job_id"] != first["job_id"]
    wait_for_end(client, third.json()["job_id"])


def test_the_manager_refuses_a_start_while_busy() -> None:
    manager = api_fill.JobManager()
    gate = threading.Event()
    manager.start(lambda: (gate.wait(5), make_result())[1])
    with pytest.raises(api_fill.FillBusy):
        manager.start(lambda: make_result())
    gate.set()
    deadline = time.time() + 5
    while manager.busy and time.time() < deadline:
        time.sleep(0.01)
    assert not manager.busy


def test_only_the_last_jobs_are_remembered_and_a_running_one_is_never_dropped() -> None:
    manager = api_fill.JobManager(max_jobs=3)
    ids = []
    for _ in range(5):
        job = manager.start(lambda: make_result())
        ids.append(job.id)
        while manager.busy:
            time.sleep(0.005)
    assert [manager.get(i) is not None for i in ids] == [False, False, True, True, True]
    gate = threading.Event()
    running = manager.start(lambda: (gate.wait(5), make_result())[1])
    assert manager.get(running.id) is running  # still there
    gate.set()


# ---- things that go wrong ---------------------------------------------------------------------------------------


def test_the_browser_not_being_open_is_a_503_and_starts_nothing(client: TestClient, app, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(api_fill, "browser_is_open", lambda: False)
    response = client.post("/fill")
    assert response.status_code == 503 and response.json()["code"] == "browser_closed"
    assert "browser open" in response.json()["detail"]
    assert app.state.fill_runner.calls == [] and not app.state.fill_jobs.busy


def test_an_empty_index_is_a_409_with_the_mode_in_the_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_fill, "browser_is_open", lambda: True)  # the REAL check_ready runs here
    app = api.create_app(MOCK, db_path=tmp_path / "test.db", answers_path=tmp_path / "answers.json")
    app.state.fill_runner = Stub()
    response = TestClient(app, base_url=LOCAL).post("/fill")
    assert response.status_code == 409 and response.json()["code"] == "index_not_ready"
    assert "mock" in response.json()["detail"] and app.state.fill_runner.calls == []


def test_an_unreachable_model_is_a_503(client: TestClient, app, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    def down(conn: sqlite3.Connection, settings: Settings) -> None:
        try:
            raise AIError("connection refused")
        except AIError as exc:
            raise api_fill.AIUnavailable(str(exc)) from exc

    monkeypatch.setattr(api_fill, "check_ready", down)
    response = client.post("/fill")
    assert response.status_code == 503 and response.json()["code"] == "ai_unavailable"
    assert app.state.fill_runner.calls == []


def test_check_ready_turns_ai_errors_into_a_clear_503_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_a: object, **_k: object) -> None:
        raise AIError("connection refused")

    monkeypatch.setattr(rag, "retrieve", broken)
    with pytest.raises(api_fill.AIUnavailable, match="Ollama"):
        api_fill.check_ready(sqlite3.connect(":memory:"), MOCK)


def test_an_expected_failure_ends_as_error_with_its_message_and_the_next_fill_can_start(client: TestClient, app) -> None:  # type: ignore[no-untyped-def]
    app.state.fill_runner = Stub(error=RuntimeError("No open tab has 'zzz' in its address."))
    job = wait_for_end(client, client.post("/fill").json()["job_id"])
    assert job["status"] == "error" and job["result"] is None and "zzz" in job["error"] and job["finished_at"]
    app.state.fill_runner = Stub()  # not stuck on "running"
    assert wait_for_end(client, client.post("/fill").json()["job_id"])["status"] == "done"


def test_an_unexpected_failure_ends_as_error_without_leaking_its_text_and_is_logged(client: TestClient, app, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    app.state.fill_runner = Stub(error=KeyError("secret-looking-value 0917"))
    job = wait_for_end(client, client.post("/fill").json()["job_id"])
    assert job["status"] == "error" and "KeyError" in job["error"] and "nothing was submitted" in job["error"]
    assert "secret-looking-value" not in job["error"]
    conn = db.connect(tmp_path / "test.db")
    row = conn.execute("SELECT kind, details FROM action_log WHERE kind = 'error'").fetchone()
    conn.close()
    assert row is not None and row["details"] == "fill failed: KeyError"  # the type only


def test_a_safety_refusal_is_reported_plainly(client: TestClient, app) -> None:  # type: ignore[no-untyped-def]
    from engine import safety

    app.state.fill_runner = Stub(error=safety.SafetyError("Mock mode only fills saved fixture pages, not real websites"))
    job = wait_for_end(client, client.post("/fill").json()["job_id"])
    assert job["status"] == "error" and "Mock mode" in job["error"]


# ---- the guards cover it --------------------------------------------------------------------------------------------


def test_a_fill_requested_by_another_website_is_refused(client: TestClient, app) -> None:  # type: ignore[no-untyped-def]
    response = client.post("/fill", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403 and app.state.fill_runner.calls == []


def test_a_foreign_host_cannot_start_or_read_a_fill(app) -> None:  # type: ignore[no-untyped-def]
    foreign = TestClient(app, base_url="http://evil.example")
    assert foreign.post("/fill").status_code == 403 and foreign.get("/fill/abc").status_code == 403


# ---- the real chain, on a tiny page ----------------------------------------------------------------------------------


@pytest.fixture
def real_app(tmp_path: Path, ready: None, spy) -> Iterator[tuple[TestClient, dict[str, Any]]]:  # type: ignore[no-untyped-def]  # noqa: F811
    """The real orchestrator runs in the job thread, on a page made from ``FORM`` in a headless browser."""
    from playwright.sync_api import sync_playwright

    app = api.create_app(MOCK, db_path=tmp_path / "test.db", answers_path=tmp_path / "answers.json")
    conn = db.connect(tmp_path / "test.db")
    conn.execute(
        "INSERT INTO profile (id, full_name, first_name, last_name, email, phone, address, upload_name) "
        "VALUES (1, ?, 'Maria', 'Santos', ?, ?, '12 Fake St, Faketown', ?)",
        (NAME, EMAIL, PHONE, "Maria Santos.pdf"),
    )
    for rid in ("A", "B"):
        pdf = tmp_path / f"resume_{rid}.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        conn.execute("INSERT INTO resumes (id, label, file_path, extracted_text) VALUES (?, ?, ?, '')", (rid, rid, str(pdf)))
    conn.commit()
    conn.close()
    seen: dict[str, Any] = {"spy": spy}

    def runner(db_path: Any, settings: Settings, request: FillIn) -> FillResultOut:
        connection = db.connect(db_path)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_content(FORM)
                install_recorder(page)
                result = api_fill.perform_fill(connection, page, settings, request, tmp_path / "shots" / "fill.png", sleep=lambda s: None)
                seen["bad_clicks"] = bad_clicks(page)
                seen["first_name"] = page.input_value("input[name=fn]")
                browser.close()
                return result
        finally:
            connection.close()

    app.state.fill_runner = runner
    yield TestClient(app, base_url=LOCAL), seen


def test_the_endpoint_runs_the_whole_chain_saves_the_history_row_and_clicks_nothing(real_app, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    client, seen = real_app
    job = wait_for_end(client, client.post("/fill", json={"post_text": POST_TEXT}).json()["job_id"], timeout=60)
    assert job["status"] == "done", job
    result = job["result"]
    assert result["resume_id"] == "B" and result["post"]["source"] == "text you pasted"
    assert result["filled"] >= 1 and result["unknown_ids"] == [7] and result["screenshot_path"]
    assert seen["first_name"] == "Maria" and seen["spy"].pick_texts == [POST_TEXT]  # the pasted post reached the picker
    assert seen["bad_clicks"] == [], "the fill clicked something that is not a field"
    history = client.get("/fills").json()
    assert [h["id"] for h in history] == [result["fill_id"]] and history[0]["status"] == "filled"
    assert Path(result["screenshot_path"]).is_file()


def test_the_response_never_holds_your_details(real_app) -> None:  # type: ignore[no-untyped-def]
    client, _seen = real_app
    job_id = client.post("/fill", json={"post_text": POST_TEXT}).json()["job_id"]
    wait_for_end(client, job_id, timeout=60)
    text = client.get(f"/fill/{job_id}").text + client.get("/fills").text
    for private in (NAME, EMAIL, PHONE, "12 Fake St"):
        assert private not in text


# ---- it can never submit or change the mode ----------------------------------------------------------------------------


def test_the_fill_code_never_clicks_and_never_changes_the_mode() -> None:
    source = Path(api_fill.__file__).read_text(encoding="utf-8")
    for forbidden in (".click(", ".press(", "submit(", "load_settings", "SETTINGS_PATH", "write_text"):
        assert forbidden not in source, forbidden
