"""Tests for "Why do you want to work here?": the company brief and the answer written from it.

The AI never knows the company. A first step copies notes out of the JOB POST (the brief) and code drops every
note the post does not back up; a second step writes the answer from the brief and your own notes, and code rejects
invented facts and claims like "I heard...". The AI and the search are faked; one test uses the mock fixture.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from engine import ai, rag
from engine.db import connect, init_db
from engine.forms import drafting
from engine.forms.answers import answer_field, answer_form, is_company_question, preview_company_answer
from engine.forms.drafting import CompanyBrief, DraftError, build_company_brief, company_answer
from engine.forms.reader import FormField
from engine.profile import load_answers
from engine.settings import Settings
from tests.test_reflective import fake_retrieve

POST = (
    "Junior Software Engineer at Brightwave\n"
    "Brightwave builds scheduling software for small clinics in the Philippines. We want clinics to spend less time on "
    "paperwork. We ship small and learn fast.\n"
    "What you will do: build features for the clinic scheduling app. Fix bugs reported by clinics.\n"
    "You are a student who likes building things."
)
THIN_POST = (
    "Junior Software Engineer\n"
    "What you will do: build features for the scheduling app. Fix bugs reported by users.\n"
    "Requirements: a student who likes building things."
)
BRIEF_REPLY = {
    "company": "Brightwave",
    "role": "Junior Software Engineer",
    "what_they_do": "Brightwave builds scheduling software for small clinics in the Philippines.",
    "mission": "to help small clinics spend less time on paperwork",
    "values": ["we ship small and learn fast"],
    "duties": ["build features for the clinic scheduling app", "fix bugs reported by clinics"],
    "quotes": ["Brightwave builds scheduling software for small clinics in the Philippines"],
}
GOOD = (
    "Brightwave builds scheduling software for small clinics in the Philippines, and I like that it helps them spend "
    "less time on paperwork. I enjoy building things, like CheatNoNo, which began when students cheated on online exams. "
    "I would love to work with you toward the same goal."
)
QUESTION = "Why do you want to work here?"


class FakeAI:
    """Answers ``company_brief`` and ``reflect_text`` separately, and remembers every prompt."""

    def __init__(self) -> None:
        self.brief: object = dict(BRIEF_REPLY)
        self.answer: object = {"answer": GOOD, "confidence": 0.8}
        self.calls: list[tuple[str, str]] = []

    def __call__(self, task: str, prompt: str, **kwargs: object) -> dict:
        self.calls.append((task, prompt))
        reply = self.brief if task == "company_brief" else self.answer
        if isinstance(reply, Exception):
            raise reply
        return reply  # type: ignore[return-value]

    def prompts(self, task: str) -> list[str]:
        return [p for t, p in self.calls if t == task]


@pytest.fixture
def fake_ai(monkeypatch: pytest.MonkeyPatch) -> FakeAI:
    fake = FakeAI()
    monkeypatch.setattr(ai, "ask_ai", fake)
    return fake


@pytest.fixture(autouse=True)
def facts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rag, "retrieve", fake_retrieve)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    path = tmp_path / "answers.json"
    path.write_text(
        json.dumps([{"question": "Why do you want to work for this company?", "answer": "I want to grow as a developer.", "kind": "open"}]),
        encoding="utf-8",
    )
    connection = connect(":memory:")
    init_db(connection)
    load_answers(connection, path)
    yield connection
    connection.close()


def box(label: str = QUESTION, type: str = "textarea", **kw: object) -> FormField:
    return FormField(label=label, type=type, **kw)  # type: ignore[arg-type]


def no_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rag, "match_saved_question", lambda *a, **k: rag.SavedMatch(None, False, (), rag.MATCH_THRESHOLD))


def match(monkeypatch: pytest.MonkeyPatch, ref: str) -> None:
    hit = rag.Hit(1, "answer", ref, ref, 0.95)
    monkeypatch.setattr(rag, "match_saved_question", lambda *a, **k: rag.SavedMatch(hit, True, ("open",), rag.MATCH_THRESHOLD))


# ---- which questions count -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    ["What do you know about us?", "What do you know about our company?", "What do you like about our team?",
     "Tell us why you want to join", "Why did you apply?", "Why do you want to work here?"],
)
def test_more_ways_of_asking_about_the_company_are_recognised(label: str) -> None:
    assert is_company_question(label), label


# ---- step 1: the brief holds only what the post says -----------------------------------------------------------


def test_the_brief_keeps_what_the_post_says(fake_ai: FakeAI) -> None:
    brief = build_company_brief(POST)
    assert brief is not None and not brief.thin and brief.usable
    assert brief.company == "Brightwave" and "scheduling software" in brief.what_they_do
    assert brief.duties and brief.quotes and brief.dropped == ()


def test_the_brief_prompt_holds_the_post_and_forbids_outside_knowledge(fake_ai: FakeAI) -> None:
    build_company_brief(POST)
    prompt = fake_ai.prompts("company_brief")[0]
    assert "Brightwave builds scheduling software" in prompt and "{{" not in prompt
    assert "You know nothing about this company from anywhere else" in prompt


def test_notes_the_post_does_not_back_up_are_dropped(fake_ai: FakeAI) -> None:
    fake_ai.brief = {
        **BRIEF_REPLY,
        "mission": "to be the number one startup builder in Southeast Asia",  # not in the post
        "values": ["we ship small and learn fast", "we were funded by Sequoia"],  # the second is invented
        "quotes": ["Brightwave builds scheduling software for small clinics in the Philippines", "a quote nobody wrote"],
    }
    brief = build_company_brief(POST)
    assert brief is not None
    assert brief.mission == "" and brief.values == ("we ship small and learn fast",)
    assert brief.quotes == ("Brightwave builds scheduling software for small clinics in the Philippines",)
    dropped = " | ".join(brief.dropped)
    assert "Southeast Asia" in dropped and "Sequoia" in dropped and "a quote nobody wrote" in dropped


def test_a_company_name_that_is_not_in_the_post_is_dropped(fake_ai: FakeAI) -> None:
    fake_ai.brief = {**BRIEF_REPLY, "company": "Stellar PH"}
    brief = build_company_brief(POST)
    assert brief is not None and brief.company == "" and any("Stellar PH" in d for d in brief.dropped)


def test_a_post_that_says_nothing_about_the_company_gives_a_thin_brief(fake_ai: FakeAI) -> None:
    # The model invents what the company does (it "knows" it); the post does not say it, so the code removes it.
    fake_ai.brief = {**BRIEF_REPLY, "company": "", "role": "Junior Software Engineer",
                     "duties": ["build features for the scheduling app"]}
    brief = build_company_brief(THIN_POST)
    assert brief is not None and brief.thin and brief.usable
    assert brief.what_they_do == "" and brief.mission == "" and brief.values == ()
    assert brief.role == "Junior Software Engineer" and brief.duties == ("build features for the scheduling app",)
    assert brief.dropped  # the invented company notes are listed


def test_nothing_usable_in_the_post_means_no_company_answer(fake_ai: FakeAI) -> None:
    fake_ai.brief = {"company": "", "role": "", "what_they_do": "Makes rockets.", "mission": "", "values": [], "duties": [], "quotes": []}
    brief = build_company_brief(THIN_POST)
    assert brief is not None and not brief.usable
    assert company_answer(None, box(), brief).note.startswith("the job post says nothing")  # type: ignore[arg-type]


def test_no_text_or_a_failed_ai_gives_no_brief(fake_ai: FakeAI) -> None:
    assert build_company_brief(None) is None and build_company_brief("   ") is None
    fake_ai.brief = ai.AIError("down")
    assert build_company_brief(POST) is None


def test_a_brief_reply_with_an_email_is_not_used(fake_ai: FakeAI) -> None:
    fake_ai.brief = {**BRIEF_REPLY, "mission": "write to jane.doe@example.com"}
    assert build_company_brief(POST) is None


def test_the_mock_fixture_is_a_valid_brief_and_works_through_ask_ai() -> None:
    brief = build_company_brief(POST, Settings(run_mode="mock"))  # the real ask_ai, reading fixtures/ai/company_brief.json
    assert brief is not None and brief.company == "Brightwave" and not brief.thin


# ---- step 2: the answer ----------------------------------------------------------------------------------------


def test_a_full_brief_gives_a_first_person_company_answer(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    no_match(monkeypatch)
    result = answer_field(conn, box(), {}, job_text=POST)
    assert result.value == GOOD and result.source == "draft" and result.flagged
    assert "company brief" in result.note and "written from the job post" in result.note
    prompt = fake_ai.prompts("reflect_text")[0]
    assert "What they do: Brightwave builds scheduling software" in prompt and "{{" not in prompt
    assert "Start with the company" in prompt and "toward the same goal" in prompt  # the shape you asked for
    assert "CheatNoNo" in prompt  # one real project from MY NOTES


def test_the_prompt_forbids_claiming_experience_with_the_company(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    no_match(monkeypatch)
    answer_field(conn, box(), {}, job_text=POST)
    prompt = fake_ai.prompts("reflect_text")[0]
    assert "Never write \"I heard\"" in prompt and "You have never used, visited or read about this company" in prompt


def test_a_thin_post_gives_a_role_focused_answer_and_says_so(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    no_match(monkeypatch)
    fake_ai.brief = {**BRIEF_REPLY, "company": "", "what_they_do": "", "mission": "", "values": [], "quotes": [],
                     "duties": ["build features for the scheduling app", "fix bugs reported by users"]}
    fake_ai.answer = {"answer": "I want to build features for the scheduling app and fix bugs reported by users, because I like building things, like CheatNoNo. I would like to contribute and grow in this role.", "confidence": 0.8}
    result = answer_field(conn, box(), {}, job_text=THIN_POST)
    assert result.value and "role only" in result.note and "about the role" in result.note
    prompt = fake_ai.prompts("reflect_text")[0]
    assert "write about the ROLE" in prompt and "Start with the company" not in prompt


def test_your_saved_answer_is_adapted_to_the_company(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    match(monkeypatch, "Why do you want to work for this company?")
    result = answer_field(conn, box(), {}, job_text=POST)
    assert result.source == "draft" and "your saved answer adapted" in result.note
    assert result.matched_question == "Why do you want to work for this company?"
    assert "I want to grow as a developer." in fake_ai.prompts("reflect_text")[0]  # it is a note about you


@pytest.mark.parametrize(
    "bad, reason",
    [
        ("From what I've heard, Brightwave has a great community. I like building things.", "claimed experience"),
        ("I have followed Brightwave for years and I like building things.", "claimed experience"),
        ("Brightwave builds scheduling software, and I like building things, just like Google does.", "'Google'"),
        ("Brightwave serves 500 clinics, and I like building things.", "number 500"),
        ("I am sorry, as an AI I cannot say why.", "assistant"),
        ("Brightwave builds scheduling software. Write to me at jane.doe@example.com.", "email"),
    ],
)
def test_an_answer_that_invents_a_fact_is_rejected_and_the_saved_text_is_kept(
    conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch, bad: str, reason: str
) -> None:
    match(monkeypatch, "Why do you want to work for this company?")
    fake_ai.answer = {"answer": bad, "confidence": 0.9}
    result = answer_field(conn, box(), {}, job_text=POST)
    assert result.value == "I want to grow as a developer." and result.source == "bank" and result.flagged
    assert "AI draft rejected" in result.note and reason in result.note


def test_a_rejected_new_company_answer_is_left_empty_for_you(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    no_match(monkeypatch)
    fake_ai.answer = {"answer": "I heard that Brightwave is great.", "confidence": 0.9}
    result = answer_field(conn, box(), {}, job_text=POST)
    assert result.value == "" and result.source == "none" and result.flagged and "rejected" in result.note


def test_no_job_post_keeps_the_old_behaviour_and_asks_the_ai_nothing(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    no_match(monkeypatch)
    assert answer_field(conn, box(), {}).value == "" and fake_ai.calls == []
    match(monkeypatch, "Why do you want to work for this company?")
    saved = answer_field(conn, box(), {})
    assert saved.value == "I want to grow as a developer." and "job post" in saved.note and fake_ai.calls == []


def test_a_failed_brief_falls_back_to_the_saved_text(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    match(monkeypatch, "Why do you want to work for this company?")
    fake_ai.brief = ai.AIError("down")
    result = answer_field(conn, box(), {}, job_text=POST)
    assert result.value == "I want to grow as a developer." and "saved text used as written" in result.note
    assert fake_ai.prompts("reflect_text") == []  # no answer was asked for without a brief


def test_company_answers_refuse_sensitive_questions_and_non_text_boxes() -> None:
    brief = CompanyBrief(company="Brightwave", what_they_do="Builds software.")
    with pytest.raises(DraftError):
        company_answer(None, box("Are you legally authorized to work here?"), brief)  # type: ignore[arg-type]
    with pytest.raises(DraftError):
        company_answer(None, box(type="select"), brief)  # type: ignore[arg-type]


# ---- one brief per form ----------------------------------------------------------------------------------------


def test_two_company_questions_on_one_form_read_the_post_once(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    no_match(monkeypatch)
    fields = [box("Why do you want to work here?"), box("Why are you interested in this role?")]
    answers = answer_form(conn, fields, job_text=POST, record=False)
    assert len(fake_ai.prompts("company_brief")) == 1  # the brief is built once...
    assert len(fake_ai.prompts("reflect_text")) == 2  # ...and used for both questions
    assert all(a.source == "draft" for a in answers)


def test_a_failed_brief_is_not_retried_for_every_question(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    no_match(monkeypatch)
    fake_ai.brief = ai.AIError("down")
    answer_form(conn, [box("Why do you want to work here?"), box("Why this company?")], job_text=POST, record=False)
    assert len(fake_ai.prompts("company_brief")) == 1


# ---- the preview used by `forms why-company` ----------------------------------------------------------------------


def test_the_preview_returns_the_brief_and_the_answer_and_saves_nothing(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    no_match(monkeypatch)
    brief, answer = preview_company_answer(conn, POST)
    assert brief is not None and brief.company == "Brightwave"
    assert answer.value == GOOD and answer.unknown_id is None  # record=False: nothing filed as unknown


def test_the_company_prompt_sections_exist_and_fill_completely() -> None:
    for section, values in (
        ("BRIEF", {"post": "x"}),
        ("COMPANY", dict(question="q", saved="", brief="b", facts="f", shape="s", length="l", max_sentences="3",
                          max_chars="300", voice="v", earlier="e")),
    ):
        assert "{{" not in drafting.load_prompt(section, **values)
