"""Tests for the form filler (``engine/forms/filler.py``).

They run on the saved synthetic and captured pages in ``fixtures/forms/`` in a headless browser. No real
website, no AI (the answers are written by hand), no real data. The most important test is the
no-Submit test: a recorder in the page notes every click and fails if any lands on a button.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, sync_playwright

from engine import safety
from engine.db import connect, init_db
from engine.forms import filler
from engine.forms.answers import FieldAnswer
from engine.forms.filler import FillReport, ResumeFile, fill_page, to_iso_date
from engine.forms.reader import FormField, read_fields
from engine.settings import ROOT, Settings

FIXTURES = ROOT / "fixtures" / "forms"
MOCK = Settings(run_mode="mock")


# ---- helpers -------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    pg = browser.new_page()
    yield pg
    pg.close()


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    init_db(connection)
    yield connection
    connection.close()


@pytest.fixture
def resume(tmp_path: Path) -> ResumeFile:
    path = tmp_path / "resume_final_v7.pdf"  # an ugly on-disk name: the employer must never see it
    path.write_bytes(b"%PDF-1.4 fake resume bytes")
    return ResumeFile(path, "Fake Person.pdf")


def open_fixture(page: Page, name: str) -> list[FormField]:
    page.set_content((FIXTURES / name).read_text(encoding="utf-8"))
    page.wait_for_timeout(300)
    return read_fields(page)


def known(label: str, value: str) -> FieldAnswer:
    """A strong saved answer: filled, not flagged."""
    return FieldAnswer(label, value, "bank", False, kind="fixed", confidence=0.9)


def guess(label: str, value: str) -> FieldAnswer:
    """An AI draft: filled and flagged."""
    return FieldAnswer(label, value, "draft", True, "drafted from your notes")


def build(fields: list[FormField], values: dict[str, FieldAnswer | str]) -> list[FieldAnswer]:
    """One answer per field, in order. Fields not named in ``values`` are 'needs you' (empty)."""
    out = []
    for f in fields:
        v = values.get(f.label)
        if isinstance(v, str):
            v = known(f.label, v)
        out.append(v or FieldAnswer(f.label, "", "none", True, "no saved answer"))
    return out


def run(page: Page, fields: list[FormField], answers: list[FieldAnswer], **kwargs: Any) -> FillReport:
    kwargs.setdefault("settings", MOCK)
    kwargs.setdefault("sleep", lambda seconds: None)  # tests must not wait 1-4 s per field
    return fill_page(page, fields, answers, **kwargs)


def checked(page: Page, name: str) -> list[bool]:
    return [bool(x) for x in page.eval_on_selector_all(f"input[name={name}]", "els => els.map(e => e.checked)")]


# The recorder: notes every click and submit in the page (and its frames). See test_no_submit.
_RECORDER = r"""
() => {
  if (window.__jp) return;
  window.__jp = {clicks: [], submits: 0};
  document.addEventListener('click', e => {
    const t = e.target;
    const pressable = t.closest('button, a, [role=button], input[type=submit], input[type=button], input[type=image], input[type=reset]');
    window.__jp.clicks.push({
      tag: t.tagName.toLowerCase(), type: (t.type || '').toLowerCase(),
      text: (t.innerText || t.value || '').trim().slice(0, 40),
      onField: !!t.closest('input, select, textarea, label'), pressable: !!pressable,
    });
  }, true);
  document.addEventListener('submit', () => { window.__jp.submits++; }, true);
}
"""


def install_recorder(page: Page) -> None:
    for frame in page.frames:
        try:
            frame.evaluate(_RECORDER)
        except Exception:  # a frame that is still loading
            pass


def bad_clicks(page: Page) -> list[str]:
    """Every click that was NOT on a plain field, and every submit event. Empty = good.

    A page that navigated loses its recorder, which is reported too.
    """
    problems: list[str] = []
    for frame in page.frames:
        try:
            data = frame.evaluate("window.__jp || null")
        except Exception:
            continue
        if data is None:
            problems.append(f"recorder lost in {frame.url or 'main frame'}: the page navigated or reloaded")
            continue
        for c in data["clicks"]:
            if c["pressable"] or not c["onField"]:
                problems.append(f"click on <{c['tag']} type={c['type']}> {c['text']!r}")
        if data["submits"]:
            problems.append(f"{data['submits']} submit event(s)")
    return problems


def total_clicks(page: Page) -> int:
    return sum(len(frame.evaluate("window.__jp ? window.__jp.clicks : []")) for frame in page.frames)


# ---- the field types -------------------------------------------------------------------------------


def test_text_like_fields_are_typed(page: Page) -> None:
    fields = open_fixture(page, "sample_form.html")
    run(page, fields, build(fields, {"First name": "Maria", "Email": "maria@example.com", "Phone": "555 0100", "Summary": "Hello there"}))
    assert page.input_value("#fn") == "Maria"
    assert page.input_value("#em") == "maria@example.com"
    assert page.input_value("#ph") == "555 0100"
    assert page.input_value("#sum") == "Hello there"


def test_select_radio_and_checkboxes(page: Page) -> None:
    fields = open_fixture(page, "sample_form.html")
    report = run(
        page,
        fields,
        build(
            fields,
            {
                "Year level": "4th year",
                "Are you open to a hybrid setup?": "Yes",
                "Which tools do you use?": "Git, Docker",
                "I agree to the terms": "Yes",
            },
        ),
    )
    assert page.input_value("#lvl") == "4th year"
    assert checked(page, "hybrid") == [True, False]  # "Yes" picked the option labelled YES
    assert checked(page, "tools") == [True, True]
    assert checked(page, "terms") == [True]
    assert report.failed == 0


def test_one_checkbox_option_ticks_only_that_one(page: Page) -> None:
    fields = open_fixture(page, "sample_form.html")
    run(page, fields, build(fields, {"Which tools do you use?": "Docker"}))
    assert checked(page, "tools") == [False, True]


def test_a_no_leaves_a_lone_checkbox_alone(page: Page) -> None:
    fields = open_fixture(page, "sample_form.html")
    report = run(page, fields, build(fields, {"I agree to the terms": "No"}))
    assert checked(page, "terms") == [False]
    assert next(r for r in report.results if r.label == "I agree to the terms").outcome == "filled"


def test_select_with_untidy_option_text_and_hidden_radios(page: Page) -> None:
    fields = open_fixture(page, "fill_types.html")
    run(page, fields, build(fields, {"Country": "Philippines", "Work arrangement": "On-site"}))
    assert page.input_value("#country") == "ph"  # the option text has stray spaces in the page
    assert checked(page, "arr") == [False, True]  # the radios are invisible: ticked with a click on the input itself


def test_date_number_and_url_fields(page: Page) -> None:
    fields = open_fixture(page, "fill_types.html")
    run(page, fields, build(fields, {"Date you can start": "March 5, 2027", "Years of experience": "3", "Portfolio link": "https://example.com/me"}))
    assert page.input_value("#start") == "2027-03-05"
    assert page.input_value("#yrs") == "3"
    assert page.input_value("#web") == "https://example.com/me"


@pytest.mark.parametrize(
    ("text", "iso"),
    [("2027-03-05", "2027-03-05"), ("March 5, 2027", "2027-03-05"), ("5 March 2027", "2027-03-05"), ("Mar 5 2027", "2027-03-05"), ("03/05/2027", None), ("soon", None)],
)
def test_to_iso_date(text: str, iso: str | None) -> None:
    assert to_iso_date(text) == iso  # a slash date is ambiguous (month or day first?), so it is refused


def test_an_unreadable_date_is_left_empty(page: Page) -> None:
    fields = open_fixture(page, "fill_types.html")
    report = run(page, fields, build(fields, {"Date you can start": "03/05/2027"}))
    assert page.input_value("#start") == ""
    result = next(r for r in report.results if r.label == "Date you can start")
    assert result.outcome == "needs_you" and result.flagged


def test_text_longer_than_the_page_limit_is_flagged(page: Page) -> None:
    fields = open_fixture(page, "fill_types.html")
    report = run(page, fields, build(fields, {"One-line pitch": "A pitch that is much too long"}))
    result = next(r for r in report.results if r.label == "One-line pitch")
    assert result.outcome == "filled" and result.flagged and "limit of 12" in result.note


# ---- the resume ----------------------------------------------------------------------------------------


def upload_answer(label: str) -> FieldAnswer:
    return FieldAnswer(label, "", "resume", False, "resume upload: the picker chooses A or B")


def test_resume_is_uploaded_under_the_formal_name(page: Page, resume: ResumeFile) -> None:
    fields = open_fixture(page, "sample_form.html")
    report = run(page, fields, build(fields, {"Resume": upload_answer("Resume")}), resume=resume)
    seen = page.evaluate("(() => { const f = document.querySelector('#cv').files[0]; return {name: f.name, size: f.size}; })()")
    assert seen == {"name": "Fake Person.pdf", "size": len(b"%PDF-1.4 fake resume bytes")}
    assert resume.path.name == "resume_final_v7.pdf" and resume.path.is_file()  # the original is never renamed
    assert next(r for r in report.results if r.label == "Resume").outcome == "filled"


def test_no_resume_means_the_upload_is_left_empty_and_flagged(page: Page) -> None:
    fields = open_fixture(page, "sample_form.html")
    report = run(page, fields, build(fields, {"Resume": upload_answer("Resume")}), resume=None)
    assert page.evaluate("document.querySelector('#cv').files.length") == 0
    result = next(r for r in report.results if r.label == "Resume")
    assert result.outcome == "needs_you" and result.flagged and "no resume" in result.note


def test_only_the_resume_field_gets_a_file(page: Page, resume: ResumeFile) -> None:
    fields = open_fixture(page, "sample_form.html")
    other = FieldAnswer("Resume", "", "none", True, "cover letter file: needs you")  # the engine said: not the resume
    run(page, fields, build(fields, {"Resume": other}), resume=resume)
    assert page.evaluate("document.querySelector('#cv').files.length") == 0


# ---- things the filler leaves to you --------------------------------------------------------------------


def test_unlabelled_field_and_custom_dropdown_stay_empty(page: Page) -> None:
    sample = open_fixture(page, "sample_form.html")
    report = run(page, sample, build(sample, {}))
    mystery = next(r for r in report.results if r.label == "")
    assert mystery.outcome == "needs_you" and "no readable question" in mystery.note
    assert page.input_value("input[name=mystery]") == ""

    fields = open_fixture(page, "fill_types.html")
    report = run(page, fields, build(fields, {"Preferred start month": "March"}))  # even with an answer
    month = next(r for r in report.results if r.label == "Preferred start month")
    assert month.outcome == "needs_you" and "custom dropdown" in month.note
    assert page.input_value("#month") == ""


def test_a_value_that_matches_no_option_is_left_empty(page: Page) -> None:
    fields = open_fixture(page, "fill_types.html")
    report = run(page, fields, build(fields, {"Country": "Atlantis"}))
    assert page.input_value("#country") == ""
    assert next(r for r in report.results if r.label == "Country").outcome == "needs_you"


# ---- flags in the page -------------------------------------------------------------------------------------


def flag_tags(page: Page) -> list[str]:
    return page.evaluate("[...document.getElementById('jobpilot-flags').shadowRoot.querySelectorAll('.tag')].map(t => t.textContent)")


def test_guesses_and_needs_you_are_flagged_known_answers_stay_plain(page: Page) -> None:
    fields = open_fixture(page, "sample_form.html")
    answers = build(fields, {"First name": "Maria", "Summary": guess("Summary", "A drafted summary")})
    report = run(page, fields, answers)
    assert page.eval_on_selector("#fn", "e => e.style.outline") == ""  # known: plain
    assert "solid" in page.eval_on_selector("#sum", "e => e.style.outline")  # guess: solid outline
    assert "dashed" in page.eval_on_selector("input[name=mystery]", "e => e.style.outline")  # needs you: dashed
    tags = flag_tags(page)
    assert "drafted by AI: check me" in tags
    assert any(t.startswith("needs you") for t in tags)
    assert len(tags) == report.flagged  # exactly one tag per flagged field, none for known answers
    assert page.evaluate("getComputedStyle(document.getElementById('jobpilot-flags')).pointerEvents") == "none"  # can never be clicked


def test_a_long_error_note_stays_short_and_inside_the_page(page: Page) -> None:
    """Regression: a long engine error used to wrap one word per line and run off the left edge of the page."""
    fields = open_fixture(page, "sample_form.html")
    long_error = "error: RagError: The index was built with 'nomic-embed-text/v4' but you are searching with 'mock/v4'. Run: python -m engine.cli rag reindex"
    answers = [FieldAnswer(f.label, "", "none", True, long_error) for f in fields]
    run(page, fields, answers)
    boxes = page.evaluate(
        "[...document.getElementById('jobpilot-flags').shadowRoot.querySelectorAll('.tag, .why')]"
        ".map(e => { const r = e.getBoundingClientRect(); return {cls: e.className, left: r.left, right: r.right, width: r.width, height: r.height, text: e.textContent}; })"
    )
    width = page.evaluate("document.documentElement.clientWidth")
    assert boxes
    for b in boxes:
        assert b["left"] >= 0 and b["right"] <= width, f"{b['cls']} runs off the page: {b}"
        if b["cls"] == "tag":
            assert "RagError" not in b["text"] and b["height"] < 30  # one short line
        elif b["text"]:
            assert b["width"] > 150 and b["height"] < 60  # a readable line or two, not a column of single words


def test_flag_colours_come_from_the_design_tokens() -> None:
    assert filler.amber_colors()["line"].upper() == "#B45309"


# ---- safety, logging, delays ------------------------------------------------------------------------------------


def test_every_field_writes_one_log_row_and_never_the_value(page: Page, conn: sqlite3.Connection) -> None:
    fields = open_fixture(page, "sample_form.html")
    report = run(page, fields, build(fields, {"First name": "Zorblax", "Email": "zorblax@example.com"}), conn=conn)
    rows = conn.execute("SELECT kind, target, details FROM action_log").fetchall()
    assert len(rows) == len(fields)
    assert {r["kind"] for r in rows} <= {"fill", "upload", "error"}
    assert "Zorblax" not in " ".join(f"{r['target']} {r['details']}" for r in rows)  # values may be phone or email
    assert sum(r["details"].endswith("filled") for r in rows) == report.filled


def test_safety_is_asked_before_each_write(page: Page, monkeypatch: pytest.MonkeyPatch, resume: ResumeFile) -> None:
    calls: list[str] = []
    real = safety.check

    def spy(kind: str, target: str = "", *, settings: Settings | None = None) -> None:
        calls.append(kind)
        real(kind, target, settings=settings)

    monkeypatch.setattr(safety, "check", spy)
    fields = open_fixture(page, "sample_form.html")
    run(page, fields, build(fields, {"First name": "Maria", "Resume": upload_answer("Resume")}), resume=resume)
    assert calls[0] == "fill"  # once up front for the page
    assert calls.count("upload") == 1
    assert calls.count("fill") == 1 + 1  # the page, then the one text field


def test_if_safety_refuses_nothing_is_written(page: Page, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def refuse_after_the_first(kind: str, target: str = "", *, settings: Settings | None = None) -> None:
        calls.append(kind)
        if len(calls) > 1:  # the up-front page check passes, then every field is refused
            raise safety.SafetyError("test: not allowed")

    monkeypatch.setattr(safety, "check", refuse_after_the_first)
    fields = open_fixture(page, "sample_form.html")
    report = run(page, fields, build(fields, {"First name": "Maria"}))
    assert page.input_value("#fn") == ""
    result = next(r for r in report.results if r.label == "First name")
    assert result.outcome == "needs_you" and "safety" in result.note


def test_mock_mode_refuses_a_real_website_and_dry_run_allows_it() -> None:
    with pytest.raises(safety.SafetyError):
        safety.check("fill", "https://example.com/apply", settings=Settings(run_mode="mock"))
    with pytest.raises(safety.SafetyError):
        safety.check("upload", "https://example.com/apply", settings=Settings(run_mode="mock"))
    safety.check("fill", "file:///fixtures/forms/sample_form.html", settings=Settings(run_mode="mock"))
    safety.check("fill", "https://example.com/apply", settings=Settings(run_mode="dry_run"))
    with pytest.raises(safety.SafetyError):
        safety.check("submit", "file:///x.html", settings=Settings(run_mode="dry_run"))  # still never


def test_pauses_are_random_between_one_and_four_seconds(page: Page, monkeypatch: pytest.MonkeyPatch) -> None:
    writes: list[str] = []
    real = safety.check
    monkeypatch.setattr(safety, "check", lambda kind, target="", *, settings=None: (writes.append(kind), real(kind, target, settings=settings))[1])
    pauses: list[float] = []
    fields = open_fixture(page, "sample_form.html")
    report = fill_page(page, fields, build(fields, {"First name": "Maria", "Email": "m@example.com", "Phone": "555 0100"}), settings=MOCK, sleep=pauses.append)
    assert report.filled == 3
    assert len(pauses) == 2  # between 3 actions, none before the first
    assert all(1.0 <= p <= 4.0 for p in pauses)
    assert len(set(pauses)) == 2  # random, not a fixed wait


def test_fields_and_answers_must_line_up(page: Page) -> None:
    fields = open_fixture(page, "sample_form.html")
    with pytest.raises(ValueError):
        run(page, fields, build(fields, {})[:-1])


def test_a_screenshot_is_saved_with_the_flags_visible(page: Page, tmp_path: Path, conn: sqlite3.Connection) -> None:
    fields = open_fixture(page, "sample_form.html")
    shot = tmp_path / "shots" / "fill.png"
    report = run(page, fields, build(fields, {}), screenshot_path=shot, conn=conn)
    assert report.screenshot_path == shot and shot.stat().st_size > 1000
    row = conn.execute("SELECT kind, screenshot_path FROM action_log WHERE kind = 'screenshot'").fetchone()
    assert row["screenshot_path"] == str(shot)


def test_fields_in_frames_that_share_an_address_are_filled_in_the_right_frame(page: Page) -> None:
    """The saved Greenhouse page has several frames that are all 'about:srcdoc': the frame's position tells them apart."""
    fields = open_fixture(page, "indiecampers_greenhouse.html")
    in_frames = [f for f in fields if f.frame]
    assert len({f.frame for f in in_frames}) == 1 and len({f.frame_number for f in in_frames}) >= 2
    report = run(page, fields, build(fields, {"First Name": "Maria", "Email": "maria@example.com"}))
    assert report.failed == 0
    holders = [fr.url for fr in page.frames if fr.evaluate("[...document.querySelectorAll('input')].some(e => e.value === 'Maria')")]
    assert len(holders) == 1


