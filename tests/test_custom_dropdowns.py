"""Tests for filling every kind of field, not just text boxes (Phase 4.4).

What a real form (careers.shopee.sg) showed: its labels are not linked to their inputs, and all its choices are
custom dropdowns built from <div>s. So:

* the reader takes the label from the field's own block, and reads each custom dropdown as ONE field with its options
  (``fixtures/forms/shopee_careers.html`` is the real page, saved with personal data removed);
* facts come from your profile by code (name, school, degree, level, skills, country code), never from the AI;
* one saved answer can fill a text box, a dropdown or a yes/no list, through ``pick_option``, which never guesses;
* the filler opens a custom dropdown, searches it when the list is long, clicks the matching option and checks it
  was taken (``fixtures/forms/custom_dropdowns.html`` is a synthetic page that behaves like Shopee's widgets).

Mock mode, headless browser, no network, no AI.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, Page, sync_playwright
from tests.test_filler import bad_clicks, install_recorder

from engine import ai, rag
from engine.ai import AIError
from engine.db import connect, init_db
from engine.forms.answers import (
    FieldAnswer,
    answer_field,
    answer_form,
    bare_phone,
    country_code_option,
    education_level,
    is_fact_label,
    pick_option,
    profile_values,
)
from engine.forms.filler import fill_page
from engine.forms.reader import FormField, read_fields, read_fixture
from engine.settings import ROOT, Settings

MOCK = Settings(run_mode="mock")
FORMS = ROOT / "fixtures" / "forms"


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    pg = browser.new_page()
    pg.set_content((FORMS / "custom_dropdowns.html").read_text(encoding="utf-8"))
    pg.wait_for_timeout(200)
    yield pg
    pg.close()


@pytest.fixture(scope="module")
def shopee() -> dict[str, list[FormField]]:
    """The saved Shopee page's fields, by label (two fields share "Contact Number": the code box and the number)."""
    out: dict[str, list[FormField]] = {}
    for f in read_fixture(FORMS / "shopee_careers.html"):
        out.setdefault(f.label, []).append(f)
    return out


def fill(page: Page, fields: list[FormField], values: dict[str, str]):  # type: ignore[no-untyped-def]
    answers = [FieldAnswer(f.label, values.get(f.label, ""), "bank", False, kind="fixed") for f in fields]
    return fill_page(page, fields, answers, settings=MOCK, sleep=lambda s: None)


def shown(page: Page, selector: str) -> str:
    return page.eval_on_selector(selector, "e => e.textContent.trim()")


def boxes(page: Page) -> list[str]:
    """What each .jp-select box shows, in page order."""
    return page.eval_on_selector_all(".jp-select .jp-selector__inner", "els => els.map(e => e.textContent.trim())")


# ---- the reader: labels from the block, custom dropdowns as one field ------------------------------------------


def test_shopee_labels_come_from_the_block_not_the_placeholder(shopee: dict[str, list[FormField]]) -> None:
    assert "First Name" in shopee and "Last Name" in shopee and "Email Address" in shopee
    assert "As in NRIC/Passport" not in shopee  # the placeholder is no longer used as the question
    assert "Cumulative Grade Point Average (CGPA)" in shopee
    assert shopee["First Name"][0].required  # the red star counts as "required"
    assert shopee["Resume"][0].type == "file"  # the help sentence under "Resume*" is not part of the label


def test_shopee_custom_dropdowns_are_read_with_their_options(shopee: dict[str, list[FormField]]) -> None:
    code, number = shopee["Contact Number"]
    assert code.type == "dropdown" and code.custom_index >= 0 and "Philippines +63" in code.options
    assert number.type == "text"
    for label in ("Current Location", "Education Level", "School", "Course of Study", "Degree Classification"):
        assert shopee[label][0].type == "dropdown" and shopee[label][0].options, label
    assert "Bachelor's Degree" in shopee["Education Level"][0].options
    skills = shopee["Skills"][0]
    assert skills.multi and skills.max_choices == 8
    immigration = next(fs[0] for label, fs in shopee.items() if label.startswith("Do you need"))
    assert immigration.type == "dropdown" and immigration.options == ["Yes", "No"]


