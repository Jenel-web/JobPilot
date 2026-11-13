"""Tests for the AI side of the answer engine (engine/forms/drafting.py) and how answers.py uses it.

No real Ollama and no real search: ``ai.ask_ai`` and ``rag.retrieve`` are replaced, and the
replacement records every prompt so the tests can read exactly what the AI would have seen.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from engine import ai, learning, rag
from engine.db import connect, init_db
from engine.forms import drafting
from engine.forms.answers import answer_field
from engine.forms.drafting import DraftError, draft_answer, rewrite_open
from engine.forms.reader import FormField
from engine.profile import load_answers
from engine.settings import Settings

FACT = rag.Hit(
    1, "project", "EconLens PH",
    "Project: EconLens PH. Technologies: React, Python. A dashboard of Philippine economic data. Result: 4 charts live.",
    0.7,
)
QUESTION = "Describe a project you are proud of"
GOOD = "I built EconLens PH, a dashboard of Philippine economic data using React and Python. It has 4 charts live."
HOBBY = "What are your hobbies?"


class FakeAI:
    """Stands in for ``ai.ask_ai``: records prompts, returns what the test chose."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.reply: object = None

    def answer(self, text: str, *, field: str = QUESTION, confidence: float = 0.9, source: str = "project:EconLens PH") -> None:
        self.reply = {"answers": [{"field": field, "answer": text, "confidence": confidence, "source": source}]}

    def __call__(self, task: str, prompt: str, **kwargs: object) -> dict:
        assert task == "form_answer"
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
def facts(monkeypatch: pytest.MonkeyPatch) -> list[rag.Hit]:
    found = [FACT]
    monkeypatch.setattr(rag, "retrieve", lambda *args, **kwargs: list(found))
    return found


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    path = tmp_path / "answers.json"
    path.write_text(
        json.dumps(
            [
                {"question": "Tell us about your strengths", "answer": "I learn fast and finish what I start.", "kind": "open"},
                {"question": "When can you start?", "answer": "2 weeks notice", "kind": "fixed"},
                {"question": "Will you need visa sponsorship?", "answer": "No", "kind": "protected"},
            ]
        ),
        encoding="utf-8",
    )
    connection = connect(":memory:")
    init_db(connection)
    load_answers(connection, path)
    yield connection
    connection.close()


def box(label: str = QUESTION, type: str = "textarea", **kw: object) -> FormField:
    return FormField(label=label, type=type, **kw)  # type: ignore[arg-type]


# ---- the prompt file -------------------------------------------------------------------------


def test_prompt_sections_load_and_fill_every_placeholder() -> None:
    for section, extra in (("DRAFT", {}), ("REWRITE", {"saved": "I learn fast."})):
        text = drafting.load_prompt(section, question="Q?", facts="[project:X] fact", max_sentences="3", max_chars="500", **extra)
        assert "{{" not in text and "}}" not in text
        assert "Q?" in text and "[project:X] fact" in text
        assert "Never invent" in text and "first person" in text and "Do not write about the company" in text


def test_unknown_prompt_section_is_an_error() -> None:
    with pytest.raises(DraftError):
        drafting.load_prompt("NOPE")


# ---- a good draft -----------------------------------------------------------------------------


def test_good_draft_passes_and_the_prompt_holds_question_and_facts(fake_ai: FakeAI) -> None:
    fake_ai.answer(GOOD)
    result = draft_answer(None, box())  # type: ignore[arg-type]
    assert result.ok and result.text == GOOD and result.source == "project:EconLens PH"
    prompt = fake_ai.prompts[0]
    assert QUESTION in prompt and "[project:EconLens PH]" in prompt and "{{" not in prompt


def test_mock_mode_uses_the_canned_answer_for_its_own_question() -> None:
    mock = Settings(run_mode="mock")  # the real ask_ai runs and reads fixtures/ai/form_answer.json
    mine = draft_answer(None, box("Why do you want to work here?"), settings=mock)  # type: ignore[arg-type]
    assert mine.ok and mine.text.startswith("Mock answer")
    other = draft_answer(None, box(QUESTION), settings=mock)  # type: ignore[arg-type]
    assert not other.ok  # the canned reply for this question is "empty"


