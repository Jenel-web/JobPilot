"""Privacy test (CLAUDE.md rule 3): no prompt sent through ``ask_ai`` may contain your phone, address,
email or ID numbers.

How it works:
  1. A profile is built whose private values are easy to recognise (fake phone, email, address, and an ID
     number that appears in a resume and in the answer bank).
  2. ``ask_ai`` is replaced by a recorder. It stores every prompt, then passes the call on to the real
     ``ask_ai`` in mock mode, so the engine behaves exactly as it normally would.
  3. ``answer_form()`` runs on each saved form in ``fixtures/forms/``.
  4. Every recorded prompt is searched for the private values (in several spellings) and for anything
     shaped like an email address or a long ID number.

The test also fails if NO prompt was recorded, because "nothing was sent" would prove nothing.
No Ollama, no network, no real data.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest
from playwright.sync_api import sync_playwright

from engine import ai, matcher, rag
from engine.db import connect, init_db
from engine.forms.answers import answer_form
from engine.forms.reader import FormField, read_fields
from engine.settings import ROOT, Settings

MOCK = Settings(run_mode="mock")
FORMS = ROOT / "fixtures" / "forms"
FIXTURES = ["sample_form.html", "angkas_workable.html", "indiecampers_greenhouse.html"]

FAKE_EMAIL = "fake.person@example.com"
FAKE_PHONE = "+63 917 123 4567"
FAKE_ADDRESS = "12 Imaginary Street, Faketown"
FAKE_ID = "987654321"  # e.g. a tax or student ID number

RESUME_A = f"""Fake Person
{FAKE_EMAIL} | {FAKE_PHONE} | {FAKE_ADDRESS}
Student ID {FAKE_ID}
EXPERIENCE
Built an Android app with Kotlin and Jetpack Compose for a campus club.
SKILLS
Java, Kotlin, SQL, Git and unit testing with JUnit.
"""
RESUME_B = f"""Fake Person
{FAKE_EMAIL} | {FAKE_PHONE}
TIN {FAKE_ID}
EXPERIENCE
Built a React and Spring Boot exam platform with a live camera feed.
SKILLS
React, TypeScript, Spring Boot, PostgreSQL.
"""

# The private values and the spellings a form or a resume might use for them.
PRIVATE: dict[str, list[str]] = {
    "email": [FAKE_EMAIL, FAKE_EMAIL.split("@")[0]],
    "phone": [FAKE_PHONE, "917 123 4567", "09171234567", "+639171234567", "9171234567"],
    "address": [FAKE_ADDRESS, "12 Imaginary Street", "Imaginary Street"],
    "id number": [FAKE_ID],
}
EMAIL_SHAPE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
LONG_NUMBER = re.compile(r"\d{6,}")  # ID-style numbers (years and scores are shorter)


# ---- setup ---------------------------------------------------------------------------------------


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    """A database with a fake profile, two resumes and a few saved answers, indexed with mock vectors."""
    connection = connect(":memory:")
    init_db(connection)
    projects = [
        {
            "name": "PetTracker",
            "tech": ["Kotlin", "Room"],
            "blurb": "Android app to track pet vaccines",
            "problem": "Owners forgot vaccine dates.",
            "solution": "Reminders based on each pet's schedule.",
            "hardest_part": "Scheduling reminders offline.",
        },
        {
            "name": "ExamGuard",
            "tech": ["React", "Spring Boot"],
            "blurb": "Online exam proctoring platform",
            "problem": "Students cheated on online exams.",
            "solution": "A live camera feed with alerts for teachers.",
            "hardest_part": "Keeping the feed in sync.",
        },
    ]
    about_me = {"why_software_engineering": "A small idea can help many people.", "how_i_work": "I start from the hard part."}
    connection.execute(
        "INSERT INTO profile (id, full_name, first_name, last_name, email, phone, address, location, gpa, summary, skills,"
        " projects, about_me, school, degree, year_level, grad_year)"
        " VALUES (1, 'Fake Person', 'Fake', 'Person', ?, ?, ?, 'Makati, Philippines', '3.99',"
        " 'Student who likes building apps', ?, ?, ?, 'Fake University', 'BS Computer Science', '3rd year', 2027)",
        (FAKE_EMAIL, FAKE_PHONE, FAKE_ADDRESS, json.dumps(["Java", "Kotlin", "React"]), json.dumps(projects), json.dumps(about_me)),
    )
    connection.execute("INSERT INTO resumes (id, label, file_path, extracted_text) VALUES ('A', 'x', 'a.pdf', ?)", (RESUME_A,))
    connection.execute("INSERT INTO resumes (id, label, file_path, extracted_text) VALUES ('B', 'y', 'b.pdf', ?)", (RESUME_B,))
    for question, answer, kind in [
        ("What is your tax ID number?", f"TIN {FAKE_ID}", "protected"),
        ("Do you require visa sponsorship?", "No", "protected"),
        ("When can you start?", "Immediately", "fixed"),
        ("What are your strengths?", "I am strong in OOP and databases.", "open"),
    ]:
        connection.execute("INSERT INTO answers (question, answer, kind) VALUES (?, ?, ?)", (question, answer, kind))
    connection.commit()
    rag.reindex(connection, MOCK)
    yield connection
    connection.close()


class PromptRecorder:
    """Stands in for ``ask_ai``: remembers every prompt, then lets the real mock ``ask_ai`` answer."""

    def __init__(self, real: Any) -> None:
        self._real = real
        self.calls: list[tuple[str, str]] = []  # (task, prompt)

    def __call__(self, task: str, prompt: str, **kwargs: Any) -> dict:
        self.calls.append((task, prompt))
        return self._real(task, prompt, **kwargs)


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> PromptRecorder:
    """Record every prompt sent through ``ask_ai``. Real Ollama embeddings are blocked."""

    def boom(*args: object, **kwargs: object) -> list[list[float]]:
        raise AssertionError("A test tried to call the real Ollama embeddings")

    monkeypatch.setattr(ai, "_call_ollama_embed", boom)
    rec = PromptRecorder(ai.ask_ai)
    monkeypatch.setattr(ai, "ask_ai", rec)  # drafting.py calls ai.ask_ai(...), so it reaches the recorder
    return rec


def read_form(name: str) -> list[FormField]:
    """Read a saved form page with the real reader (a headless browser on the saved HTML)."""
    html = (FORMS / name).read_text(encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        page.wait_for_timeout(300)  # let embedded frames load
        fields = read_fields(page)
        browser.close()
    return fields


def leaks_in(prompt: str, allowed_numbers: frozenset[str] = frozenset()) -> list[str]:
    """Everything private found in one prompt, as readable descriptions (empty = clean).

    ``allowed_numbers``: long numbers that belong to the form, not to you (a box's ``maxlength``).
    """
    found: list[str] = []
    lowered = prompt.lower()
    digits_only = re.sub(r"\D", "", prompt)
    for kind, spellings in PRIVATE.items():
        for spelling in spellings:
            plain_hit = spelling.lower() in lowered
            digit_hit = spelling.replace(" ", "").lstrip("+").isdigit() and re.sub(r"\D", "", spelling) in digits_only
            if plain_hit or digit_hit:
                found.append(f"{kind}: {spelling!r}")
    found += [f"email-shaped text: {m!r}" for m in EMAIL_SHAPE.findall(prompt)]
    found += [f"long number: {m!r}" for m in LONG_NUMBER.findall(prompt) if m not in allowed_numbers]
    return found


def form_numbers(fields: list[FormField]) -> frozenset[str]:
    """Long numbers that come from the form itself: each box's ``maxlength``."""
    return frozenset(str(f.max_length) for f in fields if f.max_length)


def assert_no_private_data(calls: list[tuple[str, str]], where: str, allowed_numbers: frozenset[str] = frozenset()) -> None:
    """Fail with the task and the leak found. Fails too when no prompt was recorded (it would prove nothing)."""
    assert calls, f"{where}: no prompt was recorded, so this test proved nothing"
    problems = []
    for task, prompt in calls:
        for leak in leaks_in(prompt, allowed_numbers):
            problems.append(f"[{task}] {leak}")
    assert not problems, f"{where}: private data reached the AI:\n  " + "\n  ".join(problems)


# ---- the tests -----------------------------------------------------------------------------------


def test_the_checker_itself_catches_each_kind_of_leak() -> None:
    """If this fails, a green privacy test below would mean nothing."""
    for kind, spellings in PRIVATE.items():
        for spelling in spellings:
            assert leaks_in(f"Some text {spelling} more text"), f"{kind} spelling {spelling!r} was not caught"
    assert leaks_in("call 0917-123-4567") and leaks_in("call 0917 123 4567")
    assert not leaks_in("Graduating 2027 with a 3.99 average, 3rd year, built in 2024.")


@pytest.mark.parametrize("fixture_name", FIXTURES)
def test_answer_form_sends_no_private_data_to_the_ai(conn: sqlite3.Connection, recorder: PromptRecorder, fixture_name: str) -> None:
    fields = read_form(fixture_name)
    assert fields, f"{fixture_name}: the reader found no fields"
    answer_form(conn, fields, page_url=f"file://{fixture_name}", settings=MOCK)
    assert_no_private_data(recorder.calls, fixture_name, form_numbers(fields))


def test_all_three_forms_in_one_session_send_no_private_data(conn: sqlite3.Connection, recorder: PromptRecorder) -> None:
    """Same check with the forms back to back, as in a real session (earlier answers feed later prompts)."""
    allowed: frozenset[str] = frozenset()
    for name in FIXTURES:
        fields = read_form(name)
        allowed |= form_numbers(fields)
        answer_form(conn, fields, page_url=f"file://{name}", settings=MOCK)
    assert_no_private_data(recorder.calls, "all three forms", allowed)


@pytest.mark.skipif(
    not hasattr(matcher, "pick_resume"),
    reason="the resume picker is not built yet (ROADMAP Phase 3, step 4). Expected as engine.matcher.pick_resume(conn, job_text, settings=...)",
)
def test_resume_picker_sends_no_private_data_to_the_ai(conn: sqlite3.Connection, recorder: PromptRecorder) -> None:
    job_text = "Junior Java developer. You will build Android apps with Kotlin and write unit tests."
    matcher.pick_resume(conn, job_text, settings=MOCK)  # type: ignore[attr-defined]
    assert_no_private_data(recorder.calls, "resume picker")