def test_the_synthetic_page_reads_like_the_real_one(page: Page) -> None:
    fields = read_fields(page)
    by_label = {(f.label, f.type): f for f in fields}
    assert ("First Name", "text") in by_label  # a broken <label for>, taken from the block
    assert ("Education Level", "dropdown") in by_label  # an ARIA combobox (its list is elsewhere in the page)
    channel = by_label[("How did you know about this role?", "dropdown")]
    assert "Add another channel" not in channel.options  # a <button> in a list is an action, not a choice
    assert by_label[("Skills", "dropdown")].multi and by_label[("Skills", "dropdown")].max_choices == 3


# ---- picking an option: words, not letters, and never a guess ---------------------------------------------------


@pytest.mark.parametrize(
    "value, options, expected",
    [
        ("bachelors degree", ["High School", "Bachelor's Degree"], "Bachelor's Degree"),
        ("Mandaluyong, Metro Manila, Philippines", ["Singapore", "Philippines", "Malaysia"], "Philippines"),
        ("Bachelor of Science in Information Technology", ["Information Technology", "Information Systems", "Science"], "Information Technology"),
        ("No, I do not need sponsorship", ["Yes", "No"], "No"),
        ("Yes", ["Yes", "No"], "Yes"),
        ("Java", ["JavaScript", "Java"], "Java"),
        ("Java", ["JavaScript"], ""),  # never a part of a word
        ("Philippines", ["Philippines +63", "Singapore +65"], "Philippines +63"),
        ("Manila", ["Manila North", "Manila South"], ""),  # two fit equally well: you choose
        ("Atlantis", ["Singapore", "Philippines"], ""),
    ],
)
def test_pick_option(value: str, options: list[str], expected: str) -> None:
    assert pick_option(value, options) == expected


def test_country_code_and_number_without_it() -> None:
    options = ["Singapore +65", "Philippines +63", "Syria +963", "Zimbabwe +263"]
    assert country_code_option("+63 917 123 4567", options) == "Philippines +63"
    assert country_code_option("09171234567", options) == "Philippines +63"
    assert country_code_option("+1 555 0100", options) == ""  # not in the list: you choose
    assert bare_phone("+63 917 123 4567") == "9171234567" and bare_phone("09171234567") == "9171234567"


@pytest.mark.parametrize(
    "degree, level",
    [("Bachelor of Science in Information Technology", "Bachelor's Degree"), ("BS Computer Science", "Bachelor's Degree"),
     ("Master of Science in Data Science", "Master's Degree"), ("PhD in Physics", "Doctorate"), ("Senior High School", "")],
)
def test_education_level_comes_from_your_degree(degree: str, level: str) -> None:
    assert education_level(degree) == level


@pytest.mark.parametrize(
    "label, fact",
    [("Previous / Current Company", True), ("Previous / Current Designation", True), ("Expected salary", True),
     ("Why do you want to join us?", False), ("Describe a project you are proud of", False),
     ("What is your favourite language", False), ("Tell us about yourself", False)],
)
def test_short_labels_name_facts_and_questions_do_not(label: str, fact: bool) -> None:
    assert is_fact_label(label) == fact


# ---- the answer engine on the real Shopee page --------------------------------------------------------------------


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    init_db(connection)
    connection.execute(
        "INSERT INTO profile (id, full_name, first_name, last_name, email, phone, school, degree, year_level, grad_year,"
        " location, github, skills) VALUES (1, 'Maria Santos', 'Maria', 'Santos', 'maria@example.com', '+63 900 123 4567',"
        " 'Polytechnic University of the Philippines', 'Bachelor of Science in Information Technology', '3rd Year', 2028,"
        " 'Faketown, Metro Manila, Philippines', 'https://github.com/fake', ?)",
        (json.dumps(["java", "react", "sql"]),),
    )
    connection.commit()
    yield connection
    connection.close()


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """No saved question matches, and the AI is offline: whatever gets filled here comes from code."""
    monkeypatch.setattr(rag, "match_saved_question", lambda *a, **k: rag.SavedMatch(None, False, (), rag.MATCH_THRESHOLD))

    def boom(*args: object, **kwargs: object) -> None:
        raise AIError("offline")

    monkeypatch.setattr(ai, "ask_ai", boom)