# ---- the checks on the reply ---------------------------------------------------------------------


def test_reply_for_another_field_is_rejected_unless_it_is_the_only_one(fake_ai: FakeAI) -> None:
    fake_ai.reply = {"answers": [
        {"field": "Something else", "answer": GOOD, "confidence": 0.9, "source": "project:EconLens PH"},
        {"field": "Third", "answer": GOOD, "confidence": 0.9, "source": "project:EconLens PH"},
    ]}
    assert not draft_answer(None, box()).ok  # type: ignore[arg-type]
    fake_ai.answer(GOOD, field="Describe a project you are proud of.")  # one answer, slightly different wording
    assert draft_answer(None, box()).ok  # type: ignore[arg-type]


def test_empty_answer_means_the_facts_do_not_cover_it(fake_ai: FakeAI) -> None:
    fake_ai.answer("", confidence=0.0, source="none")
    result = draft_answer(None, box())  # type: ignore[arg-type]
    assert not result.ok and "facts" in result.note


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("I built EconLens PH and 7 charts are live.", "number"),
        ("I built EconLens PH with Kubernetes and React.", "name"),
        ("The applicant built EconLens PH using React.", "first person"),
        ("EconLens PH uses React and Python.", "first person"),
        ("As an AI, I built EconLens PH.", "AI"),
        ("I built EconLens PH. Email me at juan@example.com.", "personal"),
        ("I built EconLens PH. Call me on 0917 123 4567.", "personal"),
    ],
)
def test_bad_replies_are_rejected(fake_ai: FakeAI, text: str, why: str) -> None:
    fake_ai.answer(text)
    result = draft_answer(None, box())  # type: ignore[arg-type]
    assert not result.ok and result.text == "", why
    assert result.note


def test_numbers_and_names_that_are_in_the_facts_are_fine(fake_ai: FakeAI) -> None:
    fake_ai.answer("I built EconLens PH with React and Python. Today 4 charts are live.")
    assert draft_answer(None, box()).ok  # type: ignore[arg-type]


def test_capital_letter_at_sentence_start_is_not_an_invented_name(fake_ai: FakeAI) -> None:
    fake_ai.answer("Honestly, I built EconLens PH. Dashboards are my favourite thing to build with React.")
    assert draft_answer(None, box()).ok  # type: ignore[arg-type]


def test_answer_longer_than_the_box_is_rejected(fake_ai: FakeAI) -> None:
    fake_ai.answer(GOOD)
    assert not draft_answer(None, box(max_length=40)).ok  # type: ignore[arg-type]


def test_source_must_be_one_of_the_facts_given(fake_ai: FakeAI) -> None:
    fake_ai.answer(GOOD, source="project:Something Else")
    result = draft_answer(None, box())  # type: ignore[arg-type]
    assert not result.ok and "source" in result.note


@pytest.mark.parametrize("problem", [ai.AIError("no valid answer"), NotImplementedError("gemini")])
def test_ai_failure_gives_a_rejected_result_not_a_crash(fake_ai: FakeAI, problem: Exception) -> None:
    fake_ai.reply = problem
    result = draft_answer(None, box())  # type: ignore[arg-type]
    assert not result.ok and "AI" in result.note


def test_no_facts_means_no_ai_call(fake_ai: FakeAI, facts: list[rag.Hit]) -> None:
    facts.clear()
    result = draft_answer(None, box())  # type: ignore[arg-type]
    assert not result.ok and fake_ai.prompts == []


# ---- refusals (defence in depth) ------------------------------------------------------------------


def test_drafting_refuses_sensitive_questions(fake_ai: FakeAI) -> None:
    with pytest.raises(DraftError):
        draft_answer(None, box("Are you legally authorized to work here?"))  # type: ignore[arg-type]
    assert fake_ai.prompts == []


@pytest.mark.parametrize("kind", ["fixed", "protected"])
def test_rewrite_refuses_fixed_and_protected(fake_ai: FakeAI, kind: str) -> None:
    with pytest.raises(DraftError):
        rewrite_open(None, box(), "No", kind)  # type: ignore[arg-type]
    assert fake_ai.prompts == []


