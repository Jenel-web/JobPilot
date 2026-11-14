"""Tests for reflective questions ("what are your strengths", "how do you decide what to build").

Reflective answers are ONE free-written answer: a reflection drawn from your notes, never a new fact. Private
data, an invented number or name, and assistant talk are rejected; style problems are only warnings. The AI and
the search are faked; the fake search knows 5 projects so the "best 2 of 5" choice can be checked.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from engine import ai, rag
from engine.db import connect, init_db
from engine.forms import drafting
from engine.forms.answers import answer_field, is_company_question, is_reflective, is_story
from engine.forms.drafting import DraftError, reflect_answer
from engine.forms.reader import FormField
from engine.profile import load_answers
from engine.settings import Settings

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
    "I decide what to build by starting from problems I have seen people struggle with. "
    "CheatNoNo came from students cheating on online exams, and MJ Cinema came from not having built a full booking system "
    "after learning Spring Boot. What I look for is the hard part first, like keeping the live camera feed in sync."
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
    hits.append(_hit(102, "profile", "preferences", "Target roles: Java developer intern. Job types: internship.", 0.5))
    for n, (ref, text, score) in enumerate([
        ("about:why_software_engineering", "Why I like software engineering: a small idea can help many people.", 0.72),
        ("about:goals", "My goals. In five years: lead a small team.", 0.66),
        ("about:strength:Finishing", "Strength: Finishing. Evidence: I shipped before the deadline.", 0.6),
        ("about:values", "What I value: honest work.", 0.4),
    ]):
        hits.append(_hit(110 + n, "profile", ref, text, score))
    wanted = set(sources or rag.SOURCES)
    return sorted((h for h in hits if h.source in wanted), key=lambda h: -h.score)[:k]


class FakeAI:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.tasks: list[str] = []
        self.reply: object = None

    def answer(self, text: str, confidence: float = 0.8) -> None:
        """Reply with one free-written answer."""
        self.reply = {"answer": text, "confidence": confidence}

    def __call__(self, task: str, prompt: str, **kwargs: object) -> dict:
        self.tasks.append(task)
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
        "Why do you like software engineering?",
        "Why did you choose to study IT?",
        "Why are you passionate about technology?",
        "What got you into programming?",
        "Where do you see yourself in five years?",
        "What are your career goals?",
        "What makes you a good fit for a developer role?",
        "How have you grown as a developer?",
        "Is there anything else you would like us to know?",
        "Explain what software quality means to you.",
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
        "Cover letter",
        "What are your hobbies?",
        "Why do you want to work here?",
        "What programming languages do you know?",
        "How many years of experience do you have?",
        "List your technical skills",
    ],
)
def test_factual_questions_are_not_reflective(label: str) -> None:
    assert not is_reflective(label), label


@pytest.mark.parametrize(
    "label",
    [
        "Describe a project you are proud of",
        "Tell us about a challenge you faced",
        "Describe a time you worked in a team",
        "What is the most challenging project you have built?",
        "Tell us about a project you built",
    ],
)
def test_story_questions_are_recognised(label: str) -> None:
    assert is_story(label), label


def test_opinion_questions_are_not_story_questions() -> None:
    assert not is_story("Why do you like software engineering?")
    assert not is_story("What are your strengths?")


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


# ---- choosing the facts: best 2 of 5 projects --------------------------------------------------------------------


def test_facts_are_the_two_best_projects_plus_profile() -> None:
    facts = drafting.gather_reflective_facts(None, QUESTION)  # type: ignore[arg-type]
    refs = [h.ref for h in facts]
    projects = {h.ref.replace(" (story)", "") for h in facts if h.source == "project"}
    assert projects == {"CheatNoNo", "MJ Cinema"}
    assert "CheatNoNo (story)" in refs and "summary" in refs and "skills" in refs
    assert "preferences" in refs  # target roles: what a "where do you see yourself" question needs
    about = [r for r in refs if r.startswith("about:")]
    assert about == ["about:why_software_engineering", "about:goals", "about:strength:Finishing"]  # the best 3 only


def test_each_project_is_reduced_to_what_started_it_and_what_was_hard() -> None:
    facts = drafting.gather_reflective_facts(None, QUESTION)  # type: ignore[arg-type]
    cheat = next(h for h in facts if h.ref == "CheatNoNo (story)")
    assert "What started it: students cheated on online exams" in cheat.text
    assert "What was hard: keeping the live camera feed in sync" in cheat.text
    assert "proctoring platform" not in cheat.text  # the Solution (a resume bullet) is left out
    assert not any(h.ref == "CheatNoNo" for h in facts)  # so is the technology overview


def test_the_prompt_holds_the_two_best_projects_and_the_writing_rules(fake_ai: FakeAI) -> None:
    fake_ai.answer(GOOD)
    reflect_answer(None, box())  # type: ignore[arg-type]
    prompt = fake_ai.prompts[0]
    assert "CheatNoNo" in prompt and "MJ Cinema" in prompt
    assert "EconLens" not in prompt and "Countdown Math Arena" not in prompt and "Pag-IBIG" not in prompt
    assert "{{" not in prompt and "What was hard" in prompt  # every placeholder filled, the notes are in
    assert "NEVER add a fact" in prompt and "reflective sentence" in prompt
    assert "Aim for about 5 to 8 sentences" in prompt  # a big box asks for a fuller answer
    assert "Budget Tracker" not in prompt  # no worked example for the model to copy


def test_a_question_about_you_asks_for_a_direct_answer_then_moments_then_a_reflection(fake_ai: FakeAI) -> None:
    fake_ai.answer(GOOD)
    reflect_answer(None, box())  # type: ignore[arg-type]
    prompt = fake_ai.prompts[0]
    assert "answering the question directly" in prompt and "one or two real moments" in prompt
    assert "The impact" not in prompt  # the XYZ shape is for stories


def test_a_story_question_asks_for_impact_then_what_you_did_then_a_reflection(fake_ai: FakeAI) -> None:
    fake_ai.answer(GOOD)
    reflect_answer(None, box("Describe a project you are proud of"), single_project=True)  # type: ignore[arg-type]
    prompt = fake_ai.prompts[0]
    assert "ONE project" in prompt and "The impact" in prompt and "What you did to get there" in prompt
    assert "CheatNoNo" in prompt and "MJ Cinema" not in prompt  # only the best project


def test_a_small_box_asks_for_a_short_answer(fake_ai: FakeAI) -> None:
    fake_ai.answer("I start from a real problem, like CheatNoNo.")
    reflect_answer(None, box(type="text", max_length=300))  # type: ignore[arg-type]
    assert "Write 2 sentences" in fake_ai.prompts[0]


# ---- a good answer -------------------------------------------------------------------------------------------------


def test_the_answer_is_the_models_own_text_untouched(fake_ai: FakeAI) -> None:
    fake_ai.answer(GOOD)
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert result.ok and result.text == GOOD and result.note == ""
    assert result.source == "CheatNoNo; MJ Cinema" and result.confidence == 0.8


def test_new_reflective_question_is_a_flagged_interpretation(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    no_match(monkeypatch)
    fake_ai.answer(GOOD)
    result = answer_field(conn, box(), {})
    assert (result.value, result.source, result.flagged) == (GOOD, "draft", True)
    assert "interpretation" in result.note and "CheatNoNo" in result.note and "Warnings" not in result.note


def test_why_do_you_like_question_gets_the_reflective_task(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    no_match(monkeypatch)
    fake_ai.answer(GOOD)
    result = answer_field(conn, box("Why do you like software engineering?"), {})
    assert fake_ai.tasks == ["reflect_text"] and result.source == "draft" and "interpretation" in result.note


def test_a_story_question_sends_only_the_best_project(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    no_match(monkeypatch)
    fake_ai.answer("CheatNoNo began when students cheated on online exams and teachers could not see it. I built a way to see it.")
    result = answer_field(conn, box("Describe a project you are proud of"), {})
    assert result.value and "CheatNoNo" in fake_ai.prompts[0] and "MJ Cinema" not in fake_ai.prompts[0]


def test_factual_question_still_uses_the_strict_prompt(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    no_match(monkeypatch)
    fake_ai.reply = {"answers": []}
    answer_field(conn, box("Which programming languages do you know?"), {})
    assert "Use ONLY the FACTS" in fake_ai.prompts[0] and "list of technologies" in fake_ai.prompts[0]


# ---- hard blocks: the answer is rejected --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("I built 12 apps and CheatNoNo came from students cheating on exams.", "12"),
        ("CheatNoNo cut review time by 90 percent for the teachers.", "90"),
        ("I used Redis in CheatNoNo to keep the camera feed in sync.", "Redis"),
        ("CheatNoNo came from cheating, and I worked at Globex on it.", "Globex"),
        ("CheatNoNo came from cheating. Write to me at juan.fake@example.com.", "email"),
        ("CheatNoNo came from cheating. Call me on +63 917 123 4567.", "phone"),
        ("As an AI language model, I cannot describe CheatNoNo.", "assistant"),
        ("I'm sorry, but I can't say more. CheatNoNo came from students cheating on online exams.", "assistant only"),  # no other check can catch this one
    ],
)
def test_invented_facts_private_data_and_assistant_talk_are_rejected(fake_ai: FakeAI, text: str, why: str) -> None:
    fake_ai.answer(text)
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert not result.ok and result.note, why


def test_an_empty_reply_or_zero_confidence_is_rejected(fake_ai: FakeAI) -> None:
    fake_ai.answer("")
    assert not reflect_answer(None, box()).ok  # type: ignore[arg-type]
    fake_ai.answer(GOOD, confidence=0.0)
    assert not reflect_answer(None, box()).ok  # type: ignore[arg-type]


def test_a_reflection_may_not_name_a_tool_that_is_not_in_the_notes(fake_ai: FakeAI) -> None:
    fake_ai.answer("CheatNoNo taught me a lot about Kubernetes.")
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert not result.ok and "Kubernetes" in result.note


def test_a_reflection_about_what_you_learned_is_allowed(fake_ai: FakeAI) -> None:
    fake_ai.answer("CheatNoNo taught me to fix the hard part first, and MJ Cinema taught me to expect two people to want one seat.")
    assert reflect_answer(None, box()).ok  # type: ignore[arg-type]


def test_a_tool_named_in_the_notes_may_be_named_in_the_answer(fake_ai: FakeAI) -> None:
    fake_ai.answer("MJ Cinema was my first full project after I learned Spring Boot, and CheatNoNo came from cheating.")
    assert reflect_answer(None, box()).ok  # type: ignore[arg-type]  # Spring Boot is in the MJ Cinema note


def test_ai_failure_is_a_rejected_result(fake_ai: FakeAI) -> None:
    fake_ai.reply = ai.AIError("down")
    assert not reflect_answer(None, box()).ok  # type: ignore[arg-type]


def test_no_projects_means_no_ai_call(fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rag, "retrieve", lambda *a, **k: [])
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert not result.ok and fake_ai.prompts == []


# ---- warnings: the answer is still given, untouched -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "warning"),
    [
        ("CheatNoNo came from cheating. I am excited to make a positive impact on people's lives.", "stock phrases"),
        ("CheatNoNo came from cheating. This demonstrates my ability to lead.", "praises you"),
        ("CheatNoNo came from cheating, and I always keep the camera feed in sync.", "inflated word 'always'"),
        ("I think CheatNoNo came from cheating. I believe MJ Cinema came from a gap.", "start with 'I think'"),
        ("I like CheatNoNo. I like MJ Cinema. I like both of them.", "three sentences start with"),
        ("What started it: students cheated on online exams, which is why I built CheatNoNo.", "repeats a note label"),
        ("Say them in your own words shaped to the question, said CheatNoNo.", "repeats wording from the prompt"),
        ("The applicant built CheatNoNo after students cheated on online exams.", "first person"),
    ],
)
def test_style_problems_are_warnings_and_the_text_is_kept_as_written(fake_ai: FakeAI, text: str, warning: str) -> None:
    fake_ai.answer(text)
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert result.ok and result.text == text  # nothing is deleted or rewritten
    assert warning in result.note


def test_a_list_of_your_technologies_is_a_warning(fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drafting, "_tech_terms", lambda conn: {"java", "react", "spring boot"})
    fake_ai.answer("CheatNoNo came from cheating, and I used Java, React and Spring Boot for it.")
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert result.ok and "a list of technologies" in result.note


def test_more_sentences_than_the_box_suggests_is_a_warning(fake_ai: FakeAI) -> None:
    fake_ai.answer("CheatNoNo came from cheating. " + "I kept working on it. " * 6)
    result = reflect_answer(None, box(type="text", max_length=300))  # type: ignore[arg-type]  # a 2-sentence box
    assert result.ok and "7 sentences, more than the 2" in result.note


def test_warnings_reach_the_note_of_the_field_answer(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    no_match(monkeypatch)
    fake_ai.answer("CheatNoNo came from cheating. I am excited to keep building.")
    result = answer_field(conn, box(), {})
    assert result.value == "CheatNoNo came from cheating. I am excited to keep building."
    assert "Warnings: stock phrases ('excited')" in result.note and result.flagged


# ---- length: only a real limit of the box matters -----------------------------------------------------------------------


def test_a_long_answer_is_cut_after_the_last_whole_sentence_that_fits(fake_ai: FakeAI) -> None:
    fake_ai.answer("CheatNoNo came from cheating. " + "I kept working on the hard part of it. " * 40)
    result = reflect_answer(None, box())  # type: ignore[arg-type]  # no limit stated: the default box holds 1500 characters
    assert result.ok and len(result.text) <= 1500 and result.text.endswith(".")
    assert "cut after the last whole sentence" in result.note


def test_a_real_limit_on_the_box_cuts_to_whole_sentences(fake_ai: FakeAI) -> None:
    fake_ai.answer("CheatNoNo came from cheating. I built a way to see it. I kept working on the hard part of it for weeks.")
    result = reflect_answer(None, box(type="textarea", max_length=80))  # type: ignore[arg-type]
    assert result.text == "CheatNoNo came from cheating. I built a way to see it." and "cut" in result.note


def test_a_first_sentence_longer_than_the_box_is_rejected(fake_ai: FakeAI) -> None:
    fake_ai.answer("CheatNoNo came from students cheating on online exams and teachers could not see any of it at all.")
    result = reflect_answer(None, box(type="text", max_length=40))  # type: ignore[arg-type]
    assert not result.ok and "longer than the box" in result.note


def test_the_mock_fixture_is_one_free_answer() -> None:
    reply = ai.ask_ai("reflect_text", "", settings=Settings(run_mode="mock"))
    assert reply["answer"] and reply["confidence"] > 0 and set(reply) == {"answer", "confidence"}


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


# ---- richer facts straight from your data ---------------------------------------------------------------------------------


@pytest.fixture
def rich_conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    from engine.profile import load_profile

    profile = {
        "first_name": "Juan", "last_name": "Dela Cruz",
        "projects": [
            {"name": "CheatNoNo", "problem": "students cheated on online exams and teachers could not see it",
             "hardest_part": "keeping the live camera feed in sync", "solution": "A chrome extension and a dashboard.",
             "why_i_built_it": "I watched classmates share answers in a group chat.",
             "key_decision": "I chose Supabase because I did not have time to build a backend.",
             "what_i_learned": "Decide the architecture before writing code.", "result": "Cut review from 10 minutes to 20 seconds."},
            {"name": "MJ Cinema", "problem": "I had just learned Spring Boot but had never built a full-stack project",
             "hardest_part": "stopping two people booking the same seat"},
        ],
        "about_me": {"voice_notes": "Direct and plain, short sentences."},
    }
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    connection = connect(":memory:")
    init_db(connection)
    load_profile(connection, path, tmp_path)
    yield connection
    connection.close()


def test_projects_use_your_own_fields_from_the_database(rich_conn: sqlite3.Connection) -> None:
    facts = drafting.gather_reflective_facts(rich_conn, QUESTION)
    cheat = next(h for h in facts if h.ref == "CheatNoNo (story)").text
    assert "What started it: students cheated on online exams" in cheat
    assert "Why I built it: I watched classmates share answers in a group chat." in cheat
    assert "Key decision: I chose Supabase" in cheat and "What I learned: Decide the architecture" in cheat
    assert "chrome extension" not in cheat and "Result:" not in cheat  # the Solution is left out; Result only for a full answer


def test_a_full_answer_also_gets_the_result(rich_conn: sqlite3.Connection) -> None:
    facts = drafting.gather_reflective_facts(rich_conn, QUESTION, include_result=True)
    assert "Result: Cut review from 10 minutes to 20 seconds." in next(h for h in facts if h.ref == "CheatNoNo (story)").text


def test_the_two_best_projects_are_still_chosen_with_a_database(rich_conn: sqlite3.Connection) -> None:
    facts = drafting.gather_reflective_facts(rich_conn, QUESTION)
    assert {h.ref for h in facts if h.source == "project"} == {"CheatNoNo (story)", "MJ Cinema (story)"}


def test_your_voice_notes_go_into_the_prompt(rich_conn: sqlite3.Connection, fake_ai: FakeAI) -> None:
    fake_ai.answer(GOOD)
    reflect_answer(rich_conn, box())
    assert "Direct and plain, short sentences." in fake_ai.prompts[0]


def test_without_voice_notes_the_prompt_says_none(fake_ai: FakeAI) -> None:
    fake_ai.answer(GOOD)
    reflect_answer(None, box())  # type: ignore[arg-type]
    assert "(none given)" in fake_ai.prompts[0]
