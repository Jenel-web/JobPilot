"""Tests for reflective questions ("what are your strengths", "how do you decide what to build").

Reflective answers may state an OPINION drawn from several projects, but never a new fact. The AI and
the search are faked; the fake search knows 5 projects so the "best 3 of 5" choice can be checked.
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
from engine.forms.answers import answer_field, is_company_question, is_reflective
from engine.forms.drafting import DraftError, reflect_answer
from engine.forms.reader import FormField
from engine.profile import load_answers

QUESTION = "What are your strengths and how do you decide what apps to make?"

STORIES = {
    "CheatNoNo": ("Problem: students cheated on online exams and teachers could not see it. Solution: I built a proctoring "
                  "platform with React and Spring Boot. Hardest part: keeping the live camera feed in sync.", 0.80),
    "MJ Cinema": ("Problem: I had just learned Spring Boot but had never built a full-stack project. Solution: a cinema "
                  "booking system. Hardest part: stopping two people booking the same seat.", 0.70),
    "EconLens": ("Problem: economic data was hard to read. Solution: a dashboard. Hardest part: cleaning messy data.", 0.65),
    "Countdown Math Arena": ("Problem: math practice was boring. Solution: a timed game. Hardest part: fair scoring.", 0.50),
    "Pag-IBIG Housing": ("Problem: loan forms were confusing. Solution: an online form. Hardest part: validation.", 0.40),
}
GOOD = (
    "I think I decide what to build by starting from problems I have seen people struggle with. "
    "CheatNoNo came from students cheating on online exams, and MJ Cinema came from not having built a full booking system "
    "after learning Spring Boot. What I do is look for the hard part first, like keeping the live camera feed in sync."
)


def _hit(i: int, source: str, ref: str, text: str, score: float) -> rag.Hit:
    return rag.Hit(i, source, ref, text, score)


def fake_retrieve(conn: object, question: str, k: int = 5, *, sources: tuple[str, ...] | None = None, settings: object = None) -> list[rag.Hit]:
    hits: list[rag.Hit] = []
    for n, (name, (story, score)) in enumerate(STORIES.items()):
        hits.append(_hit(n * 2, "project", f"{name} (story)", f"Project: {name}. {story}", score))
        hits.append(_hit(n * 2 + 1, "project", name, f"Project: {name}. Technologies: React, Java.", score - 0.05))
    hits.append(_hit(100, "profile", "summary", "About me: IT student and full-stack developer.", 0.6))
    hits.append(_hit(101, "profile", "skills", "Skills: java, react, spring boot, sql.", 0.55))
    wanted = set(sources or rag.SOURCES)
    return sorted((h for h in hits if h.source in wanted), key=lambda h: -h.score)[:k]


class FakeAI:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.reply: object = None

    def answer(self, text: str, field: str = QUESTION) -> None:
        self.reply = {"answers": [{"field": field, "answer": text, "confidence": 0.8, "source": "project:CheatNoNo"}]}

    def __call__(self, task: str, prompt: str, **kwargs: object) -> dict:
        self.prompts.append(prompt)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply  # type: ignore[return-value]


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
        json.dumps([
            {"question": "What are your strengths?", "answer": "I am strong in OOP and databases.", "kind": "open"},
            {"question": "Why do you want to work for this company?", "answer": "I want to grow as a developer.", "kind": "open"},
        ]),
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


# ---- which questions are reflective / about the company ---------------------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        QUESTION,
        "What are your strengths?",
        "How do you decide what to build?",
        "How do you approach a hard problem?",
        "How do you handle tight deadlines?",
        "How do you learn new technologies?",
        "What motivates you?",
        "What drives you as a developer?",
        "Tell us about yourself",
        "Describe yourself in a few sentences",
        "What kind of projects do you enjoy?",
        "What do you care about when you build software?",
    ],
)
def test_reflective_questions_are_recognised(label: str) -> None:
    assert is_reflective(label), label


@pytest.mark.parametrize(
    "label",
    [
        "When can you start?",
        "What is your expected monthly salary?",
        "Which programming languages do you know?",
        "Describe a project you are proud of",
        "Cover letter",
        "What are your hobbies?",
        "Why do you want to work here?",
    ],
)
def test_factual_questions_are_not_reflective(label: str) -> None:
    assert not is_reflective(label), label


@pytest.mark.parametrize(
    "label",
    ["Why do you want to work here?", "Why do you want to join us?", "Why this company?", "Why are you interested in this role?",
     "What attracts you to our company?", "Why do you want to work for this company?"],
)
def test_company_questions_are_recognised(label: str) -> None:
    assert is_company_question(label), label


def test_other_questions_are_not_company_questions() -> None:
    assert not is_company_question("What are your strengths?")
    assert not is_company_question("Why did you choose to study IT?")


# ---- company questions wait for the job post (Phase 4) ---------------------------------------------------------


def test_new_company_question_is_left_for_you_and_never_sent_to_the_ai(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    no_match(monkeypatch)
    result = answer_field(conn, box("Why do you want to work here?"), {})
    assert result.value == "" and result.flagged and "job post" in result.note and fake_ai.prompts == []


def test_matched_open_company_answer_keeps_the_saved_text(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    match(monkeypatch, "Why do you want to work for this company?")
    result = answer_field(conn, box("Why do you want to work here?"), {})
    assert result.value == "I want to grow as a developer." and result.flagged and "job post" in result.note
    assert fake_ai.prompts == []


# ---- choosing the facts: best 3 of 5 projects --------------------------------------------------------------------


def test_facts_are_the_three_best_projects_plus_profile() -> None:
    facts = drafting.gather_reflective_facts(None, QUESTION)  # type: ignore[arg-type]
    refs = [h.ref for h in facts]
    projects = {r.replace(" (story)", "") for r in refs if r not in ("summary", "skills")}
    assert projects == {"CheatNoNo", "MJ Cinema", "EconLens"}
    assert "CheatNoNo (story)" in refs and "summary" in refs and "skills" in refs


def test_reflective_prompt_holds_the_three_stories_and_the_voice_rules(fake_ai: FakeAI) -> None:
    fake_ai.answer(GOOD)
    reflect_answer(None, box())  # type: ignore[arg-type]
    prompt = fake_ai.prompts[0]
    assert "CheatNoNo" in prompt and "MJ Cinema" in prompt and "EconLens" in prompt
    assert "Countdown Math Arena" not in prompt and "Pag-IBIG" not in prompt
    assert "I think" in prompt and "Hardest part" in prompt and "{{" not in prompt


# ---- a good reflective answer -------------------------------------------------------------------------------------


def test_good_reflective_answer_passes_and_lists_the_projects_it_used(fake_ai: FakeAI) -> None:
    fake_ai.answer(GOOD)
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert result.ok and result.text == GOOD
    assert result.source == "CheatNoNo, MJ Cinema"


def test_new_reflective_question_is_a_flagged_interpretation(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    no_match(monkeypatch)
    fake_ai.answer(GOOD)
    result = answer_field(conn, box(), {})
    assert (result.value, result.source, result.flagged) == (GOOD, "draft", True)
    assert "interpretation" in result.note and "CheatNoNo" in result.note


def test_factual_question_still_uses_the_strict_prompt(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    no_match(monkeypatch)
    fake_ai.reply = {"answers": []}
    answer_field(conn, box("Which programming languages do you know?"), {})
    assert "Use ONLY the FACTS" in fake_ai.prompts[0]
    assert "pattern" not in fake_ai.prompts[0]


# ---- rejected reflective answers ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("I think I build things people need. CheatNoNo came from students cheating on online exams.", "only one project"),
        ("I build things from problems people have. CheatNoNo and MJ Cinema both came from real problems, so I start there.", "no hedge"),
        ("I think I always start from a real problem, like CheatNoNo and MJ Cinema.", "overclaim: always"),
        ("I believe I am passionate about problems, like CheatNoNo and MJ Cinema.", "overclaim: passionate"),
        ("I think CheatNoNo and MJ Cinema show I like Kubernetes style work.", "invented tool"),
        ("I think CheatNoNo and MJ Cinema took me 9 months.", "invented number"),
        ("They think CheatNoNo and MJ Cinema show the applicant solves problems.", "third person"),
    ],
)
def test_bad_reflective_answers_are_rejected(fake_ai: FakeAI, text: str, why: str) -> None:
    fake_ai.answer(text)
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert not result.ok and result.note, why


def test_a_short_box_needs_only_one_project(fake_ai: FakeAI) -> None:
    fake_ai.answer("I think I start from a real problem, like CheatNoNo.")
    assert reflect_answer(None, box(type="text", max_length=200)).ok  # type: ignore[arg-type]


def test_ai_failure_is_a_rejected_result(fake_ai: FakeAI) -> None:
    fake_ai.reply = ai.AIError("down")
    assert not reflect_answer(None, box()).ok  # type: ignore[arg-type]


def test_no_projects_means_no_ai_call(fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rag, "retrieve", lambda *a, **k: [])
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert not result.ok and fake_ai.prompts == []


# ---- refusals and matched open answers -----------------------------------------------------------------------------------


def test_reflect_refuses_sensitive_questions_and_non_open_answers(fake_ai: FakeAI) -> None:
    with pytest.raises(DraftError):
        reflect_answer(None, box("What are your strengths as it relates to your disability?"))  # type: ignore[arg-type]
    with pytest.raises(DraftError):
        reflect_answer(None, box(), "No", "protected")  # type: ignore[arg-type]
    assert fake_ai.prompts == []


def test_matched_open_reflective_answer_uses_the_saved_text_as_a_fact(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    match(monkeypatch, "What are your strengths?")
    fake_ai.answer(GOOD)
    result = answer_field(conn, box(), {})
    assert result.source == "bank" and result.kind == "open" and result.flagged and result.value == GOOD
    assert "I am strong in OOP and databases." in fake_ai.prompts[0]


def test_failed_reflective_rewrite_falls_back_to_the_saved_text(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    match(monkeypatch, "What are your strengths?")
    fake_ai.reply = ai.AIError("down")
    result = answer_field(conn, box(), {})
    assert result.value == "I am strong in OOP and databases." and result.flagged and "saved text" in result.note