# ---- the command line ---------------------------------------------------------------------------------------------


def test_forms_fill_reports_a_missing_fixture_without_opening_anything(capsys: pytest.CaptureFixture[str]) -> None:
    from engine import cli

    assert cli.main(["forms", "fill", "--fixture", "no_such_page"]) == 1
    assert "fixture not found" in capsys.readouterr().err


def test_forms_fill_stops_with_a_clear_message_when_the_index_does_not_match_the_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from engine import cli, rag

    def mismatch(*args: object, **kwargs: object) -> None:
        raise rag.RagError("The index was built with 'nomic-embed-text/v4' but you are searching with 'mock/v4'. Run: python -m engine.cli rag reindex")

    monkeypatch.setattr(rag, "retrieve", mismatch)
    assert cli.main(["forms", "fill", "--fixture", "sample_form"]) == 1
    err = capsys.readouterr().err
    assert "Nothing was filled" in err and "rag reindex" in err


def test_the_fill_report_lists_what_needs_you(capsys: pytest.CaptureFixture[str]) -> None:
    from engine import cli
    from engine.forms.filler import FieldResult

    report = FillReport(
        url="x",
        results=[FieldResult("Name", "text", "filled"), FieldResult("Licence", "text", "needs_you", "no saved answer", True)],
    )
    cli._print_fill_report(report)
    out = capsys.readouterr().out
    assert "Filled 1 of 2" in out and "NEEDS YOU" in out and "Licence" in out and "Stopped before Submit" in out


