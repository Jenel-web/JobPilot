"""Tests for elaborating a short saved yes/no answer in a free-text box.

Fake data, an in-memory database, a faked AI and faked search. Nothing here touches Ollama or a browser.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from engine import ai, rag
from engine.db import connect, init_db
from engine.forms import answers, drafting
from engine.forms.reader import FormField
from engine.profile import load_answers

DOCKER = "Do you have experience with Docker? Please explain."
AUTH = "Are you legally authorized to work in the Philippines?"
GOOD = "Yes. I used Docker to containerise the EconLens backend."


class FakeAI:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.text = GOOD
        self.confidence = 0.9

    def __call__(self, task: str, prompt: str, **kw: object) -> dict:
        self.prompts.append(prompt)
        return {"answer": self.text, "confidence": self.confidence}


@pytest.fixture
def fake_ai(monkeypatch: pytest.MonkeyPatch) -> FakeAI:
    fake = FakeAI()
    monkeypatch.setattr(ai, "ask_ai", fake)
    return fake


@pytest.fixture
def notes(monkeypatch: pytest.MonkeyPatch) -> list[rag.Hit]:
    """The facts the search 'finds'. A test may replace the list contents."""
    hits = [rag.Hit(1, "project", "EconLens PH", "Project: EconLens PH. Built with Docker and Spring Boot.", 0.8)]

    def fake_retrieve(conn: object, q: str, k: int = 5, *, sources: object = None, settings: object = None) -> list[rag.Hit]:
        return list(hits)

    monkeypatch.setattr(rag, "retrieve", fake_retrieve)
    return hits


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    path = tmp_path / "answers.json"
    path.write_text(
        json.dumps(
            [
                {"question": DOCKER, "answer": "Yes", "kind": "fixed"},
                {"question": "Do you have experience with Kubernetes?", "answer": "Yes", "kind": "protected"},
                {"question": "How many years of Java?", "answer": "Yes, I have two years of Java", "kind": "fixed"},
                {"question": AUTH, "answer": "Yes", "kind": "fixed"},
            ]
        ),
        encoding="utf-8",
    )
    connection = connect(":memory:")
    init_db(connection)
    load_answers(connection, path)
    yield connection
    connection.close()


def match(monkeypatch: pytest.MonkeyPatch, ref: str) -> None:
    hit = rag.Hit(1, "answer", ref, ref, 0.99)
    result = rag.SavedMatch(hit, True, ("fixed",), rag.MATCH_THRESHOLD)
    monkeypatch.setattr(rag, "match_saved_question", lambda *a, **k: result)


def ask(conn: sqlite3.Connection, label: str, type: str = "textarea", **kw: object) -> answers.FieldAnswer:
    return answers.answer_field(conn, FormField(label=label, type=type, **kw), {})  # type: ignore[arg-type]


# ---- the rule -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("saved, expected", [("Yes", "yes"), ("No", "no"), ("yes.", "yes"), ("No, not yet", "no"), ("Yes, I do", "yes")])
def test_short_yes_no_is_recognised(saved: str, expected: str) -> None:
    assert drafting.short_yes_no(saved) == expected


@pytest.mark.parametrize("saved", ["", "Yes, I have two years of Java", "Maybe", "Yesterday", "2 weeks notice", "Nope"])
def test_anything_else_is_not_a_short_yes_no(saved: str) -> None:
    assert drafting.short_yes_no(saved) is None


# ---- the answers ----------------------------------------------------------------------------------------------


def test_yes_in_a_text_box_is_expanded_and_flagged(conn, monkeypatch, fake_ai, notes) -> None:
    match(monkeypatch, DOCKER)
    result = ask(conn, DOCKER)
    assert result.value == GOOD and result.flagged and result.source == "bank"
    assert "SAVED ANSWER: Yes" in fake_ai.prompts[0] and "Docker" in fake_ai.prompts[0]


@pytest.mark.parametrize("type", ["radio", "select", "checkbox"])
def test_yes_in_a_radio_or_dropdown_stays_plain(conn, monkeypatch, fake_ai, notes, type) -> None:
    match(monkeypatch, DOCKER)
    result = ask(conn, DOCKER, type, options=["Yes", "No"])
    assert result.value == "Yes" and not result.flagged
    assert fake_ai.prompts == []


def test_a_protected_yes_is_untouched(conn, monkeypatch, fake_ai, notes) -> None:
    match(monkeypatch, "Do you have experience with Kubernetes?")
    result = ask(conn, "Do you have experience with Kubernetes? Please explain.")
    assert result.value == "Yes" and fake_ai.prompts == []


def test_a_long_saved_answer_is_not_expanded(conn, monkeypatch, fake_ai, notes) -> None:
    match(monkeypatch, "How many years of Java?")
    result = ask(conn, "How many years of Java?")
    assert result.value == "Yes, I have two years of Java" and fake_ai.prompts == []


def test_a_sensitive_question_is_never_sent_to_the_ai(conn, monkeypatch, fake_ai, notes) -> None:
    match(monkeypatch, AUTH)
    result = ask(conn, AUTH)
    assert result.value == "Yes" and fake_ai.prompts == []
    with pytest.raises(drafting.DraftError):
        drafting.elaborate_short(conn, FormField(label=AUTH, type="textarea"), "Yes")


# ---- the guards (each one falls back to the plain saved answer, unflagged) -------------------------------------


@pytest.mark.parametrize(
    "reply, why",
    [
        ("No. I have never used Docker.", "start"),  # flips the stance
        ("Yes. I used Docker for 5 years.", "not in your notes"),  # invented number
        ("Yes. I used Docker and Terraform.", "not in your notes"),  # invented name
        ("Yes. Call me on 09171234567.", "phone"),  # private data
        ("Yes. As an AI language model I use Docker.", "assistant"),
        ("", "no answer"),
    ],
)
def test_a_bad_reply_falls_back_to_the_saved_answer(conn, monkeypatch, fake_ai, notes, reply, why) -> None:
    match(monkeypatch, DOCKER)
    fake_ai.text = reply
    result = ask(conn, DOCKER)
    assert result.value == "Yes" and not result.flagged and "not elaborated" in result.note


def test_no_close_notes_means_no_ai_call(conn, monkeypatch, fake_ai, notes) -> None:
    match(monkeypatch, DOCKER)
    notes[0] = rag.Hit(1, "project", "EconLens PH", "Project: EconLens PH.", 0.2)  # far below the cutoff
    result = ask(conn, DOCKER)
    assert result.value == "Yes" and fake_ai.prompts == [] and "no notes close enough" in result.note


def test_ai_unavailable_falls_back(conn, monkeypatch, notes) -> None:
    match(monkeypatch, DOCKER)

    def down(*a: object, **k: object) -> dict:
        raise ai.AIError("ollama is not running")

    monkeypatch.setattr(ai, "ask_ai", down)
    assert ask(conn, DOCKER).value == "Yes"


def test_the_prompt_has_no_private_data(conn, monkeypatch, fake_ai, notes) -> None:
    match(monkeypatch, DOCKER)
    ask(conn, DOCKER)
    prompt = fake_ai.prompts[0]
    assert rag.scrub(prompt) == prompt


def test_a_search_failure_falls_back_to_the_saved_answer(conn, monkeypatch, fake_ai) -> None:
    match(monkeypatch, DOCKER)

    def broken(*a: object, **k: object) -> list:
        raise rag.RagError("The index is empty.")

    monkeypatch.setattr(rag, "retrieve", broken)
    result = ask(conn, DOCKER)
    assert result.value == "Yes" and fake_ai.prompts == []


# ---- only experience and knowledge questions ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    ["Do you have experience with Docker? Please explain.", "Are you familiar with Agile or Scrum?", "Do you know Java?",
     "Have you ever used React?", "Do you have hands-on experience with SQL?"],
)
def test_experience_and_knowledge_questions_are_recognised(label: str) -> None:
    assert answers.is_experience_question(label)


@pytest.mark.parametrize(
    "label",
    ["Are you open to a hybrid setup?", "Do you have your own laptop?", "Are you available for part-time work?",
     "Are you comfortable working asynchronously?", "Were you referred by an employee?"],
)
def test_logistics_questions_are_not(label: str) -> None:
    assert not answers.is_experience_question(label)


def test_a_logistics_yes_in_a_text_box_stays_plain_even_with_close_notes(conn, monkeypatch, fake_ai, notes) -> None:
    match(monkeypatch, DOCKER)  # a saved "Yes", but the form asks a logistics question
    result = ask(conn, "Are you open to a hybrid setup?")
    assert result.value == "Yes" and not result.flagged and fake_ai.prompts == []


def test_the_notes_cutoff_is_0_65() -> None:
    assert drafting.ELABORATE_MIN_SCORE == 0.65
