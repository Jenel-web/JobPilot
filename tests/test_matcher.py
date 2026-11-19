"""Resume picker tests (mock mode: no Ollama, no network)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest

from engine import ai, matcher, rag
from engine.cli import main
from engine.db import connect, init_db
from engine.settings import Settings

MOCK = Settings(run_mode="mock")
POST = "Junior Java developer. You will build Android apps with Kotlin and write unit tests."
TEXT_A = "EXPERIENCE\nBuilt an Android app with Kotlin for a campus club.\nSKILLS\nJava, Kotlin, JUnit."
TEXT_B = "EXPERIENCE\nBuilt a React and Spring Boot exam platform.\nSKILLS\nReact, TypeScript, PostgreSQL."


def make_db(label_a: str, file_a: str, label_b: str, file_b: str) -> sqlite3.Connection:
    conn = connect(":memory:")
    init_db(conn)
    conn.execute("INSERT INTO resumes (id, label, file_path, extracted_text) VALUES ('A', ?, ?, ?)", (label_a, file_a, TEXT_A))
    conn.execute("INSERT INTO resumes (id, label, file_path, extracted_text) VALUES ('B', ?, ?, ?)", (label_b, file_b, TEXT_B))
    conn.commit()
    rag.reindex(conn, MOCK)
    return conn


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = make_db("backend", "backend.pdf", "frontend", "frontend.pdf")
    yield connection
    connection.close()


class Recorder:
    """Remembers each prompt, then lets the real mock ``ask_ai`` answer."""

    def __init__(self, real: Any) -> None:
        self.real = real
        self.calls: list[tuple[str, str]] = []

    def __call__(self, task: str, prompt: str, **kwargs: Any) -> dict:
        self.calls.append((task, prompt))
        return self.real(task, prompt, **kwargs)


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    rec = Recorder(ai.ask_ai)
    monkeypatch.setattr(ai, "ask_ai", rec)
    return rec


def test_pick_returns_a_or_b_with_evidence(conn: sqlite3.Connection, recorder: Recorder) -> None:
    pick = matcher.pick_resume(conn, POST, settings=MOCK)
    assert pick is not None
    assert pick.resume in ("A", "B")
    assert pick.evidence and pick.reason
    assert [task for task, _ in recorder.calls] == ["resume_pick"]


def test_prompt_holds_the_post_and_chunks_of_both_resumes(conn: sqlite3.Connection, recorder: Recorder) -> None:
    matcher.pick_resume(conn, POST, settings=MOCK)
    prompt = recorder.calls[0][1]
    assert "Android apps" in prompt and "Resume A:" in prompt and "Resume B:" in prompt
    assert "Kotlin" in prompt and "React" in prompt


@pytest.mark.parametrize("text", ["", "   \n\t "])
def test_empty_post_does_no_pick_and_no_ai_call(conn: sqlite3.Connection, recorder: Recorder, text: str) -> None:
    assert matcher.pick_resume(conn, text, settings=MOCK) is None
    assert recorder.calls == []


def test_swapping_file_names_and_labels_changes_nothing(recorder: Recorder) -> None:
    first = make_db("backend", "backend.pdf", "frontend", "frontend.pdf")
    second = make_db("frontend", "frontend.pdf", "backend", "backend.pdf")  # names swapped, contents the same
    pick_1 = matcher.pick_resume(first, POST, settings=MOCK)
    pick_2 = matcher.pick_resume(second, POST, settings=MOCK)
    assert pick_1 == pick_2
    assert recorder.calls[0][1] == recorder.calls[1][1]
    for name in ("backend", "frontend", ".pdf"):
        assert name not in recorder.calls[0][1].replace("backend developer", "")


def test_post_contact_details_are_scrubbed(conn: sqlite3.Connection, recorder: Recorder) -> None:
    matcher.pick_resume(conn, POST + " Apply: hr@example.com or call 0917 123 4567.", settings=MOCK)
    assert "hr@example.com" not in recorder.calls[0][1]
    assert "123 4567" not in recorder.calls[0][1]


def test_missing_resume_raises_a_clear_error(recorder: Recorder) -> None:
    empty = connect(":memory:")
    init_db(empty)
    with pytest.raises(matcher.PickError):
        matcher.pick_resume(empty, POST, settings=MOCK)
    assert recorder.calls == []


def test_bad_ai_answer_becomes_a_pick_error(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(task: str, prompt: str, **kwargs: Any) -> dict:
        raise ai.AIError("no valid answer")

    monkeypatch.setattr(ai, "ask_ai", broken)
    with pytest.raises(matcher.PickError):
        matcher.pick_resume(conn, POST, settings=MOCK)


def test_cli_prints_the_pick(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    post = tmp_path / "post.txt"
    post.write_text(POST, encoding="utf-8")
    connection = make_db("x", "a.pdf", "y", "b.pdf")
    monkeypatch.setattr("engine.cli.connect", lambda *a, **k: connection)
    monkeypatch.setattr(rag, "load_settings", lambda: MOCK)  # the CLI passes no settings: force mock mode
    monkeypatch.setattr(ai, "load_settings", lambda: MOCK)
    assert main(["resume", "pick", "--post", str(post)]) == 0
    out = capsys.readouterr().out
    assert "Pick: resume" in out and "Evidence:" in out