# ---- the page changed after the reader looked --------------------------------------------------------------------


def test_when_the_page_changes_nothing_is_typed_into_or_clicked_on_the_wrong_element(page: Page) -> None:
    fields = open_fixture(page, "sample_form.html")
    install_recorder(page)
    # Two new inputs appear at the top, so every saved position now points one or two elements too early.
    page.evaluate("document.querySelector('form').insertAdjacentHTML('afterbegin', '<input type=submit id=late value=Go><input type=checkbox id=trap>')")
    report = run(page, fields, build(fields, {"First name": "Maria", "Email": "maria@example.com", "Are you open to a hybrid setup?": "Yes"}))
    assert not page.is_checked("#trap") and total_clicks(page) == 0
    assert bad_clicks(page) == []
    assert report.filled == 0 and report.failed >= 3  # reported as failed, not forced


# ---- NEVER SUBMIT ------------------------------------------------------------------------------------------------------


def sample_values(fields: list[FormField]) -> dict[str, FieldAnswer | str]:
    """A plausible answer for every field of any page, by type."""
    values: dict[str, FieldAnswer | str] = {}
    for f in fields:
        if f.type == "file":
            values[f.label] = upload_answer(f.label)
        elif f.type in ("radio", "select", "checkbox") and f.options:
            values[f.label] = f.options[0]
        elif f.type == "checkbox":
            values[f.label] = "Yes"
        elif f.type == "date":
            values[f.label] = "March 5, 2027"
        elif f.type in ("number",):
            values[f.label] = "3"
        elif f.type == "url":
            values[f.label] = "https://example.com"
        elif f.type == "email":
            values[f.label] = "someone@example.com"
        else:
            values[f.label] = "Sample text"
    return values


