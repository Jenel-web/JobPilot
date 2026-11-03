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
