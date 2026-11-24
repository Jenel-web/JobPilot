"""Regression tests for the four bugs found by the form-filler audit (Nov 2026).

The audit ran the real pipeline (reader -> answers -> filler, mock mode, headless Chromium) on mock forms shaped like
Greenhouse, Lever, Workday, a Google Form and a "tricky" form. Each bug has a small synthetic page in
``fixtures/forms/audit_*.html`` and tests here:

    Bug 1   radio/checkbox questions without a <legend> lost their question text (labelled ``cards[1]``)
    Bug 2   a Workday-style <button role="combobox"> dropdown was skipped without a word
    Bug 2b  any control the reader cannot drive must be REPORTED as "needs you", never skipped
    Bug 3   Workday phone fields ("Phone Device Type", "Country Phone Code")
    Bug 4   profile facts were not reused for course, year level and technology checkboxes

No real website, no AI, fake profile values only. Every browser test also checks that nothing but fields was clicked.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, Page, sync_playwright

from engine.db import connect, init_db
from engine.forms import answers
from engine.forms.answers import FieldAnswer, fill_personal
from engine.forms.reader import FormField
from tests.test_filler import MOCK, bad_clicks, build, install_recorder, known, open_fixture, run

VALUES = {
    "first_name": "Juan", "last_name": "Dela Cruz", "full_name": "Juan Dela Cruz", "email": "juan@example.com",
    "phone": "+63 917 555 0142", "country": "Philippines",
    "degree": "Bachelor of Science in Computer Science", "year_level": "4th year",
    "skills": "python, react, typescript, docker",
}

# Each bug's tests are marked "expected to fail" until its fix lands, so every commit stays green. strict=True: a test
# that starts passing while still marked makes pytest fail, so the marker must be removed in the fix's own commit.
BUG1 = pytest.mark.xfail(strict=True, reason="Bug 1 not fixed yet: no <legend> = question text lost")
BUG2 = pytest.mark.xfail(strict=True, reason="Bug 2 not fixed yet: <button role=combobox> dropdowns skipped")
BUG2B = pytest.mark.xfail(strict=True, reason="Bug 2b not fixed yet: unknown controls skipped silently")
BUG3 = pytest.mark.xfail(strict=True, reason="Bug 3 not fixed yet: Workday phone fields")
BUG4 = pytest.mark.xfail(strict=True, reason="Bug 4 not fixed yet: course, year level, technology checkboxes")


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


def by_name(fields: list[FormField], name: str) -> FormField:
    return next(f for f in fields if f.name == name)


def field(label: str, type: str = "text", **kw: object) -> FormField:
    return FormField(label=label, type=type, **kw)  # type: ignore[arg-type]


def personal_answers(fields: list[FormField], values: dict[str, str]) -> list[FieldAnswer]:
    """What the answer engine's personal step decides for each field; anything not personal is left for you."""
    out = []
    for f in fields:
        p = fill_personal(f, values)
        if p is None:
            out.append(FieldAnswer(f.label, "", "none", True, "not personal"))
        else:
            out.append(FieldAnswer(f.label, p.value, "personal", p.flagged, p.note))
    return out


# ---- Bug 1: radio/checkbox questions without a <legend> ------------------------------------------------------------


@BUG1
@pytest.mark.parametrize(
    ("name", "question"),
    [
        ("cards[1]", "Are you eligible to work?"),  # Lever: question div, choices in a ul
        ("entry.14", "Do you have your own laptop?"),  # Google Form: question <label> beside the choices
        ("question_3", "Are you willing to work onsite?"),  # Greenhouse without a legend: <p>, choices in own divs
    ],
)
def test_bug1_question_text_is_read_without_a_legend(page: Page, name: str, question: str) -> None:
    f = by_name(open_fixture(page, "audit_radio_layouts.html"), name)
    assert question in f.label
    assert f.type == "radio" and f.options == ["Yes", "No"]
    assert "[" not in f.label and "entry." not in f.label and "question_" not in f.label


def test_bug1_a_legend_still_wins(page: Page) -> None:
    f = by_name(open_fixture(page, "audit_radio_layouts.html"), "setup")
    assert f.label == "Preferred work setup" and f.options == ["Onsite", "Remote"]