@pytest.mark.parametrize("name", ["sample_form.html", "fill_types.html", "angkas_workable.html", "indiecampers_greenhouse.html"])
def test_no_code_path_clicks_submit_apply_or_next(page: Page, name: str, resume: ResumeFile, conn: sqlite3.Connection) -> None:
    """The [R] test: the filler may only touch fields. A recorder in the page sees every click and submit event."""
    fields = open_fixture(page, name)
    assert fields, f"the reader found no fields in {name}"
    install_recorder(page)
    answers = build(fields, sample_values(fields))
    # Flag a few so the highlight code runs too, then fill with the file upload available.
    answers = [FieldAnswer(a.label, a.value, a.source, True, "check", kind=a.kind) if i % 3 == 0 else a for i, a in enumerate(answers)]
    url_before = page.url
    report = run(page, fields, answers, resume=resume, conn=conn)
    assert report.filled > 0, f"nothing was filled on {name}"
    assert len(report.results) == len(fields)
    assert bad_clicks(page) == [], "the filler clicked something that is not a field"
    assert page.url == url_before


def test_the_detector_catches_a_submit_click(page: Page) -> None:
    """Proof the no-Submit test can fail: clicking the Submit button by hand must be reported."""
    open_fixture(page, "fill_types.html")
    install_recorder(page)
    page.evaluate("document.querySelector('form').addEventListener('submit', e => e.preventDefault())")  # stay on the page
    page.click("#send")
    assert any("submit" in p.lower() for p in bad_clicks(page))
    page.click("#next")
    assert len(bad_clicks(page)) >= 3  # the submit click and its submit event, then the Next button


def test_the_filler_source_has_no_button_or_submit_code() -> None:
    """A cheap second guard on the code itself: the only click is the JS click on a checkbox/radio input."""
    source = (ROOT / "engine" / "forms" / "filler.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    assert len(re.findall(r"\.click\(", code)) == 1 and "e => e.click()" in code
    for banned in ("get_by_role", ".press(", "dispatch_event", "requestSubmit", ".submit(", "type=submit", "locator(\"button"):
        assert banned not in code, f"filler.py must not contain {banned!r}"
