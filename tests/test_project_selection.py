"""Tests for choosing the best projects for a question, calling them by a short name, and dropping stock phrases.

Every project detail is its own search piece, so a question finds the project with the best matching MOMENT.
The AI and the search are faked. Fake data and an in-memory database only.
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
        if sources == ("profile",):
            return [rag.Hit(900, "profile", "skills", "Skills: java, react, mysql, spring boot, supabase.", 0.5)]
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
        self.prompts: list[str] = []

    def __call__(self, task: str, prompt: str, **kwargs: object) -> dict:
        self.prompts.append(prompt)
        return self.reply

    def answer(self, text: str, confidence: float = 0.8) -> None:
        self.reply = {"answer": text, "confidence": confidence}


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
    fake_ai.answer(
        "On CheatNoNo, Exam Integrity Platform I shipped without rate limits and the dashboard froze, so I added batching. "
        "MJ Cinema, Movie Booking System taught me to expect two people booking one seat."
    )
    result = reflect_answer(conn, box())
    assert result.ok, result.note
    assert "CheatNoNo, Exam" not in result.text and "Exam Integrity Platform" not in result.text
    assert "Movie Booking System" not in result.text and "MJ Cinema taught me" in result.text


def test_the_notes_in_the_prompt_use_the_short_name_and_say_what_was_built_with(conn: sqlite3.Connection, fake_ai: FakeAI) -> None:
    fake_ai.answer("CheatNoNo froze at 60 students, so I added batching.")
    reflect_answer(conn, box())
    prompt = fake_ai.prompts[0]
    assert "Project: CheatNoNo. Built with: React, Supabase." in prompt
    assert "Exam Integrity Platform" not in prompt
    assert "A mistake and the fix: I shipped without rate limits" in prompt  # the new details are in the notes


def test_a_tool_from_your_tech_list_may_be_named_but_another_may_not(conn: sqlite3.Connection, fake_ai: FakeAI) -> None:
    fake_ai.answer("CheatNoNo taught me a lot about Supabase, because I had two weeks.")
    assert reflect_answer(conn, box()).ok
    fake_ai.answer("CheatNoNo taught me a lot about Redis.")
    assert not reflect_answer(conn, box()).ok


def test_a_list_of_your_technologies_warns_using_your_profile(conn: sqlite3.Connection, fake_ai: FakeAI) -> None:
    fake_ai.answer("On CheatNoNo I used Java, React and MySQL, and I added batching when it froze at 60 students.")
    result = reflect_answer(conn, box())
    assert result.ok and "a list of technologies" in result.note  # the terms come from your skills and project tech


def test_stock_phrases_warn_and_stay(conn: sqlite3.Connection, fake_ai: FakeAI) -> None:
    text = "CheatNoNo froze at 60 students because I shipped without rate limits. I'm excited to make a positive impact."
    fake_ai.answer(text)
    result = reflect_answer(conn, box())
    assert result.ok and result.text == text and "stock phrases" in result.note


def test_a_tiny_box_still_works_with_short_names(conn: sqlite3.Connection, fake_ai: FakeAI) -> None:
    fake_ai.answer("I learn from mistakes like the one on CheatNoNo. What I do now is test limits.")
    result = reflect_answer(conn, box(type="text", max_length=300))
    assert result.ok, result.note


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
