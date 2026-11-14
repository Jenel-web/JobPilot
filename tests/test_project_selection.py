"""Tests for choosing the best projects for a question, calling them by a short name, and dropping stock phrases.

Every project detail is its own search piece, so a question finds the project with the best matching MOMENT.
The AI and the search are faked. Fake data and an in-memory database only.
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
from engine.forms.drafting import FIELDS_PER_PROJECT, reflect_answer
from engine.forms.reader import FormField
from engine.profile import Project, load_profile, project_short_name

QUESTION = "Tell me about a time you made a mistake and how you fixed it."

PROFILE = {
    "first_name": "Juan",
    "last_name": "Dela Cruz",
    "skills": ["Java", "React", "MySQL", "Spring Boot"],
    "projects": [
        {
            "name": "CheatNoNo, Exam Integrity Platform",
            "tech": ["React", "Supabase"],
            "problem": "Students cheated on online exams.",
            "why_i_built_it": "I watched classmates share answers.",
            "my_part": "I wrote the extension and the dashboard.",
            "key_decision": "I used Supabase because I had two weeks.",
            "hardest_part": "Keeping the live feed in sync.",
            "how_i_got_through_it": "I replayed events in order.",
            "mistake_and_fix": "I shipped without rate limits and the dashboard froze at 60 students. I added batching.",
            "what_i_learned": "Decide the data flow on paper first.",
            "would_change": "Write tests for the rules first.",
            "proud_of": "Review time dropped to 20 seconds.",
            "teamwork": "Professors gave feedback after the first exam.",
            "timeline": "Six weeks.",
        },
        {"name": "MJ Cinema, Movie Booking System", "problem": "I had never built a full-stack project.", "hardest_part": "Two people booking one seat."},
        {"name": "Pag-IBIG Housing Loan Online Application System", "problem": "Loan forms were confusing.", "hardest_part": "Validation."},
        {"name": "EconLens", "problem": "Economic data was hard to read.", "short_name": "Econ Lens"},
    ],
}


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(PROFILE), encoding="utf-8")
    connection = connect(":memory:")
    init_db(connection)
    load_profile(connection, path, tmp_path)
    yield connection
    connection.close()


def box(label: str = QUESTION, type: str = "textarea", **kw: object) -> FormField:
    return FormField(label=label, type=type, **kw)  # type: ignore[arg-type]


# ---- short names ----------------------------------------------------------------------------------------------


def test_the_short_name_is_the_part_before_the_comma() -> None:
    assert project_short_name("CheatNoNo, Exam Integrity Platform") == "CheatNoNo"
    assert project_short_name("MJ Cinema: Movie Booking System") == "MJ Cinema"


def test_a_long_name_without_a_comma_is_cut_to_three_words() -> None:
    assert project_short_name("Pag-IBIG Housing Loan Online Application System") == "Pag-IBIG Housing Loan"


def test_your_own_short_name_wins() -> None:
    assert project_short_name({"name": "EconLens", "short_name": "Econ Lens"}) == "Econ Lens"
    assert project_short_name({"name": "CheatNoNo, Exam Integrity Platform"}) == "CheatNoNo"


# ---- the four new fields load ---------------------------------------------------------------------------------


def test_the_new_project_fields_are_optional() -> None:
    project = Project(name="Fake")
    assert project.how_i_got_through_it == project.mistake_and_fix == project.teamwork == project.timeline == project.short_name == ""


def test_the_new_fields_are_saved_with_the_profile(conn: sqlite3.Connection) -> None:
    saved = json.loads(conn.execute("SELECT projects FROM profile").fetchone()[0])[0]
    assert saved["mistake_and_fix"].startswith("I shipped without rate limits")
    assert saved["teamwork"] == "Professors gave feedback after the first exam."


# ---- every detail is its own piece of the index -----------------------------------------------------------------


def test_each_filled_detail_becomes_one_chunk_called_by_the_short_name(conn: sqlite3.Connection) -> None:
    chunks = {c.ref: c for c in rag.build_chunks(conn) if rag.is_field_ref(c.ref)}
    mistake = chunks["CheatNoNo :: mistake_and_fix"]
    assert mistake.text.startswith("Project: CheatNoNo. A mistake and the fix: I shipped without rate limits")
    assert "Exam Integrity Platform" not in mistake.text
    assert "MJ Cinema :: problem" in chunks and "MJ Cinema :: mistake_and_fix" not in chunks  # empty details make no chunk
    assert "Econ Lens :: problem" in chunks  # your own short name is used


def test_the_index_is_rebuilt_for_the_per_detail_chunks() -> None:
    assert rag.INDEX_VERSION >= 4


def test_the_draft_path_never_sees_the_per_detail_pieces(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    hits = [rag.Hit(1, "project", "CheatNoNo :: problem", "x", 0.9), rag.Hit(2, "project", "CheatNoNo (story)", "y", 0.8)]
    monkeypatch.setattr(rag, "retrieve", lambda *a, **k: hits)
    assert [h.ref for h in drafting.gather_facts(conn, "anything")] == ["CheatNoNo (story)"]


# ---- choosing the best projects ---------------------------------------------------------------------------------


def _field_hits(scores: dict[tuple[str, str], float], words: dict[tuple[str, str], int] | None = None) -> list[rag.Hit]:
    """Fake detail hits. Every detail is 10 words long unless ``words`` says otherwise (length matters for richness)."""
    words = words or {}
    return [
        rag.Hit(n, "project", f"{short} :: {key}", "word " * words.get((short, key), 10), score)
        for n, ((short, key), score) in enumerate(scores.items())
    ]


def _patch_search(monkeypatch: pytest.MonkeyPatch, project_hits: list[rag.Hit]) -> None:
    def fake(conn: object, question: str, k: int = 5, *, sources: tuple[str, ...] | None = None, settings: object = None) -> list[rag.Hit]:
        if sources == ("project",):
            return sorted(project_hits, key=lambda h: -h.score)
        return []

    monkeypatch.setattr(rag, "retrieve", fake)


def test_the_project_with_the_best_matching_detail_is_chosen(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_search(monkeypatch, _field_hits({
        ("CheatNoNo", "mistake_and_fix"): 0.90,
        ("MJ Cinema", "problem"): 0.60, ("MJ Cinema", "hardest_part"): 0.58,
        ("Pag-IBIG Housing Loan", "problem"): 0.55,
        ("Econ Lens", "problem"): 0.40,
    }))
    refs = [h.ref for h in drafting.gather_reflective_facts(conn, QUESTION) if h.source == "project"]
    assert refs == ["CheatNoNo (story)", "MJ Cinema (story)"]


def test_a_second_good_detail_lifts_a_project_over_one_lucky_match(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_search(monkeypatch, _field_hits({
        ("MJ Cinema", "problem"): 0.70, ("MJ Cinema", "hardest_part"): 0.69,
        ("Pag-IBIG Housing Loan", "problem"): 0.72,
        ("CheatNoNo", "mistake_and_fix"): 0.50,
    }))
    refs = [h.ref for h in drafting.gather_reflective_facts(conn, QUESTION, count=1) if h.source == "project"]
    assert refs == ["MJ Cinema (story)"]  # 0.70 + 0.3 * 0.69 beats 0.72 + 0


def test_only_the_closest_details_are_sent_and_always_what_started_it(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    keys = ["mistake_and_fix", "how_i_got_through_it", "what_i_learned", "would_change", "key_decision", "teamwork", "proud_of", "timeline", "problem"]
    scores = {("CheatNoNo", key): 0.9 - 0.05 * n for n, key in enumerate(keys)}
    scores[("CheatNoNo", "problem")] = 0.01  # the worst match, but still included
    _patch_search(monkeypatch, _field_hits(scores))
    text = next(h.text for h in drafting.gather_reflective_facts(conn, QUESTION, count=1) if h.source == "project")
    assert "A mistake and the fix: I shipped without rate limits" in text
    assert "What started it: Students cheated on online exams." in text
    assert "Timeline" not in text and "Proud of" not in text  # the least relevant are left out
    shown = [label for _, label in rag.PROJECT_FIELDS if f"{label}:" in text]
    assert len(shown) == FIELDS_PER_PROJECT + 1  # the 6 closest, plus what started it


def test_facts_call_the_project_by_its_short_name(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_search(monkeypatch, _field_hits({("CheatNoNo", "mistake_and_fix"): 0.9}))
    fact = next(h for h in drafting.gather_reflective_facts(conn, QUESTION) if h.source == "project")
    assert fact.ref == "CheatNoNo (story)" and fact.text.startswith("Project: CheatNoNo.")
    assert "Exam Integrity Platform" not in fact.text


# ---- the answer ---------------------------------------------------------------------------------------------------


class FakeAI:
    def __init__(self) -> None:
        self.reply: dict = {}

    def __call__(self, task: str, prompt: str, **kwargs: object) -> dict:
        return self.reply

    def parts(self, stance: str, examples: list[str], closing: str) -> None:
        self.reply = {"pattern": "", "stance": stance, "examples": examples, "closing": closing, "confidence": 0.8}


@pytest.fixture
def fake_ai(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> FakeAI:
    fake = FakeAI()
    monkeypatch.setattr(ai, "ask_ai", fake)
    _patch_search(monkeypatch, _field_hits({
        ("CheatNoNo", "mistake_and_fix"): 0.9, ("CheatNoNo", "problem"): 0.7,
        ("MJ Cinema", "problem"): 0.6, ("MJ Cinema", "hardest_part"): 0.5,
    }))
    return fake


def test_a_full_name_written_by_the_model_becomes_the_short_name(conn: sqlite3.Connection, fake_ai: FakeAI) -> None:
    fake_ai.parts(
        "I learn the most from my mistakes.",
        ["On CheatNoNo, Exam Integrity Platform I shipped without rate limits and the dashboard froze, so I added batching.",
         "MJ Cinema, Movie Booking System taught me to expect two people booking one seat."],
        "What I do now is test the limit before I ship.",
    )
    result = reflect_answer(conn, box())
    assert result.ok, result.note
    assert "CheatNoNo, Exam" not in result.text and "Exam Integrity Platform" not in result.text
    assert "Movie Booking System" not in result.text and "MJ Cinema taught me" in result.text


def test_stock_sentences_are_dropped_and_the_real_ones_stay(conn: sqlite3.Connection, fake_ai: FakeAI) -> None:
    fake_ai.parts(
        "I learn the most from my mistakes.",
        ["CheatNoNo froze at 60 students because I shipped without rate limits.", "MJ Cinema showed me two people can book one seat."],
        "I fixed it with batching. I'm excited to keep building apps that make a positive impact on people's lives.",
    )
    result = reflect_answer(conn, box())
    assert result.ok, result.note
    assert "excited" not in result.text and "positive impact" not in result.text and "I fixed it with batching." in result.text


def test_a_list_of_technologies_is_dropped(conn: sqlite3.Connection, fake_ai: FakeAI) -> None:
    fake_ai.parts(
        "I learn the most from my mistakes.",
        ["CheatNoNo froze at 60 students because I shipped without rate limits.", "MJ Cinema showed me two people can book one seat."],
        "I used Java, React and MySQL to build it. What I do now is test the limit before I ship.",
    )
    result = reflect_answer(conn, box())
    assert result.ok, result.note
    assert "Java, React" not in result.text and "test the limit before I ship" in result.text


def test_this_project_started_with_becomes_it_started_with(conn: sqlite3.Connection, fake_ai: FakeAI) -> None:
    fake_ai.parts(
        "I learn the most from my mistakes.",
        ["CheatNoNo: This project started with students cheating on exams.", "MJ Cinema showed me two people can book one seat."],
        "What I do now is test the limit before I ship.",
    )
    result = reflect_answer(conn, box())
    assert result.ok and "this project started" not in result.text.lower() and "it started with students cheating" in result.text


def test_an_answer_of_only_stock_phrases_is_rejected_with_a_clear_reason(conn: sqlite3.Connection, fake_ai: FakeAI) -> None:
    fake_ai.parts(
        "I'm excited about technology.",
        ["CheatNoNo froze at 60 students.", "MJ Cinema showed me two people can book one seat."],
        "I'm excited to make a positive impact on people's lives.",
    )
    result = reflect_answer(conn, box())
    assert not result.ok and "stock phrases" in result.note
    assert len(re.split(r"(?<=[.!?])\s+", result.text)) <= 1


def test_the_prompt_asks_for_a_real_moment_and_no_stock_endings(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(ai, "ask_ai", lambda task, prompt, **k: (seen.append(prompt), fake_ai.reply)[1])
    fake_ai.parts("I learn from mistakes.", ["CheatNoNo froze at 60 students.", "MJ Cinema booked one seat twice."], "What I do now is test limits.")
    reflect_answer(conn, box())
    assert "ONE real moment" in seen[0] and "No stock endings" in seen[0]
    assert "A mistake and the fix" in seen[0]  # the facts carry the new details


def test_a_tiny_box_still_works_with_short_names(conn: sqlite3.Connection, fake_ai: FakeAI) -> None:
    # a 300-character box has room for 2 sentences and no examples, so the stance itself must name the project
    fake_ai.parts("I learn from mistakes like the one on CheatNoNo.", [], "What I do now is test limits.")
    result = reflect_answer(conn, box(type="text", max_length=300))
    assert result.ok, result.note


# ---- one retry when the closing is only stock phrases -------------------------------------------------------------


class SequenceAI:
    """Replies one after another, and remembers each prompt."""

    def __init__(self, *replies: dict) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def __call__(self, task: str, prompt: str, **kwargs: object) -> dict:
        self.prompts.append(prompt)
        return self.replies.pop(0)


def _reply(closing: str, stance: str = "I learn the most from my mistakes.") -> dict:
    return {"pattern": "", "stance": stance, "closing": closing, "confidence": 0.8,
            "examples": ["CheatNoNo froze at 60 students.", "MJ Cinema showed me two people can book one seat."]}


STOCK_CLOSING = "I'm excited to make a positive impact. Through these projects I showed my passion."


def test_a_stock_closing_gets_one_retry_for_the_closing_only(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    sequence = SequenceAI(_reply(STOCK_CLOSING), _reply("What I do now is test the limit before I ship."))
    monkeypatch.setattr(ai, "ask_ai", sequence)
    result = reflect_answer(conn, box())
    assert result.ok, result.note
    assert len(sequence.prompts) == 2 and "PREVIOUS REPLY WAS REJECTED" in sequence.prompts[1]
    assert result.text.endswith("What I do now is test the limit before I ship.") and "excited" not in result.text


def test_a_second_stock_closing_is_rejected_and_there_is_no_third_call(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    sequence = SequenceAI(_reply(STOCK_CLOSING), _reply("I'm thrilled to grow as a developer."))
    monkeypatch.setattr(ai, "ask_ai", sequence)
    result = reflect_answer(conn, box())
    assert not result.ok and "stock phrases" in result.note and len(sequence.prompts) == 2


def test_a_good_closing_makes_no_second_call(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    sequence = SequenceAI(_reply("What I do now is test the limit before I ship."))
    monkeypatch.setattr(ai, "ask_ai", sequence)
    assert reflect_answer(conn, box()).ok and len(sequence.prompts) == 1


def test_self_praise_endings_are_dropped_too(conn: sqlite3.Connection, fake_ai: FakeAI, monkeypatch: pytest.MonkeyPatch) -> None:
    closing = "I fixed it with batching. This shows I'm committed to delivering high-quality results."
    monkeypatch.setattr(ai, "ask_ai", SequenceAI(_reply(closing)))
    result = reflect_answer(conn, box())
    assert result.ok and "committed" not in result.text and "high-quality" not in result.text


# ---- a richer story beats a slightly closer one-liner ---------------------------------------------------------------


def test_among_close_matches_the_richer_detail_wins(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    # the real case: MJ Cinema's one-line mistake echoes the question (0.688); CheatNoNo's long story is 0.065 behind
    _patch_search(monkeypatch, _field_hits(
        {("MJ Cinema", "mistake_and_fix"): 0.688, ("CheatNoNo", "mistake_and_fix"): 0.623, ("Econ Lens", "mistake_and_fix"): 0.40},
        {("MJ Cinema", "mistake_and_fix"): 57, ("CheatNoNo", "mistake_and_fix"): 86, ("Econ Lens", "mistake_and_fix"): 90},
    ))
    refs = [h.ref for h in drafting.gather_reflective_facts(conn, QUESTION, count=1) if h.source == "project"]
    assert refs == ["CheatNoNo (story)"]  # Econ Lens is longer still, but far from the question, so it is not considered


def test_a_much_closer_match_is_not_beaten_by_a_longer_one(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    margin = drafting.RICHNESS_MARGIN
    _patch_search(monkeypatch, _field_hits(
        {("MJ Cinema", "mistake_and_fix"): 0.70, ("CheatNoNo", "mistake_and_fix"): 0.70 - margin - 0.01},
        {("MJ Cinema", "mistake_and_fix"): 20, ("CheatNoNo", "mistake_and_fix"): 200},
    ))
    refs = [h.ref for h in drafting.gather_reflective_facts(conn, QUESTION, count=1) if h.source == "project"]
    assert refs == ["MJ Cinema (story)"]


def test_equally_rich_close_matches_keep_the_similarity_order(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_search(monkeypatch, _field_hits({("MJ Cinema", "problem"): 0.70, ("CheatNoNo", "problem"): 0.68}))
    refs = [h.ref for h in drafting.gather_reflective_facts(conn, QUESTION, count=2) if h.source == "project"]
    assert refs == ["MJ Cinema (story)", "CheatNoNo (story)"]