def test_bug1_a_lone_checkbox_is_still_its_own_question(page: Page) -> None:
    f = by_name(open_fixture(page, "audit_radio_layouts.html"), "consent")
    assert f.type == "checkbox" and f.options == [] and f.label.startswith("I consent")


def test_bug1_a_section_heading_past_another_field_is_never_taken(page: Page) -> None:
    """The search stops at the School block, so "Education" is not used; the old name fallback stays."""
    f = by_name(open_fixture(page, "audit_radio_layouts.html"), "yl")
    assert "Education" not in f.label and f.label == "yl"


# ---- Bug 2: <button role="combobox"> dropdowns (Workday) -----------------------------------------------------------


@BUG2
def test_bug2_a_button_combobox_is_read_as_a_dropdown(page: Page) -> None:
    fields = open_fixture(page, "audit_workday_dropdown_safe.html")
    f = next(f for f in fields if "Hear About Us" in f.label)
    assert f.type == "dropdown" and f.custom_index >= 0
    assert f.label == "How Did You Hear About Us"
    assert f.options == ["Careers Website", "LinkedIn", "Referral", "Other"]


@BUG2
def test_bug2_a_safe_button_combobox_is_filled_and_nothing_else_is_clicked(page: Page) -> None:
    fields = open_fixture(page, "audit_workday_dropdown_safe.html")
    install_recorder(page)
    report = run(page, fields, build(fields, {"How Did You Hear About Us": "Referral"}))
    assert page.inner_text("#b1").strip() == "Referral"
    assert report.failed == 0
    assert bad_clicks(page) == []


@BUG2
def test_bug2_a_button_combobox_that_could_submit_is_never_clicked(page: Page) -> None:
    """No type attribute = a submit button by default: refused, left for you, nothing clicked at all."""
    fields = open_fixture(page, "audit_workday_dropdown_unsafe.html")
    f = next(f for f in fields if f.label == "Source")
    assert f.type == "dropdown"
    install_recorder(page)
    report = run(page, fields, build(fields, {"Source": "LinkedIn"}))
    result = next(r for r in report.results if r.label == "Source")
    assert result.outcome == "needs_you"
    assert page.inner_text("#b").strip() == "Select One"
    assert page.evaluate("window.__jp.clicks.length") == 0
    assert bad_clicks(page) == []


# ---- Bug 2b: never skip a control silently --------------------------------------------------------------------------


@BUG2B
def test_bug2b_unknown_controls_are_reported_not_skipped(page: Page) -> None:
    fields = open_fixture(page, "audit_unsupported.html")
    unsupported = [f for f in fields if f.type == "unsupported"]
    assert sorted(f.label for f in unsupported) == ["Cover note", "Rate your Python skill"]
    assert all(f.indexes == [] and f.custom_index == -1 for f in unsupported)
    assert not any("Account menu" in f.label for f in fields)  # a nav menu button is an action, not a question


@BUG2B
def test_bug2b_unknown_controls_end_as_needs_you_after_a_fill(page: Page, conn: sqlite3.Connection) -> None:
    fields = open_fixture(page, "audit_unsupported.html")
    decided = [
        answers.answer_field(conn, f, VALUES, settings=MOCK, record=False) if f.type == "unsupported" else known(f.label, "Juan")
        for f in fields
    ]
    install_recorder(page)
    report = run(page, fields, decided)
    for r in report.results:
        if r.type == "unsupported":
            assert r.outcome == "needs_you" and r.flagged
    assert sum(r.type == "unsupported" for r in report.results) == 2
    assert bad_clicks(page) == []


# ---- Bug 3: Workday phone fields (no browser) -----------------------------------------------------------------------


@BUG3
def test_bug3_phone_device_type_is_mobile_for_a_mobile_number() -> None:
    f = field("Phone Device Type", "dropdown", options=["Mobile", "Home", "Work"], custom_index=0)
    p = fill_personal(f, {**VALUES, "phone": "+63 917 555 0142"})
    assert p is not None and p.value == "Mobile" and not p.flagged


def test_bug3_phone_device_type_is_never_guessed_for_a_landline() -> None:
    f = field("Phone Device Type", "dropdown", options=["Mobile", "Home", "Work"], custom_index=0)
    p = fill_personal(f, {**VALUES, "phone": "+63 2 8123 4567"})
    assert p is not None and p.value == "" and p.flagged


