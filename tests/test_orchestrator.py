"""Tests for "Fill this page" (``engine/forms/orchestrator.py`` and ``engine/forms/history.py``).

The answer engine, the resume picker and the filler have their own tests. Here they are stubbed or used
on a tiny inline page, so these tests check only what the orchestrator itself does: the ORDER, what it
hands to each piece, what it saves, and what it refuses. Mock mode, headless browser, no network, no AI.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, Route, sync_playwright
from tests.test_filler import bad_clicks, install_recorder

from engine import matcher, rag, safety
from engine.ai import ResumePick
from engine.db import connect, init_db
from engine.forms import answers as answers_module
from engine.forms import orchestrator
from engine.forms.answers import FieldAnswer
from engine.forms.jobfinder import FindResult, JobPost, TabInfo
from engine.forms.orchestrator import fill_current_page, job_location
from engine.settings import Settings

MOCK = Settings(run_mode="mock")
NAME, EMAIL, PHONE = "Maria Santos", "maria@example.com", "+63 900 123 4567"

FORM = (
    "<html><body><form>"
    "<label>First name <input name=fn></label>"
    "<label>Do you have a driver's licence? <input name=dl></label>"
    "<label>Resume <input type=file name=cv></label>"
    "<button type=submit>Submit application</button>"
    "</form></body></html>"
)
POST_TEXT = "Backend Intern in Makati. Responsibilities: write Python services. Qualifications: SQL."


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    pg = browser.new_page()
    pg.set_content(FORM)
    yield pg
    pg.close()


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    init_db(connection)
    connection.execute(
        "INSERT INTO profile (id, full_name, first_name, last_name, email, phone, address, upload_name) "
        "VALUES (1, ?, 'Maria', 'Santos', ?, ?, '12 Fake St, Faketown', ?)",
        (NAME, EMAIL, PHONE, "Maria Santos.pdf"),
    )
    for rid in ("A", "B"):
        path = tmp_path / f"resume_{rid}_v7.pdf"  # ugly on-disk names: the employer must never see them
        path.write_bytes(b"%PDF-1.4 fake")
        connection.execute("INSERT INTO resumes (id, label, file_path, extracted_text) VALUES (?, ?, ?, '')", (rid, rid, str(path)))
    connection.commit()
    yield connection
    connection.close()


class Spy:
    """Stands in for ``answer_form`` and ``pick_resume`` and remembers what they were given."""

    def __init__(self) -> None:
        self.answer_calls: list[dict[str, Any]] = []
        self.pick_texts: list[str] = []
        self.pick_error: Exception | None = None


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Spy:
    s = Spy()

    def fake_answer_form(conn: sqlite3.Connection, fields: list[Any], **kwargs: Any) -> list[FieldAnswer]:
        s.answer_calls.append(kwargs)
        out: list[FieldAnswer] = []
        for f in fields:
            if f.type == "file":
                out.append(answers_module.file_answer(f, has_job_post=bool(kwargs.get("job_text"))))
            elif f.label == "First name":
                out.append(FieldAnswer(f.label, "Maria", "personal", False, confidence=1.0))
            else:
                out.append(FieldAnswer(f.label, "", "none", True, "no saved answer", unknown_id=7))
        return out

    def fake_pick(conn: sqlite3.Connection, text: str, settings: Settings | None = None) -> ResumePick | None:
        s.pick_texts.append(text)
        if s.pick_error:
            raise s.pick_error
        return ResumePick(resume="B", reason="matches the backend projects", evidence=["Flask API"])

    monkeypatch.setattr(orchestrator, "answer_form", fake_answer_form)
    monkeypatch.setattr(matcher, "pick_resume", fake_pick)
    monkeypatch.setattr(orchestrator, "find_job_post", lambda page, **kw: FindResult(None, []))
    return s


def run(conn: sqlite3.Connection, page: Page, tmp_path: Path, **kwargs: Any) -> orchestrator.FillOutcome:
    kwargs.setdefault("settings", MOCK)
    kwargs.setdefault("sleep", lambda seconds: None)
    kwargs.setdefault("screenshot_path", tmp_path / "shots" / "fill.png")
    return fill_current_page(conn, page, **kwargs)


# ---- the happy path --------------------------------------------------------------------------------


def test_fill_runs_the_whole_chain_and_saves_a_history_row(conn: sqlite3.Connection, page: Page, spy: Spy, tmp_path: Path) -> None:
    out = run(conn, page, tmp_path, post=JobPost(POST_TEXT, "opener", "Backend Intern - Acme", "http://x.test/job"))

    assert out.resume_id == "B" and "backend" in out.resume_reason
    assert spy.pick_texts == [POST_TEXT]  # the post reached the picker
    assert spy.answer_calls[0]["job_text"] == POST_TEXT  # ...and the answer engine
    assert (spy.answer_calls[0]["job_scope"], spy.answer_calls[0]["job_city"]) == ("city", "makati")
    assert page.input_value("input[name=fn]") == "Maria"
    assert page.eval_on_selector("input[name=cv]", "e => e.files[0] && e.files[0].name") == "Maria Santos.pdf"
    assert out.unknown_ids == [7]

    row = conn.execute("SELECT * FROM fills WHERE id = ?", (out.fill_id,)).fetchone()
    assert (row["status"], row["resume_id"], row["job_title"]) == ("filled", "B", "Backend Intern - Acme")
    assert row["filled_count"] == out.report.filled and row["flagged_count"] == out.report.flagged  # type: ignore[union-attr]
    assert Path(row["screenshot_path"]).is_file()
    linked = conn.execute("SELECT count(*) FROM action_log WHERE fill_id = ?", (out.fill_id,)).fetchone()[0]
    assert linked >= 3  # the fills and the upload were logged and linked to this fill
    assert conn.execute("SELECT count(*) FROM action_log WHERE fill_id IS NULL AND kind IN ('fill', 'upload')").fetchone()[0] == 0


def test_the_job_post_the_finder_found_is_used(
    conn: sqlite3.Connection, page: Page, spy: Spy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = JobPost(POST_TEXT, "same_site", "Backend Intern", "http://x.test/job")
    tabs = [TabInfo(1, "Other", "http://y.test")]
    monkeypatch.setattr(orchestrator, "find_job_post", lambda page, **kw: FindResult(found, tabs))
    out = run(conn, page, tmp_path)
    assert out.post == found and out.tabs == tabs
    assert spy.pick_texts == [POST_TEXT]


def test_a_remote_post_selects_the_remote_answers() -> None:
    assert job_location("Fully remote role, work from home.") == ("remote", "")
    assert job_location("Based in Taguig, hybrid") == ("city", "taguig")
    assert job_location("Based in Cebu") == ("any", "")  # unknown place: the general saved answers
    assert job_location(None) == ("any", "")


# ---- no job post: no resume, never guessed -----------------------------------------------------------


def test_no_job_post_means_no_pick_no_upload_and_a_flagged_resume_field(
    conn: sqlite3.Connection, page: Page, spy: Spy, tmp_path: Path
) -> None:
    out = run(conn, page, tmp_path)
    assert out.post is None and out.resume_id is None
    assert spy.pick_texts == []  # the picker never ran
    assert spy.answer_calls[0]["job_text"] is None  # so the answer engine uses saved answers, not the post's location
    assert page.eval_on_selector("input[name=cv]", "e => e.files.length") == 0
    resume_field = next(r for r in out.report.results if r.label == "Resume")  # type: ignore[union-attr]
    assert resume_field.flagged and resume_field.outcome != "filled"
    assert any("No job post found" in m for m in out.messages)
    assert conn.execute("SELECT resume_id FROM fills WHERE id = ?", (out.fill_id,)).fetchone()["resume_id"] is None


def test_a_resume_you_name_skips_the_picker(conn: sqlite3.Connection, page: Page, spy: Spy, tmp_path: Path) -> None:
    out = run(conn, page, tmp_path, resume_id="a")
    assert out.resume_id == "A" and spy.pick_texts == []


def test_when_the_picker_fails_the_rest_is_still_filled(conn: sqlite3.Connection, page: Page, spy: Spy, tmp_path: Path) -> None:
    spy.pick_error = matcher.PickError("No resume is indexed")
    out = run(conn, page, tmp_path, post=JobPost(POST_TEXT, "pasted"))
    assert out.resume_id is None
    assert any("Resume not picked" in m for m in out.messages)
    assert page.input_value("input[name=fn]") == "Maria"  # one failing step never stops the others


# ---- privacy ---------------------------------------------------------------------------------------


def test_your_details_are_scrubbed_from_the_post_before_it_goes_anywhere(
    conn: sqlite3.Connection, page: Page, spy: Spy, tmp_path: Path
) -> None:
    text = f"Signed in as {NAME} ({EMAIL}, {PHONE}, 12 Fake St, Faketown). " + POST_TEXT + " Marketing team."
    run(conn, page, tmp_path, post=JobPost(text, "opener"))
    for seen in (spy.pick_texts[0], spy.answer_calls[0]["job_text"]):
        for private in (NAME, EMAIL, PHONE, "12 Fake St", "Maria Santos"):
            assert private not in seen
        assert "Marketing" in seen  # only whole values are removed, never name parts inside other words


def test_the_history_row_and_log_hold_labels_never_values(conn: sqlite3.Connection, page: Page, spy: Spy, tmp_path: Path) -> None:
    out = run(conn, page, tmp_path, post=JobPost(POST_TEXT, "opener"))
    row = conn.execute("SELECT * FROM fills WHERE id = ?", (out.fill_id,)).fetchone()
    stored = row["filled_fields"] + row["flagged_fields"]
    assert "First name" in stored and "Maria" not in stored
    flagged = json.loads(row["flagged_fields"])
    assert {"label", "outcome", "note"} <= set(flagged[0])
    log = " ".join(f"{r['target']} {r['details']}" for r in conn.execute("SELECT target, details FROM action_log"))
    assert "Maria" not in log and EMAIL not in log and PHONE not in log


# ---- stopping early, previews, safety ---------------------------------------------------------------


def test_a_page_without_form_fields_stops_and_saves_nothing(
    conn: sqlite3.Connection, browser: Browser, spy: Spy, tmp_path: Path
) -> None:
    pg = browser.new_page()
    pg.set_content("<html><body><h1>Backend Intern</h1><p>Read about the job.</p></body></html>")
    out = run(conn, pg, tmp_path)
    pg.close()
    assert out.report is None and out.fill_id is None
    assert any("No form fields" in m for m in out.messages)
    assert conn.execute("SELECT count(*) FROM fills").fetchone()[0] == 0
    assert spy.pick_texts == [] and spy.answer_calls == []  # no AI was asked about a page with nothing to fill


def test_a_preview_run_saves_no_history_and_records_nothing(conn: sqlite3.Connection, page: Page, spy: Spy, tmp_path: Path) -> None:
    out = run(conn, page, tmp_path, save=False)
    assert out.report is not None and out.fill_id is None
    assert spy.answer_calls[0]["record"] is False  # no unknown questions or wordings are saved either
    assert conn.execute("SELECT count(*) FROM fills").fetchone()[0] == 0


def test_mock_mode_refuses_a_real_website_before_anything_else(
    conn: sqlite3.Connection, browser: Browser, spy: Spy, tmp_path: Path
) -> None:
    ctx = browser.new_context()
    ctx.route("**/*", lambda route: Route.fulfill(route, status=200, content_type="text/html", body=FORM))
    pg = ctx.new_page()
    pg.goto("https://careers.acme.test/apply")
    with pytest.raises(safety.SafetyError):
        run(conn, pg, tmp_path)
    ctx.close()
    assert spy.pick_texts == [] and spy.answer_calls == []
    assert conn.execute("SELECT count(*) FROM fills").fetchone()[0] == 0


def test_the_orchestrator_never_clicks_submit_apply_or_next(conn: sqlite3.Connection, page: Page, spy: Spy, tmp_path: Path) -> None:
    """The [R] test, on the whole chain: a recorder in the page sees every click and submit event."""
    install_recorder(page)
    run(conn, page, tmp_path, post=JobPost(POST_TEXT, "opener"))
    assert bad_clicks(page) == [], "the fill clicked something that is not a field"


# ---- the command line --------------------------------------------------------------------------------


def test_the_command_cannot_run_live() -> None:
    from engine import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["forms", "fill", "--mode", "live"])
    assert exc.value.code == 2  # argparse: not one of the allowed choices


# ---- the real answer engine (no spy): unknown questions are really saved, and a rerun does not duplicate them ------


@pytest.fixture
def real_engine(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> Spy:
    """The REAL ``answer_form`` and finder logic. Only the picker is faked and the AI is offline (every draft fails).

    The search index is built with the mock embedder from one saved answer (an empty index is an error, as in real
    use). Mock vectors cannot judge meaning, so the questions on the test pages stay unmatched: they are unknown.

    With the AI offline, a new question can never be drafted, so it ends on the unknown questions list: that is
    what these tests check. (Mock mode, an in-memory database and the mock embedder: no network.)
    """
    from engine import ai
    from engine.ai import AIError

    s = Spy()

    def offline(task: str, prompt: str, **kwargs: Any) -> Any:
        raise AIError("offline in this test")

    def fake_pick(conn: sqlite3.Connection, text: str, settings: Settings | None = None) -> ResumePick | None:
        s.pick_texts.append(text)
        return ResumePick(resume="A", reason="test pick", evidence=["x"])

    conn.execute("INSERT INTO answers (question, answer, kind) VALUES ('When can you start?', '2 weeks notice', 'fixed')")
    conn.commit()
    rag.reindex(conn, MOCK)
    monkeypatch.setattr(ai, "ask_ai", offline)
    monkeypatch.setattr(matcher, "pick_resume", fake_pick)
    return s


def _unknown_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM unknown_questions ORDER BY id").fetchall()


def test_unknown_questions_are_really_saved_with_their_source_page(
    conn: sqlite3.Connection, page: Page, real_engine: Spy, tmp_path: Path
) -> None:
    out = run(conn, page, tmp_path, post=JobPost(POST_TEXT, "opener", "Backend Intern", "http://x.test/job"))

    rows = _unknown_rows(conn)
    assert [r["question_text"] for r in rows] == ["Do you have a driver's licence?"]
    assert rows[0]["status"] == "open" and rows[0]["times_seen"] == 1
    assert rows[0]["page_url"] == page.url  # remembered with the page it came from
    assert out.unknown_ids == [rows[0]["id"]]  # the orchestrator reports the rows the engine really saved
    assert page.input_value("input[name=dl]") == ""  # and the field is left for you


def test_filling_the_same_page_twice_does_not_duplicate_unknown_questions(
    conn: sqlite3.Connection, page: Page, real_engine: Spy, tmp_path: Path
) -> None:
    first = run(conn, page, tmp_path, post=JobPost(POST_TEXT, "opener"))
    second = run(conn, page, tmp_path, post=JobPost(POST_TEXT, "opener"))

    rows = _unknown_rows(conn)
    assert len(rows) == 1 and rows[0]["times_seen"] == 2  # one row, counted twice
    assert first.unknown_ids == second.unknown_ids == [rows[0]["id"]]
    assert conn.execute("SELECT count(*) FROM fills").fetchone()[0] == 2  # each fill is its own history row


@pytest.mark.parametrize("name", ["sample_form", "angkas_workable", "indiecampers_greenhouse"])
def test_the_whole_chain_on_each_saved_form(
    conn: sqlite3.Connection, page: Page, real_engine: Spy, tmp_path: Path, name: str
) -> None:
    """Each saved form (a synthetic one, Workable, a Greenhouse iframe): fills, saves, never clicks, reruns cleanly."""
    page.set_content((Path(__file__).resolve().parent.parent / "fixtures" / "forms" / f"{name}.html").read_text(encoding="utf-8"))
    page.wait_for_timeout(300)
    install_recorder(page)
    post = JobPost(POST_TEXT, "opener", "Backend Intern", "http://x.test/job")

    first = run(conn, page, tmp_path, post=post)
    assert first.report is not None and first.report.filled > 0
    assert first.fill_id is not None and first.resume_id == "A"
    saved = {r["id"]: r for r in _unknown_rows(conn)}
    assert saved and first.unknown_ids  # this form has questions the bank cannot answer, and they were saved
    assert set(first.unknown_ids) <= set(saved)  # every id the outcome reports is a real row
    assert all(r["page_url"] == page.url and r["status"] == "open" for r in saved.values())

    second = run(conn, page, tmp_path, post=post)
    again = _unknown_rows(conn)
    assert len(again) == len(saved)  # a rerun adds no new rows...
    assert second.unknown_ids == first.unknown_ids  # ...it finds the same ones
    assert all(r["times_seen"] == 2 for r in again if r["id"] in first.unknown_ids)  # ...and counts them again
    assert bad_clicks(page) == [], "the fill clicked something that is not a field"