def test_shopee_facts_come_from_your_profile_by_code(conn: sqlite3.Connection, offline: None, shopee: dict[str, list[FormField]]) -> None:
    fields = [f for fs in shopee.values() for f in fs]
    answers = {(a.label, f.type): a for f, a in zip(fields, answer_form(conn, fields, settings=MOCK, record=False))}

    assert answers[("First Name", "text")].value == "Maria" and answers[("First Name", "text")].source == "personal"
    assert answers[("Last Name", "text")].value == "Santos"
    assert answers[("Contact Number", "dropdown")].value == "Philippines +63"
    assert answers[("Contact Number", "text")].value == "9001234567"  # the code is chosen in the box next to it
    assert answers[("Education Level", "dropdown")].value == "Bachelor's Degree"
    school = answers[("School", "dropdown")]
    assert school.value == "Polytechnic University of the Philippines" and school.flagged  # searched for at fill time
    assert answers[("Skills", "dropdown")].value == "java, react, sql"
    assert answers[("Website URL", "text")].value == "https://github.com/fake"  # no portfolio saved: GitHub, flagged
    for fact in ("Previous / Current Company", "Previous / Current Designation"):
        answer = answers[(fact, "text")]
        assert answer.value == "" and "fact" in answer.note  # never drafted by the AI
    gpa = answers[("Cumulative Grade Point Average (CGPA)", "text")]
    assert gpa.value == "" and "yourself" in gpa.note  # GPA: only from your saved answers (CLAUDE.md rule 4)