def test_rewrite_refuses_sensitive_questions(fake_ai: FakeAI) -> None:
    with pytest.raises(DraftError):
        rewrite_open(None, box("Do you have a disability?"), "No", "open")  # type: ignore[arg-type]


# ---- rewrite ------------------------------------------------------------------------------------------


def test_rewrite_puts_the_saved_answer_in_the_prompt_and_allows_its_numbers(fake_ai: FakeAI) -> None:
    fake_ai.answer("I learn fast, and I shipped 3 apps because I finish what I start.", field=HOBBY, source="saved answer")
    result = rewrite_open(None, box(HOBBY), "I learn fast and I shipped 3 apps.", "open")  # type: ignore[arg-type]
    assert result.ok and "I learn fast and I shipped 3 apps." in fake_ai.prompts[0]


# ---- how answers.py uses it --------------------------------------------------------------------------------


def test_new_question_gets_a_flagged_draft(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rag, "match_saved_question", lambda *a, **k: rag.SavedMatch(None, False, (), rag.MATCH_THRESHOLD))
    fake_ai.answer(GOOD)
    result = answer_field(conn, box(), {})
    assert (result.value, result.source, result.flagged) == (GOOD, "draft", True)
    assert "EconLens PH" in result.note and result.unknown_id is not None


def test_rejected_draft_leaves_the_field_empty_and_flagged(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rag, "match_saved_question", lambda *a, **k: rag.SavedMatch(None, False, (), rag.MATCH_THRESHOLD))
    fake_ai.answer("I built a rocket with Kubernetes.")
    result = answer_field(conn, box(), {})
    assert result.value == "" and result.flagged and result.source == "none" and "rejected" in result.note


def test_new_dropdown_question_is_not_drafted(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rag, "match_saved_question", lambda *a, **k: rag.SavedMatch(None, False, (), rag.MATCH_THRESHOLD))
    result = answer_field(conn, box("How did you hear about us?", "dropdown", options=["Friend", "Ad"]), {})
    assert result.value == "" and result.flagged and fake_ai.prompts == []


def _match(monkeypatch: pytest.MonkeyPatch, ref: str, score: float = 0.95) -> None:
    hit = rag.Hit(1, "answer", ref, ref, score)
    monkeypatch.setattr(rag, "match_saved_question", lambda *a, **k: rag.SavedMatch(hit, True, ("open",), rag.MATCH_THRESHOLD))


def test_matched_open_answer_is_rewritten_and_flagged(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    _match(monkeypatch, "Tell us about your strengths")
    fake_ai.answer("I learn fast and I finish what I start, as my EconLens PH dashboard shows.", field=HOBBY, source="saved answer")
    result = answer_field(conn, box(HOBBY), {})
    assert result.source == "bank" and result.kind == "open" and result.flagged
    assert result.value.startswith("I learn fast") and "rewritten" in result.note


def test_failed_rewrite_falls_back_to_the_saved_text(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    _match(monkeypatch, "Tell us about your strengths")
    fake_ai.reply = ai.AIError("down")
    result = answer_field(conn, box(HOBBY), {})
    assert result.value == "I learn fast and finish what I start." and result.flagged and "saved text" in result.note


def test_open_answer_to_a_sensitive_question_is_never_sent_to_the_ai(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    _match(monkeypatch, "Tell us about your strengths")
    result = answer_field(conn, box("Do you have a disability?"), {})
    assert result.value == "I learn fast and finish what I start." and fake_ai.prompts == []


@pytest.mark.parametrize(("ref", "label"), [("When can you start?", "When can you start?"), ("Will you need visa sponsorship?", "Do you need a visa?")])
def test_fixed_and_protected_matches_still_never_reach_the_ai(
    conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch, ref: str, label: str
) -> None:
    _match(monkeypatch, ref)
    answer_field(conn, box(label), {})
    assert fake_ai.prompts == []
    assert learning.open_unknowns(conn) == []
