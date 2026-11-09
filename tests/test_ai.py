"""Tests for ask_ai() and settings. They never touch a real model or the network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from engine import ai
from engine.ai import TASK_MODELS, AIError, ask_ai
from engine.settings import Settings, load_settings

MOCK = Settings(run_mode="mock")
DRY_RUN_OLLAMA = Settings(run_mode="dry_run", ai_provider="ollama")

GOOD_MATCH: dict[str, Any] = {
    "score": 70,
    "reasons": ["uses React"],
    "missing_skills": [],
    "resume": "B",
    "resume_reason": "mobile",
}


@pytest.fixture(autouse=True)
def no_real_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    """Safety net: any test that forgets to fake Ollama fails loudly."""

    def boom(model: str, prompt: str) -> str:
        raise AssertionError("A test tried to call the real Ollama")

    monkeypatch.setattr(ai, "_call_ollama", boom)

    def boom_embed(model: str, texts: list[str]) -> list[list[float]]:
        raise AssertionError("A test tried to call the real Ollama embeddings")

    monkeypatch.setattr(ai, "_call_ollama_embed", boom_embed)


def fake_ollama(monkeypatch: pytest.MonkeyPatch, *replies: str) -> list[str]:
    """Make Ollama return ``replies`` in order; returns a list of the prompts it received."""
    seen: list[str] = []
    queue = iter(replies)

    def fake(model: str, prompt: str) -> str:
        seen.append(prompt)
        return next(queue)

    monkeypatch.setattr(ai, "_call_ollama", fake)
    return seen


# ---- mock mode -------------------------------------------------------------


def test_mock_match_returns_the_canned_answer() -> None:
    result = ask_ai("match", "ignored in mock mode", settings=MOCK)
    assert result["score"] == 78
    assert result["resume"] == "A"


@pytest.mark.parametrize("task", sorted(TASK_MODELS))
def test_every_task_has_a_valid_fixture(task: str) -> None:
    """Adding a task to TASK_MODELS without a fixture (or a broken one) fails here."""
    assert isinstance(ask_ai(task, "x", settings=MOCK), dict)


def test_a_test_can_choose_the_mock_answer() -> None:
    """Spec: 'Tests can also choose the answer, e.g. a low score.'"""
    low = {**GOOD_MATCH, "score": 12}
    assert ask_ai("match", "x", settings=MOCK, mock_response=low)["score"] == 12


def test_invalid_mock_answer_is_rejected() -> None:
    with pytest.raises(AIError):
        ask_ai("match", "x", settings=MOCK, mock_response={**GOOD_MATCH, "score": 150})


def test_ai_provider_mock_wins_even_in_dry_run() -> None:
    settings = Settings(run_mode="dry_run", ai_provider="mock")
    assert ask_ai("match", "x", settings=settings)["score"] == 78  # autouse fixture proves no Ollama call


@pytest.mark.parametrize("bad", ["../secrets", "Match", "a/b", "", "form", "nope"])
def test_unknown_task_names_are_rejected(bad: str) -> None:
    with pytest.raises(AIError):
        ask_ai(bad, "x", settings=MOCK)


# ---- validation (Pydantic) -------------------------------------------------


@pytest.mark.parametrize(
    "broken",
    [
        {**GOOD_MATCH, "score": 101},
        {**GOOD_MATCH, "score": -1},
        {**GOOD_MATCH, "resume": "C"},
        {k: v for k, v in GOOD_MATCH.items() if k != "reasons"},
    ],
)
def test_match_shape_is_enforced(broken: dict[str, Any]) -> None:
    with pytest.raises(AIError):
        ask_ai("match", "x", settings=MOCK, mock_response=broken)


def test_email_needs_a_subject_and_body() -> None:
    with pytest.raises(AIError):
        ask_ai("email", "x", settings=MOCK, mock_response={"subject": "", "body": "hi", "facts_used": []})


# ---- ollama provider (faked) ----------------------------------------------


def test_ollama_returns_validated_json(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ollama(monkeypatch, json.dumps(GOOD_MATCH))
    assert ask_ai("match", "p", settings=DRY_RUN_OLLAMA) == GOOD_MATCH


def test_ollama_retries_once_after_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ollama(monkeypatch, "not json", json.dumps(GOOD_MATCH))
    assert ask_ai("match", "p", settings=DRY_RUN_OLLAMA)["score"] == 70


def test_ollama_retries_once_after_wrong_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ollama(monkeypatch, json.dumps({**GOOD_MATCH, "score": 850}), json.dumps(GOOD_MATCH))
    assert ask_ai("match", "p", settings=DRY_RUN_OLLAMA)["score"] == 70


def test_ollama_gives_up_after_one_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = fake_ollama(monkeypatch, "bad", "still bad")
    with pytest.raises(AIError):
        ask_ai("match", "p", settings=DRY_RUN_OLLAMA)
    assert len(seen) == 2  # first try + exactly one retry, no more


def test_ollama_non_object_json_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ollama(monkeypatch, "[1, 2, 3]", "[1, 2, 3]")
    with pytest.raises(AIError):
        ask_ai("match", "p", settings=DRY_RUN_OLLAMA)


def test_ollama_server_error_becomes_ai_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(model: str, prompt: str) -> str:
        raise ConnectionError("server not running")

    monkeypatch.setattr(ai, "_call_ollama", down)
    with pytest.raises(AIError):
        ask_ai("match", "p", settings=DRY_RUN_OLLAMA)


def test_prompt_and_reply_are_never_logged(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    fake_ollama(monkeypatch, "SECRET-REPLY", json.dumps(GOOD_MATCH))
    with caplog.at_level("WARNING"):
        ask_ai("match", "SECRET-PROMPT", settings=DRY_RUN_OLLAMA)
    assert "SECRET" not in caplog.text


def test_gemini_is_not_built_yet() -> None:
    with pytest.raises(NotImplementedError):
        ask_ai("match", "p", settings=Settings(run_mode="dry_run", ai_provider="gemini"))


# ---- settings --------------------------------------------------------------


def test_missing_settings_file_defaults_to_mock(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "nope.json").run_mode == "mock"


def test_garbage_settings_fall_back_to_safe_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"run_mode": "yolo", "ai_provider": 5}), encoding="utf-8")
    loaded = load_settings(path)
    assert loaded.run_mode == "mock"
    assert loaded.ai_provider == "ollama"


def test_mock_is_an_accepted_ai_provider(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"run_mode": "dry_run", "ai_provider": "mock"}), encoding="utf-8")
    assert load_settings(path).ai_provider == "mock"


def test_committed_settings_file_is_mock_mode() -> None:
    """The committed settings.json must stay in the safe mode (CLAUDE.md: default = mock)."""
    assert load_settings().run_mode == "mock"


# ---- v0 form-filler tasks ---------------------------------------------------


def test_mock_form_answer_returns_validated_answers() -> None:
    result = ask_ai("form_answer", "ignored", settings=MOCK)
    assert result["answers"][0]["field"]
    assert 0.0 <= result["answers"][0]["confidence"] <= 1.0


def test_mock_resume_pick_returns_a_or_b() -> None:
    assert ask_ai("resume_pick", "ignored", settings=MOCK)["resume"] in ("A", "B")


def test_a_test_can_choose_the_resume() -> None:
    chosen = {"resume": "B", "reason": "post asks for X", "evidence": ["resume B project uses X"]}
    assert ask_ai("resume_pick", "x", settings=MOCK, mock_response=chosen)["resume"] == "B"


@pytest.mark.parametrize(
    ("task", "bad"),
    [
        ("resume_pick", {"resume": "C", "reason": "nope", "evidence": ["e"]}),
        ("resume_pick", {"resume": "A", "reason": "", "evidence": ["e"]}),
        ("resume_pick", {"resume": "A", "reason": "r", "evidence": []}),
        ("resume_pick", {"resume": "A", "reason": "r"}),
        ("form_answer", {"answers": [{"field": "q", "answer": "a", "confidence": 1.5, "source": "s"}]}),
        ("form_answer", {"answers": [{"field": "", "answer": "a", "confidence": 0.5, "source": "s"}]}),
        ("form_answer", [{"field": "q"}]),
    ],
)
def test_invalid_form_task_answers_raise_aierror(task: str, bad: Any) -> None:
    with pytest.raises(AIError):
        ask_ai(task, "x", settings=MOCK, mock_response=bad)


def test_ollama_form_answer_retries_once_on_bad_json(monkeypatch: pytest.MonkeyPatch) -> None:
    good = json.dumps({"answers": [{"field": "q", "answer": "a", "confidence": 0.9, "source": "s"}]})
    seen = fake_ollama(monkeypatch, "not json", good)
    result = ask_ai("form_answer", "prompt", settings=DRY_RUN_OLLAMA)
    assert result["answers"][0]["answer"] == "a"
    assert len(seen) == 2


# ---- embeddings ------------------------------------------------------------


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # vectors are already unit length


def test_embed_mock_is_deterministic_and_right_size() -> None:
    first = ai.embed(["expected monthly salary"], settings=MOCK)
    second = ai.embed(["expected monthly salary"], settings=MOCK)
    assert first == second
    assert len(first) == 1 and len(first[0]) == ai.EMBED_DIM


def test_embed_mock_similar_texts_score_higher() -> None:
    query, close, far = ai.embed(
        ["expected monthly salary", "what is your expected monthly salary", "favourite programming language"],
        settings=MOCK,
    )
    assert _cosine(query, close) > _cosine(query, far)


def test_embed_empty_list_and_empty_text() -> None:
    assert ai.embed([], settings=MOCK) == []
    assert len(ai.embed([""], settings=MOCK)[0]) == ai.EMBED_DIM


def test_embed_ollama_returns_vectors_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, list[str]]] = []

    def fake(model: str, texts: list[str]) -> list[list[float]]:
        seen.append((model, texts))
        return [[1, 0.5], [0, 1]]

    monkeypatch.setattr(ai, "_call_ollama_embed", fake)
    result = ai.embed(["a", "b"], settings=DRY_RUN_OLLAMA)
    assert result == [[1.0, 0.5], [0.0, 1.0]]
    assert seen == [("nomic-embed-text", ["a", "b"])]


@pytest.mark.parametrize(
    "bad",
    [[[1.0]], [[1.0], [1.0, 2.0]], [[], []], [["x"], ["y"]], "nope"],
)
def test_embed_ollama_bad_reply_raises(monkeypatch: pytest.MonkeyPatch, bad: Any) -> None:
    monkeypatch.setattr(ai, "_call_ollama_embed", lambda model, texts: bad)
    with pytest.raises(AIError):
        ai.embed(["a", "b"], settings=DRY_RUN_OLLAMA)


def test_embed_ollama_failure_becomes_aierror(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(model: str, texts: list[str]) -> list[list[float]]:
        raise ConnectionError("server down")

    monkeypatch.setattr(ai, "_call_ollama_embed", down)
    with pytest.raises(AIError):
        ai.embed(["a"], settings=DRY_RUN_OLLAMA)


def test_embed_gemini_not_built() -> None:
    with pytest.raises(NotImplementedError):
        ai.embed(["a"], settings=Settings(run_mode="dry_run", ai_provider="gemini"))