@BUG3
def test_bug3_country_phone_code_picks_your_country() -> None:
    f = field("Country Phone Code", "select", options=["Philippines (+63)", "United States of America (+1)", "Singapore (+65)"])
    p = fill_personal(f, VALUES)
    assert p is not None and p.value == "Philippines (+63)"


@pytest.mark.parametrize("label", ["Verification code", "Referral code", "Promo code", "Confirmation code"])
def test_bug3_other_codes_are_still_not_personal(label: str) -> None:
    assert fill_personal(field(label), VALUES) is None


# ---- Bug 4: course, year level and technology checkboxes (no browser) -----------------------------------------------


@BUG4
@pytest.mark.parametrize("label", ["Course / Program", "Course or Program", "Program / Course", "Degree and Major"])
def test_bug4_course_and_program_labels_give_your_degree(label: str) -> None:
    p = fill_personal(field(label), VALUES)
    assert p is not None and p.value == VALUES["degree"]


@BUG4
def test_bug4_year_level_radio_picks_your_year() -> None:
    f = field("Year level", "radio", options=["1st year", "2nd year", "3rd year", "4th year"])
    p = fill_personal(f, VALUES)
    assert p is not None and p.value == "4th year" and not p.flagged


@BUG4
def test_bug4_year_level_radio_with_other_words_is_left_for_you() -> None:
    f = field("Year level", "radio", options=["Freshman", "Sophomore", "Junior", "Senior"])
    p = fill_personal(f, VALUES)
    assert p is not None and p.value == "" and p.flagged


@BUG4
def test_bug4_technology_checkboxes_tick_only_your_saved_skills() -> None:
    f = field("Which of these technologies have you used?", "checkbox", options=["Python", "Java", "React", "Docker", "Rust"])
    p = fill_personal(f, VALUES)
    assert p is not None and p.value == "Python, React, Docker" and p.flagged
    assert "Java" not in p.value and "Rust" not in p.value


def test_bug4_a_yes_no_radio_is_not_personal() -> None:
    assert fill_personal(field("Do you have your own laptop?", "radio", options=["Yes", "No"]), VALUES) is None


@BUG4
def test_bug4_google_form_end_to_end(page: Page) -> None:
    fields = open_fixture(page, "audit_google_form.html")
    install_recorder(page)
    run(page, fields, personal_answers(fields, VALUES))
    assert page.input_value("#course") == VALUES["degree"]
    year = page.eval_on_selector_all("input[name='entry.2']:checked", "els => els.map(e => e.value)")
    techs = page.eval_on_selector_all("input[name='entry.3']:checked", "els => els.map(e => e.value)")
    laptop = page.eval_on_selector_all("input[name='entry.4']:checked", "els => els.map(e => e.value)")
    assert year == ["4th year"]
    assert techs == ["Python", "React", "Docker"]
    assert laptop == []  # not personal: no answer was given, so nothing is ticked
    assert bad_clicks(page) == []


# ---- every audit page: nothing but fields is ever clicked -----------------------------------------------------------


def _answer_everything(fields: list[FormField]) -> list[FieldAnswer]:
    """A value for every field the filler can drive: the first option, or a short text."""
    out = []
    for f in fields:
        if f.type == "unsupported":
            out.append(FieldAnswer(f.label, "", "none", True, "unsupported"))
        elif f.options:
            out.append(known(f.label, f.options[0]))
        elif f.type == "checkbox":
            out.append(known(f.label, "yes"))
        else:
            out.append(known(f.label, "test"))
    return out


@pytest.mark.parametrize(
    "fixture",
    [
        "audit_radio_layouts.html",
        "audit_workday_dropdown_safe.html",
        "audit_workday_dropdown_unsafe.html",
        "audit_unsupported.html",
        "audit_google_form.html",
    ],
)
def test_no_audit_page_ever_gets_a_button_click_or_submit(page: Page, fixture: str) -> None:
    fields = open_fixture(page, fixture)
    install_recorder(page)
    run(page, fields, _answer_everything(fields))
    assert bad_clicks(page) == []