def test_a_saved_yes_no_answer_fills_a_dropdown(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    conn.execute("INSERT INTO answers (question, answer, kind) VALUES ('Will you need visa sponsorship?', 'No, I am a citizen', 'protected')")
    hit = rag.Hit(1, "answer", "Will you need visa sponsorship?", "Will you need visa sponsorship?", 0.95)
    monkeypatch.setattr(rag, "match_saved_question", lambda *a, **k: rag.SavedMatch(hit, True, ("protected",), rag.MATCH_THRESHOLD))
    box = FormField(label="Do you need immigration-related sponsorship?", type="dropdown", options=["Yes", "No"], custom_index=7)
    result = answer_field(conn, box, profile_values(conn), settings=MOCK, record=False)
    assert result.value == "No" and result.source == "bank"


# ---- the filler: open, search, click, check ---------------------------------------------------------------------


def test_custom_dropdowns_are_filled_and_checked(page: Page) -> None:
    fields = read_fields(page)
    install_recorder(page)
    report = fill(page, fields, {
        "Current Location": "Mandaluyong, Metro Manila, Philippines",
        "School": "Polytechnic University of the Philippines",  # not among the 3 options shown until you search
        "Education Level": "Bachelor's Degree",
    })
    outcome = {r.label: r for r in report.results}
    assert outcome["Current Location"].outcome == "filled" and outcome["School"].outcome == "filled"
    assert outcome["Education Level"].outcome == "filled"
    assert boxes(page)[1:3] == ["Philippines", "Polytechnic University of the Philippines"]
    assert shown(page, ".aria-box .value") == "Bachelor's Degree"  # the list drawn at the end of <body>
    assert bad_clicks(page) == [], "only dropdown boxes and options may be clicked"
    assert not page.evaluate("window.__submitted || false")


def test_the_country_code_box_takes_its_option_even_when_it_shows_only_the_code(page: Page) -> None:
    fields = [f for f in read_fields(page) if f.label == "Contact Number"]
    report = fill(page, fields, {"Contact Number": "Philippines +63"})
    assert report.results[0].outcome == "filled" and boxes(page)[0] == "+63"


def test_skills_pick_exact_names_only_up_to_the_limit(page: Page) -> None:
    fields = [f for f in read_fields(page) if f.label == "Skills"]
    report = fill(page, fields, {"Skills": "java, rust, c, sql, python"})  # "up to 3 skills"
    assert report.results[0].outcome == "filled"
    assert page.eval_on_selector(".jp-select--multiple", "e => e.dataset.value") == "Java|C|SQL"  # not JavaScript, not C++
    assert "chose 3" in report.results[0].note


def test_no_matching_option_leaves_it_empty_with_no_stray_search_text(page: Page) -> None:
    fields = [f for f in read_fields(page) if f.label == "Current Location"]
    report = fill(page, fields, {"Current Location": "Atlantis"})
    assert report.results[0].outcome == "needs_you" and "custom dropdown" in report.results[0].note
    assert boxes(page)[1] == "Select"
    assert page.eval_on_selector_all(".jp-select__filter input", "els => els.every(i => i.value === '')")


def test_a_button_inside_a_dropdown_list_is_never_clicked(page: Page) -> None:
    fields = [f for f in read_fields(page) if f.label.startswith("How did you know")]
    install_recorder(page)
    report = fill(page, fields, {fields[0].label: "Add another channel"})
    assert report.results[0].outcome == "needs_you"
    assert not page.evaluate("window.__buttonClicked || false") and bad_clicks(page) == []


def test_a_saved_channel_is_picked(page: Page) -> None:
    fields = [f for f in read_fields(page) if f.label.startswith("How did you know")]
    report = fill(page, fields, {fields[0].label: "Prosple"})
    assert report.results[0].outcome == "filled" and boxes(page)[4] == "Prosple"


def test_a_degree_is_searched_by_its_subject(page: Page) -> None:
    """The profile says "Bachelor of Science in Information Technology"; the list says "Information Technology"."""
    fields = [f for f in read_fields(page) if f.label == "Course of Study"]
    report = fill(page, fields, {"Course of Study": "Bachelor of Science in Information Technology"})
    assert report.results[0].outcome == "filled" and boxes(page)[5] == "Information Technology"


def test_a_saved_answer_not_in_view_is_kept_for_the_search_and_flagged(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    conn.execute("INSERT INTO answers (question, answer, kind) VALUES ('How did you hear about us?', 'Prosple, Friends', 'fixed')")
    hit = rag.Hit(1, "answer", "How did you hear about us?", "How did you hear about us?", 0.95)
    monkeypatch.setattr(rag, "match_saved_question", lambda *a, **k: rag.SavedMatch(hit, True, ("fixed",), rag.MATCH_THRESHOLD))
    custom = FormField(label="How did you know about this role?", type="dropdown", options=["Campus Emails", "Friends"], custom_index=4, multi=True)
    result = answer_field(conn, custom, profile_values(conn), settings=MOCK, record=False)
    assert result.value == "Prosple, Friends" and result.flagged and "searched" in result.note
    native = FormField(label="How did you know about this role?", type="select", options=["Campus Emails", "Friends"])
    plain = answer_field(conn, native, profile_values(conn), settings=MOCK, record=False)
    assert plain.value == "Friends"  # a real <select> shows its whole list: what is not there is not there


def test_the_whole_page_never_clicks_submit(page: Page) -> None:
    fields = read_fields(page)
    install_recorder(page)
    fill(page, fields, {
        "First Name": "Maria", "Contact Number": "Philippines +63", "Current Location": "Philippines",
        "School": "De La Salle University", "Skills": "java, sql", "How did you know about this role?": "Friends",
        "Education Level": "Bachelor's Degree",
    })
    assert bad_clicks(page) == [] and not page.evaluate("window.__submitted || false")
    assert boxes(page)[:2] == ["+63", "Philippines"] and shown(page, ".aria-box .value") == "Bachelor's Degree"
