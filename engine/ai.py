"""ask_ai(): the ONLY place in JobPilot that talks to an AI model.

Every feature calls ``ask_ai(task, prompt)`` and gets back a plain ``dict``.
Features never know (or care) whether the answer came from a canned file
(mock), a local Ollama model, or, later, Gemini. That keeps the rest of the
code easy to test and keeps all provider logic in one file.

Which provider answers (from settings.json):
    run_mode == "mock"  OR  ai_provider == "mock"  -> fixtures/ai/<task>.json
    ai_provider == "ollama"                         -> local model via Ollama
    ai_provider == "gemini"                         -> not built yet (v3)

Every answer, from any provider, is checked against a Pydantic model for that
task. Local models follow JSON instructions less reliably than big ones, so a
bad answer gets exactly ONE retry, then an AIError (callers log it and skip).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from engine.settings import ROOT, Settings, load_settings

logger = logging.getLogger(__name__)

FIXTURES_DIR = ROOT / "fixtures" / "ai"

# Rule 4 (no invented facts) is repeated to the model on every call.
_SYSTEM_PROMPT = (
    "You are a careful assistant. Reply with a single valid JSON object and "
    "nothing else. Use ONLY the information given in the user message. "
    "If something is not provided, do not guess or invent it."
)


# ---- one Pydantic model per task (shapes come from SPEC.md) -----------------


class MatchResult(BaseModel):
    """Task ``match``: score a job against the profile and pick a resume."""

    score: int = Field(ge=0, le=100)
    reasons: list[str]
    missing_skills: list[str]
    resume: Literal["A", "B"]
    resume_reason: str = ""


class EmailDraft(BaseModel):
    """Task ``email``: a cold-email draft plus the facts it used (so you can verify them)."""

    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
    facts_used: list[str]


# The task whitelist. A task not listed here is rejected, which also means a
# task name can never be used to read an arbitrary file (e.g. "../secrets").
# The ``form_answer`` and ``resume_pick`` tasks are added in v0 Phase 0/3 (form filler);
# ``match`` and ``email`` are used from v1 and v2.
TASK_MODELS: dict[str, type[BaseModel]] = {
    "match": MatchResult,
    "email": EmailDraft,
}


class AIError(Exception):
    """Raised when no usable answer could be produced.

    Callers should catch this per job, log it, and skip that job
    (one bad job must never stop the whole run).
    """


def ask_ai(
    task: str,
    prompt: str,
    *,
    settings: Settings | None = None,
    mock_response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ask the configured AI for a JSON answer and return it as a validated dict.

    Args:
        task: What we are asking, e.g. ``"match"``. Must be a key of
            ``TASK_MODELS``. In mock mode it also picks ``fixtures/ai/<task>.json``.
        prompt: The text to send. Callers must keep personal data (phone,
            address, email, ID numbers) OUT of it. This function does not
            filter it for you. Ignored in mock mode.
        settings: Override settings (used by tests). Defaults to settings.json.
        mock_response: Mock mode only. Lets a test choose the answer, e.g. a
            low score to check that a job gets skipped. Still validated.

    Returns:
        The answer as a dict, guaranteed to match the task's Pydantic model.

    Raises:
        AIError: unknown task, missing/invalid fixture, or the model never
            returned a valid answer (after one retry).
        NotImplementedError: the Gemini provider is selected (not built yet).
    """
    model_cls = TASK_MODELS.get(task)
    if model_cls is None:
        raise AIError(f"Unknown task: {task!r} (known: {sorted(TASK_MODELS)})")

    settings = settings or load_settings()

    if settings.run_mode == "mock" or settings.ai_provider == "mock":
        raw = mock_response if mock_response is not None else _load_fixture(task)
        try:
            return _validate(raw, model_cls)
        except ValueError as exc:
            raise AIError(f"Mock answer for task {task!r} is invalid: {type(exc).__name__}") from exc
    if settings.ai_provider == "ollama":
        return _ask_ollama(task, prompt, settings.ollama_model, model_cls)
    raise NotImplementedError(f"AI provider {settings.ai_provider!r} is not built yet")


def _validate(raw: Any, model_cls: type[BaseModel]) -> dict[str, Any]:
    """Check ``raw`` against the task's model; return a clean dict.

    Raises ``ValueError`` (pydantic's ValidationError is a subclass) if the
    shape or values are wrong, e.g. a score of 150 or resume "C".
    """
    return model_cls.model_validate(raw).model_dump()


def _load_fixture(task: str) -> Any:
    """Read the canned JSON for ``task`` from ``fixtures/ai/``."""
    path = FIXTURES_DIR / f"{task}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise AIError(f"No mock fixture for task {task!r} at {path}") from exc
    except ValueError as exc:
        raise AIError(f"Mock fixture for task {task!r} is not valid JSON") from exc


def _ask_ollama(task: str, prompt: str, model: str, model_cls: type[BaseModel]) -> dict[str, Any]:
    """Call Ollama; if the reply is not valid JSON of the right shape, retry ONCE, then give up."""
    last_problem = "no attempt made"
    for attempt in (1, 2):
        try:
            text = _call_ollama(model, prompt)
        except Exception as exc:  # server down, model missing, timeout...
            raise AIError(f"Ollama call failed: {exc}") from exc
        try:
            return _validate(json.loads(text), model_cls)
        except ValueError as exc:  # bad JSON or wrong shape
            last_problem = type(exc).__name__
            # Never log the prompt or reply: they may contain personal text.
            logger.warning("ask_ai(%s): attempt %d gave an invalid answer (%s)", task, attempt, last_problem)
    raise AIError(f"Ollama gave no valid answer for task {task!r} after one retry ({last_problem})")


def _call_ollama(model: str, prompt: str) -> str:
    """Send one chat request to the local Ollama server and return the raw text.

    ``format="json"`` makes Ollama constrain its output to valid JSON.
    Kept as its own tiny function so tests can replace it (tests must never
    reach a real model).
    """
    import ollama  # imported here so mock mode works even if Ollama isn't installed

    response = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        format="json",
    )
    return response["message"]["content"]
