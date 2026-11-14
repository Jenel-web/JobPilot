"""Tests for reflective questions ("what are your strengths", "how do you decide what to build").

Reflective answers may state an OPINION drawn from several projects, but never a new fact. The AI and
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

    def answer(self, text: str) -> None:
        """Reply in the structured shape, splitting ``text`` into stance / examples / closing by sentence."""
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        if len(sentences) == 1:
            self.parts(sentences[0], [], sentences[0])  # one sentence is both stance and closing
        else:
            self.parts(sentences[0], sentences[1:-1], sentences[-1])

    def parts(self, stance: str, examples: list[str], closing: str, confidence: float = 0.8) -> None:
        self.reply = {"stance": stance, "examples": examples, "closing": closing, "confidence": confidence}

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


def test_reflective_prompt_holds_the_two_stories_and_the_shape_rules(fake_ai: FakeAI) -> None:
    fake_ai.answer(GOOD)
    reflect_answer(None, box())  # type: ignore[arg-type]
    prompt = fake_ai.prompts[0]
    assert "CheatNoNo" in prompt and "MJ Cinema" in prompt
    assert "EconLens" not in prompt and "Countdown Math Arena" not in prompt and "Pag-IBIG" not in prompt
    assert "I think" in prompt and "What was hard" in prompt and "{{" not in prompt
    assert "CLOSING" in prompt and "Do not reuse any wording from this prompt" in prompt
    assert "pulls you in" not in prompt  # a phrase in the prompt gets echoed into every answer
    assert "Budget Tracker" not in prompt  # no worked example for the model to copy


# ---- a good reflective answer -------------------------------------------------------------------------------------


def test_good_reflective_answer_passes_and_lists_the_projects_it_used(fake_ai: FakeAI) -> None:
    fake_ai.answer(GOOD)
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert result.ok and result.text == GOOD
    assert result.source == "CheatNoNo; MJ Cinema"


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
        ("I think I build things people need. CheatNoNo came from students cheating on online exams. To me that is the pattern.", "only one project"),
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


def test_a_confident_answer_with_no_hedging_is_accepted(fake_ai: FakeAI) -> None:
    fake_ai.answer(GOOD)
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert result.ok and "I think" not in result.text and "I believe" not in result.text


def test_leading_i_think_and_i_believe_are_removed_from_every_sentence(fake_ai: FakeAI) -> None:
    fake_ai.parts(
        "I think I start from real problems.",
        ["I believe CheatNoNo began with cheating.", "I feel that MJ Cinema began with a gap."],
        "I think what matters is the hard part.",
    )
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert result.ok
    assert result.text == (
        "I start from real problems. CheatNoNo began with cheating. MJ Cinema began with a gap. What matters is the hard part."
    )


def test_sentences_that_all_open_the_same_way_are_rejected(fake_ai: FakeAI) -> None:
    fake_ai.parts("I build from problems.", ["I build CheatNoNo for exams.", "I build MJ Cinema for seats."], "I build what people need.")
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert not result.ok and "same way" in result.note


def test_a_long_list_of_facts_cannot_hide_a_missing_second_project(fake_ai: FakeAI) -> None:
    # five fact sentences: only the first two survive, and they do not name MJ Cinema, so the evidence check fails
    fake_ai.answer(
        "I think I build from problems. CheatNoNo came from cheating. It uses React. It uses Spring Boot. "
        "MJ Cinema came from booking. What I do is start there."
    )
    assert not reflect_answer(None, box()).ok  # type: ignore[arg-type]


def test_copying_the_prompt_is_rejected(fake_ai: FakeAI) -> None:
    # the model once repeated its prompt example word for word; any 7-word run from the prompt is now refused
    fake_ai.answer("I think I should say what you want to grow toward, as CheatNoNo and MJ Cinema show.")
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert not result.ok and "prompt" in result.note


def test_why_do_you_like_question_now_gets_the_reflective_task_not_a_skills_list(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    no_match(monkeypatch)
    fake_ai.answer(GOOD)
    result = answer_field(conn, box("Why do you like software engineering?"), {})
    assert fake_ai.tasks == ["reflect_answer"] and result.source == "draft" and "interpretation" in result.note


def test_a_story_question_sends_only_the_best_project(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    no_match(monkeypatch)
    fake_ai.parts("I think the project I am proudest of started from a real problem.", ["CheatNoNo began when students cheated on online exams and teachers could not see it."],
                  "To me it shows I start from a real problem and then work on the hard part.")
    result = answer_field(conn, box("Describe a project you are proud of"), {})
    prompt = fake_ai.prompts[0]
    assert result.value and "CheatNoNo" in prompt and "MJ Cinema" not in prompt
    assert "AT MOST 1" in prompt


def test_a_story_answer_keeps_only_the_first_example(fake_ai: FakeAI) -> None:
    fake_ai.parts("I think I like hard problems.", ["CheatNoNo began with cheating.", "MJ Cinema began with a gap."], "To me that is the pattern.")
    result = reflect_answer(None, box("Describe a project you are proud of"), single_project=True)  # type: ignore[arg-type]
    assert result.ok and "CheatNoNo began with cheating." in result.text and "MJ Cinema" not in result.text


def test_factual_question_with_the_strict_prompt_is_told_not_to_answer_with_a_list(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    no_match(monkeypatch)
    fake_ai.reply = {"answers": []}
    answer_field(conn, box("Which programming languages do you know?"), {})
    assert "list of technologies" in fake_ai.prompts[0]


def test_a_big_box_asks_for_a_fuller_answer(fake_ai: FakeAI) -> None:
    fake_ai.answer(GOOD)
    reflect_answer(None, box())  # type: ignore[arg-type]
    prompt = fake_ai.prompts[0]
    assert "At most 8 sentence(s)" in prompt and "Explain properly" in prompt and "TWO sentences" in prompt


def test_a_small_box_stays_short(fake_ai: FakeAI) -> None:
    fake_ai.answer("I start from real problems, like CheatNoNo. What matters is the hard part, like MJ Cinema.")
    reflect_answer(None, box(max_length=300))  # type: ignore[arg-type]
    prompt = fake_ai.prompts[0]
    assert "At most 2 sentence(s)" in prompt and "Explain properly" not in prompt and "ONE short sentence" in prompt


def test_a_full_answer_with_longer_examples_is_accepted(fake_ai: FakeAI) -> None:
    fake_ai.parts(
        "I choose projects by the problem behind them.",
        [
            "CheatNoNo began when students cheated on online exams. I designed the whole system myself.",
            "MJ Cinema began after I had just learned Spring Boot. Stopping two people booking one seat was the hard part.",
        ],
        "What I look for is a real problem with a hard core. That is where I learn the most.",
    )
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert result.ok and result.text.count(".") == 7


def test_a_short_box_needs_only_one_project(fake_ai: FakeAI) -> None:
    fake_ai.parts("I think I start from a real problem, like CheatNoNo.", [], "To me that is what makes an app worth building.")
    assert reflect_answer(None, box(type="text", max_length=200)).ok  # type: ignore[arg-type]


def test_parts_without_full_stops_are_joined_as_proper_sentences(fake_ai: FakeAI) -> None:
    fake_ai.parts(
        "I think I start from real problems",
        ["CheatNoNo began with students cheating on online exams", "MJ Cinema began after I had just learned Spring Boot."],
        "What I do is look for the hard part first",
    )
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert result.ok
    assert result.text == (
        "I start from real problems. CheatNoNo began with students cheating on online exams. "
        "MJ Cinema began after I had just learned Spring Boot. What I do is look for the hard part first."
    )


def test_an_over_long_answer_is_trimmed_to_the_box_not_thrown_away(fake_ai: FakeAI) -> None:
    # the model ignores the sentence count: stance 2, examples 3 each, closing 7 = 15 sentences
    fake_ai.parts(
        "I start from real problems. I mean it.",
        ["CheatNoNo began with cheating. It was hard. It taught me a lot.", "MJ Cinema began with a gap. It was new. It taught me more."],
        "What I look for is a real problem. It has a hard core. That is where I learn. I like that. It keeps me honest. I repeat it. I do.",
    )
    result = reflect_answer(None, box())  # type: ignore[arg-type]  # a big box: 8 sentences
    sentences = re.split(r"(?<=[.!?])\s+", result.text)
    assert result.ok and len(sentences) == 8  # 1 stance + 2 + 2 examples + 3 closing
    assert result.text.startswith("I start from real problems. CheatNoNo began with cheating. It was hard. MJ Cinema")
    assert "It taught me" not in result.text and result.text.endswith("That is where I learn.")


def test_a_small_box_trims_each_example_to_one_sentence(fake_ai: FakeAI) -> None:
    fake_ai.parts("I start from real problems.", ["CheatNoNo began with cheating. It was hard.", "MJ Cinema began with a gap."], "What I look for is the hard core. And more.")
    result = reflect_answer(None, box(type="text", max_length=500))  # type: ignore[arg-type]  # budget: 4 sentences
    assert result.ok and "It was hard" not in result.text
    assert len(re.split(r"(?<=[.!?])\s+", result.text)) <= 4  # the budget of a 500-character box


def test_a_tiny_box_keeps_only_a_stance_and_a_closing(fake_ai: FakeAI) -> None:
    fake_ai.parts("I start from real problems, like CheatNoNo.", ["MJ Cinema began with a gap."], "What I look for is the hard core.")
    result = reflect_answer(None, box(type="text", max_length=300))  # type: ignore[arg-type]  # budget: 2 sentences
    assert result.ok and len(re.split(r"(?<=[.!?])\s+", result.text)) == 2 and "MJ Cinema" not in result.text


def test_a_capital_after_a_colon_is_not_an_invented_name() -> None:
    from engine.forms.drafting import _ungrounded_name

    assert _ungrounded_name("CheatNoNo: This began with a gap.", "CheatNoNo began with a gap") is None
    assert _ungrounded_name("CheatNoNo: Kubernetes began with a gap.", "CheatNoNo began with a gap") == "Kubernetes"


def test_the_closing_is_required(fake_ai: FakeAI) -> None:
    fake_ai.parts("I think I start from real problems, like CheatNoNo and MJ Cinema.", [], "")
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert not result.ok and "closing" in result.note


@pytest.mark.parametrize(
    "closing",
    [
        "I think both projects demonstrate my ability to lead.",
        "To me this shows I am a capable developer.",
        "I believe I am skilled at making decisions.",
        "I think this is where my skills and experience shine.",
        "To me I excel when I build from scratch.",
    ],
)
def test_a_closing_that_praises_instead_of_reflecting_is_rejected(fake_ai: FakeAI, closing: str) -> None:
    fake_ai.parts("I think I start from real problems.", ["CheatNoNo began with cheating.", "MJ Cinema began with a gap."], closing)
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert not result.ok and "praise" in result.note


def test_more_than_two_examples_are_cut_to_the_first_two(fake_ai: FakeAI) -> None:
    fake_ai.parts("I think I start from real problems.", ["CheatNoNo began with cheating.", "MJ Cinema began with a gap.", "EconLens began with news."], "To me that is the pattern.")
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert result.ok and "MJ Cinema began" in result.text and "EconLens" not in result.text


def test_the_mock_fixture_has_the_structured_shape() -> None:
    reply = ai.ask_ai("reflect_answer", "", settings=Settings(run_mode="mock"))
    assert reply["stance"] and reply["closing"] and len(reply["examples"]) <= 2


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


# ---- examples that read like speech, not a list ---------------------------------------------------------------------------


def test_a_project_name_colon_example_becomes_a_spoken_sentence(fake_ai: FakeAI) -> None:
    fake_ai.parts(
        "I choose projects by the problem behind them.",
        ["CheatNoNo: students cheated on online exams, so we built a way to see it.", "MJ Cinema: I had just learned Spring Boot."],
        "What I look for is a real problem with a hard core.",
    )
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert result.ok
    assert "With MJ Cinema, I had just learned Spring Boot." in result.text
    assert "MJ Cinema:" not in result.text


def test_a_colon_example_that_does_not_continue_with_a_person_is_left_alone(fake_ai: FakeAI) -> None:
    fake_ai.parts(
        "I choose projects by the problem behind them.",
        ["CheatNoNo: a proctoring platform for exams.", "MJ Cinema began after I had just learned Spring Boot."],
        "What I look for is a real problem with a hard core.",
    )
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert result.ok and "CheatNoNo: a proctoring platform" in result.text


# ---- length: only a real limit on the box rejects; the labels of the facts must not leak ----------------------------------------


def test_a_long_answer_is_fine_when_the_form_states_no_limit(fake_ai: FakeAI) -> None:
    long_example = ("CheatNoNo began when students cheated on online exams and teachers could not see it. " * 4).strip()
    fake_ai.parts("I choose projects by the problem behind them.", [long_example, "MJ Cinema began after I had just learned Spring Boot."],
                  "What I look for is a real problem with a hard core.")
    result = reflect_answer(None, box())  # type: ignore[arg-type]  # a textarea with no max_length
    assert result.ok  # never rejected for our own default size


def test_a_real_limit_on_the_box_still_rejects_a_long_answer(fake_ai: FakeAI) -> None:
    long_sentence = "I choose projects by the problem behind them, like CheatNoNo and MJ Cinema, " + "and I keep going back to that idea " * 6
    fake_ai.parts(long_sentence, [], "What I look for is a real problem with a hard core.")
    result = reflect_answer(None, box(max_length=200))  # type: ignore[arg-type]
    assert not result.ok and "characters" in result.note


@pytest.mark.parametrize("label", ["What started it", "What was hard", "Why I built it", "Key decision", "What I learned"])
def test_the_internal_fact_labels_must_not_leak_into_the_answer(fake_ai: FakeAI, label: str) -> None:
    fake_ai.parts("I choose projects by the problem behind them.", [f"CheatNoNo: {label}: students cheated.", "MJ Cinema began with a gap."],
                  "What I look for is a real problem with a hard core.")
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert not result.ok and "label" in result.note


def test_the_prompt_tells_the_model_not_to_write_the_labels(fake_ai: FakeAI) -> None:
    fake_ai.answer(GOOD)
    reflect_answer(None, box())  # type: ignore[arg-type]
    assert "Do not write these labels" in fake_ai.prompts[0]


def test_a_colon_example_that_continues_with_this_project_is_rewritten_too(fake_ai: FakeAI) -> None:
    fake_ai.parts("I choose projects by the problem behind them.",
                  ["CheatNoNo: This project started with students cheating on online exams.", "MJ Cinema began with a gap."],
                  "What I look for is a real problem with a hard core.")
    result = reflect_answer(None, box())  # type: ignore[arg-type]
    assert result.ok and "With CheatNoNo, it started with students cheating on online exams." in result.text
