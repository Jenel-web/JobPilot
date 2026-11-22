"""Tests for engine/api_write.py: the endpoints that change things (stage 4.4d).

Everything runs against a temporary database and a temporary answers.json, in mock mode, with no network.
Your real data/answers.json is never touched.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine import api, db, learning, rag
from engine.forms.filler import FieldResult, FillReport
from engine.forms.history import save_fill
from engine.profile import load_answers
from engine.settings import Settings

MOCK = Settings(run_mode="mock")
SALARY = "What is your expected monthly salary?"
CRIME = "Have you ever been convicted of a crime?"
START = "When can you start?"


@dataclass
class Env:
    client: TestClient
    conn: sqlite3.Connection
    answers: Path

    def file(self) -> list[dict]:
        return json.loads(self.answers.read_text(encoding="utf-8"))

    def backups(self) -> list[Path]:
        return sorted(self.answers.parent.glob("answers.backup-*"))

    def answer_id(self, question: str, scope: str = "any") -> int:
        return self.conn.execute("SELECT id FROM answers WHERE question = ? AND location_scope = ?", (question, scope)).fetchone()["id"]


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps(
            [
                {"question": SALARY, "answer": "PHP 20,000", "kind": "fixed", "also_asked_as": ["Expected salary"]},
                {"question": CRIME, "answer": "No", "kind": "protected", "also_asked_as": ["Any record?"]},
                {"question": START, "answer": "Immediately", "kind": "open"},
            ]
        ),
        encoding="utf-8",
    )
    path = tmp_path / "test.db"
    app = api.create_app(MOCK, db_path=path, answers_path=answers)
    conn = db.connect(path)
    load_answers(conn, answers)
    yield Env(TestClient(app, base_url="http://127.0.0.1:8000"), conn, answers)
    conn.close()


def new_unknown(env: Env, text: str = "Do you have a driving licence?") -> int:
    return learning.record_unknown(env.conn, text, "https://x.test/a", "radio")


def new_wording(env: Env, wording: str, matched: str, score: float = 0.9) -> int:
    wording_id = learning.suggest_wording(env.conn, wording, matched, score, "https://x.test/b")
    assert wording_id
    return wording_id


# ---- POST /unknown/{id}/answer ------------------------------------------------------------------------------


def test_answering_an_unknown_question_saves_it_everywhere(env: Env) -> None:
    uid = new_unknown(env)
    before = env.answers.read_text(encoding="utf-8")
    response = env.client.post(f"/unknown/{uid}/answer", json={"answer": "Yes", "kind": "fixed"})
    assert response.status_code == 200
    body = response.json()
    assert body["reindexed"] is True and body["warning"] is None
    assert Path(body["backup"]).read_text(encoding="utf-8") == before  # the backup is the file as it was
    assert body["answer"]["question"] == "Do you have a driving licence?" and body["answer"]["answer"] == "Yes"
    assert env.file()[-1]["question"] == "Do you have a driving licence?"
    assert env.client.get("/unknown").json() == []
    assert [a["answer"] for a in env.client.get("/answers").json() if a["question"].startswith("Do you have")] == ["Yes"]


def test_the_file_is_written_before_the_index_is_rebuilt(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_reindex(conn: sqlite3.Connection, settings: Settings | None = None) -> dict:
        seen["in_file_at_reindex"] = any(e["question"].startswith("Do you have") for e in env.file())
        seen["backups_at_reindex"] = len(env.backups())
        return {}

    monkeypatch.setattr(rag, "reindex", fake_reindex)
    uid = new_unknown(env)
    assert env.client.post(f"/unknown/{uid}/answer", json={"answer": "Yes", "kind": "fixed"}).status_code == 200
    assert seen == {"in_file_at_reindex": True, "backups_at_reindex": 1}  # backup, then write, then re-index


def test_a_failed_reindex_keeps_the_answer_and_warns(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_a: object, **_k: object) -> dict:
        raise rag.RagError("Ollama is off")

    monkeypatch.setattr(rag, "reindex", broken)
    uid = new_unknown(env)
    response = env.client.post(f"/unknown/{uid}/answer", json={"answer": "Yes", "kind": "fixed"})
    assert response.status_code == 200
    assert response.json()["reindexed"] is False and "Ollama is off" in response.json()["warning"]
    assert env.file()[-1]["answer"] == "Yes"  # not undone


@pytest.mark.parametrize(
    "body",
    [
        {"answer": "Yes"},  # kind is required: no default
        {"answer": "Yes", "kind": "secret"},
        {"answer": "", "kind": "fixed"},
        {"answer": "Yes", "kind": "fixed", "scope": "mars"},
        {"answer": "Yes", "kind": "fixed", "scope": "city"},  # city scope needs a city
    ],
)
def test_a_bad_answer_is_refused_and_nothing_changes(env: Env, body: dict) -> None:
    uid = new_unknown(env)
    before = env.answers.read_text(encoding="utf-8")
    assert env.client.post(f"/unknown/{uid}/answer", json=body).status_code == 422
    assert env.answers.read_text(encoding="utf-8") == before and env.backups() == []
    assert len(env.client.get("/unknown").json()) == 1  # still waiting


def test_unknown_answer_errors(env: Env) -> None:
    uid = new_unknown(env)
    ok = {"answer": "Yes", "kind": "fixed"}
    assert env.client.post("/unknown/999/answer", json=ok).status_code == 404
    assert env.client.post(f"/unknown/{uid}/answer", json=ok).status_code == 200
    again = env.client.post(f"/unknown/{uid}/answer", json=ok)
    assert again.status_code == 409 and again.json()["code"] == "already_decided"


def test_answering_never_overwrites_a_saved_answer(env: Env) -> None:
    """An unknown question with the same words as a PROTECTED saved answer must not replace it."""
    uid = new_unknown(env, CRIME)
    before = env.answers.read_text(encoding="utf-8")
    response = env.client.post(f"/unknown/{uid}/answer", json={"answer": "Yes", "kind": "open"})
    assert response.status_code == 409 and response.json()["code"] == "already_decided"
    assert env.answers.read_text(encoding="utf-8") == before


# ---- POST /wordings/{id}/approve and /reject ------------------------------------------------------------------


def test_approving_a_protected_wording_without_confirmation_is_refused(env: Env) -> None:
    wid = new_wording(env, "Any criminal convictions?", CRIME)
    before = env.answers.read_text(encoding="utf-8")
    for body in (None, {}, {"confirm_protected": False}):
        response = env.client.post(f"/wordings/{wid}/approve", json=body)
        assert response.status_code == 409 and response.json()["code"] == "protected_needs_confirmation"
    assert env.answers.read_text(encoding="utf-8") == before and env.backups() == []  # nothing changed, no backup
    assert [w["id"] for w in env.client.get("/wordings").json()] == [wid]  # still pending


def test_approving_a_protected_wording_with_confirmation_works(env: Env) -> None:
    wid = new_wording(env, "Any criminal convictions?", CRIME)
    before = env.answers.read_text(encoding="utf-8")
    response = env.client.post(f"/wordings/{wid}/approve", json={"confirm_protected": True})
    assert response.status_code == 200 and response.json()["status"] == "approved" and response.json()["reindexed"] is True
    assert Path(response.json()["backup"]).read_text(encoding="utf-8") == before
    assert "Any criminal convictions?" in next(e for e in env.file() if e["question"] == CRIME)["also_asked_as"]
    assert env.client.get("/wordings").json() == []
    again = env.client.post(f"/wordings/{wid}/approve", json={"confirm_protected": True})
    assert again.status_code == 409 and again.json()["code"] == "already_decided"


def test_an_unprotected_wording_needs_no_confirmation_and_no_body(env: Env) -> None:
    wid = new_wording(env, "How much pay do you want?", SALARY)
    assert env.client.post(f"/wordings/{wid}/approve").status_code == 200
    assert "How much pay do you want?" in next(e for e in env.file() if e["question"] == SALARY)["also_asked_as"]


def test_approve_errors(env: Env) -> None:
    assert env.client.post("/wordings/999/approve").status_code == 404
    wid = new_wording(env, "Pay?", SALARY)
    env.answers.write_text("[]", encoding="utf-8")  # the saved question vanished from the file
    response = env.client.post(f"/wordings/{wid}/approve")
    assert response.status_code == 409 and response.json()["code"] == "cannot_apply"


def test_rejecting_marks_it_and_never_touches_the_file(env: Env) -> None:
    wid = new_wording(env, "How much pay do you want?", SALARY)
    before = env.answers.read_text(encoding="utf-8")
    response = env.client.post(f"/wordings/{wid}/reject")
    assert response.status_code == 200 and response.json()["status"] == "rejected"
    assert env.answers.read_text(encoding="utf-8") == before and env.backups() == []
    assert learning.suggest_wording(env.conn, "How much pay do you want?", SALARY, 0.9) is None  # it never comes back
    assert env.client.post(f"/wordings/{wid}/reject").status_code == 409
    assert env.client.post("/wordings/999/reject").status_code == 404


# ---- answers CRUD ---------------------------------------------------------------------------------------------


def test_create_answer(env: Env) -> None:
    body = {"question": "Do you drive?", "answer": "Yes", "kind": "fixed"}
    response = env.client.post("/answers", json=body)
    assert response.status_code == 201 and response.json()["answer"]["answer"] == "Yes" and response.json()["reindexed"] is True
    assert env.file()[-1] == {"question": "Do you drive?", "answer": "Yes", "kind": "fixed"} and len(env.backups()) == 1
    duplicate = env.client.post("/answers", json={**body, "answer": "No"})
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "already_exists"
    assert env.file()[-1]["answer"] == "Yes"
    city = env.client.post("/answers", json={**body, "scope": "city", "city": "Makati"})  # a different scope is a different answer
    assert city.status_code == 201 and city.json()["answer"]["city"] == "Makati"


def test_create_cannot_overwrite_a_protected_answer(env: Env) -> None:
    before = env.answers.read_text(encoding="utf-8")
    response = env.client.post("/answers", json={"question": CRIME, "answer": "Yes", "kind": "open"})
    assert response.status_code == 409 and env.answers.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("bad", [{"kind": "secret"}, {"scope": "mars"}, {"scope": "city"}, {"answer": ""}, {"question": ""}])
def test_create_validates(env: Env, bad: dict) -> None:
    response = env.client.post("/answers", json={"question": "Q?", "answer": "A", "kind": "fixed", **bad})
    assert response.status_code == 422 and env.backups() == []


def test_update_keeps_the_id_the_usage_and_the_wordings(env: Env) -> None:
    aid = env.answer_id(SALARY)
    env.conn.execute("UPDATE answers SET times_used = 7 WHERE id = ?", (aid,))
    env.conn.commit()
    body = {"answer": "PHP 25,000", "kind": "fixed", "scope": "city", "city": "Makati"}
    response = env.client.put(f"/answers/{aid}", json=body)
    assert response.status_code == 200
    out = response.json()["answer"]
    assert out["id"] == aid and out["times_used"] == 7 and out["location_scope"] == "city" and out["city"] == "Makati"
    assert out["also_asked_as"] == ["Expected salary"]
    entry = next(e for e in env.file() if e["question"] == SALARY)
    assert entry["answer"] == "PHP 25,000" and entry["location_scope"] == "city" and entry["also_asked_as"] == ["Expected salary"]
    assert len(env.client.get("/answers").json()) == 3  # edited in place, not duplicated


def test_update_a_protected_answer_needs_confirmation(env: Env) -> None:
    aid = env.answer_id(CRIME)
    before = env.answers.read_text(encoding="utf-8")
    body = {"answer": "Yes", "kind": "protected", "scope": "any"}
    refused = env.client.put(f"/answers/{aid}", json=body)
    assert refused.status_code == 409 and refused.json()["code"] == "protected_needs_confirmation"
    assert env.answers.read_text(encoding="utf-8") == before and env.backups() == []
    assert env.client.put(f"/answers/{aid}", json={**body, "confirm_protected": True}).status_code == 200
    assert next(e for e in env.file() if e["question"] == CRIME)["answer"] == "Yes"


def test_demoting_a_protected_answer_also_needs_confirmation(env: Env) -> None:
    """Changing kind away from protected is the risky direction: it must not slip through."""
    aid = env.answer_id(CRIME)
    refused = env.client.put(f"/answers/{aid}", json={"answer": "No", "kind": "open", "scope": "any"})
    assert refused.status_code == 409 and env.file()[1]["kind"] == "protected"


def test_update_errors(env: Env) -> None:
    body = {"answer": "x", "kind": "fixed", "scope": "any"}
    assert env.client.put("/answers/999", json=body).status_code == 404
    assert env.client.put(f"/answers/{env.answer_id(START)}", json={"answer": "x", "kind": "fixed"}).status_code == 422  # scope is required
    env.client.post("/answers", json={"question": START, "answer": "Later", "kind": "open", "scope": "remote"})
    collide = env.client.put(f"/answers/{env.answer_id(START, 'remote')}", json={**body, "scope": "any"})
    assert collide.status_code == 409 and collide.json()["code"] == "already_exists"


def test_delete_removes_it_from_file_database_and_wordings(env: Env) -> None:
    aid = env.answer_id(SALARY)
    response = env.client.delete(f"/answers/{aid}")
    assert response.status_code == 200
    out = response.json()
    assert out["deleted_id"] == aid and out["question"] == SALARY and out["removed_wordings"] == 1 and out["backup"]
    assert all(e["question"] != SALARY for e in env.file())
    assert all(a["question"] != SALARY for a in env.client.get("/answers").json())
    assert env.conn.execute("SELECT COUNT(*) FROM answer_aliases WHERE question = ?", (SALARY,)).fetchone()[0] == 0
    assert env.client.delete(f"/answers/{aid}").status_code == 404


def test_delete_a_protected_answer_needs_confirmation(env: Env) -> None:
    aid = env.answer_id(CRIME)
    before = env.answers.read_text(encoding="utf-8")
    refused = env.client.delete(f"/answers/{aid}")
    assert refused.status_code == 409 and refused.json()["code"] == "protected_needs_confirmation"
    assert env.answers.read_text(encoding="utf-8") == before and env.backups() == []
    assert env.client.delete(f"/answers/{aid}?confirm_protected=true").status_code == 200
    assert all(e["question"] != CRIME for e in env.file())


def test_deleting_an_answer_that_an_unknown_question_points_at(env: Env) -> None:
    uid = new_unknown(env)
    out = env.client.post(f"/unknown/{uid}/answer", json={"answer": "Yes", "kind": "fixed"}).json()
    assert env.client.delete(f"/answers/{out['answer']['id']}").status_code == 200  # the foreign key does not block it
    assert env.conn.execute("SELECT answer_id FROM unknown_questions WHERE id = ?", (uid,)).fetchone()["answer_id"] is None


def test_every_change_to_the_file_makes_a_backup_first(env: Env) -> None:
    env.client.post("/answers", json={"question": "Q1?", "answer": "A", "kind": "fixed"})
    env.client.put(f"/answers/{env.answer_id('Q1?')}", json={"answer": "B", "kind": "fixed", "scope": "any"})
    env.client.delete(f"/answers/{env.answer_id('Q1?')}")
    assert len(env.backups()) == 3  # even within one second: no backup overwrites another


# ---- POST /fills/{id}/status ------------------------------------------------------------------------------------


def make_fill(env: Env) -> int:
    report = FillReport(url="https://jobs.test/a", results=[FieldResult("Full name", "text", "filled")])
    return save_fill(env.conn, report, job_title="Analyst")


def test_mark_a_fill_submitted_then_it_cannot_change(env: Env) -> None:
    fid = make_fill(env)
    response = env.client.post(f"/fills/{fid}/status", json={"status": "submitted"})
    assert response.status_code == 200 and response.json()["status"] == "submitted" and response.json()["submitted_at"]
    again = env.client.post(f"/fills/{fid}/status", json={"status": "abandoned"})
    assert again.status_code == 409 and again.json()["code"] == "not_allowed"


def test_mark_a_fill_abandoned(env: Env) -> None:
    fid = make_fill(env)
    response = env.client.post(f"/fills/{fid}/status", json={"status": "abandoned"})
    assert response.json()["status"] == "abandoned" and response.json()["submitted_at"] is None


@pytest.mark.parametrize("status", ["filled", "done", ""])
def test_a_fill_can_only_be_marked_submitted_or_abandoned(env: Env, status: str) -> None:
    assert env.client.post(f"/fills/{make_fill(env)}/status", json={"status": status}).status_code == 422


def test_marking_an_unknown_fill_is_404(env: Env) -> None:
    assert env.client.post("/fills/999/status", json={"status": "submitted"}).status_code == 404


# ---- the guards cover every change --------------------------------------------------------------------------------

CHANGES = [
    ("post", "/unknown/1/answer", {"answer": "Yes", "kind": "fixed"}),
    ("post", "/wordings/1/approve", {"confirm_protected": True}),
    ("post", "/wordings/1/reject", None),
    ("post", "/answers", {"question": "Q?", "answer": "A", "kind": "fixed"}),
    ("put", "/answers/1", {"answer": "A", "kind": "fixed", "scope": "any", "confirm_protected": True}),
    ("delete", "/answers/1?confirm_protected=true", None),
    ("post", "/fills/1/status", {"status": "submitted"}),
]


@pytest.mark.parametrize(("method", "url", "body"), CHANGES)
def test_a_change_from_another_website_is_refused_and_changes_nothing(env: Env, method: str, url: str, body: dict | None) -> None:
    new_wording(env, "How much pay do you want?", SALARY)
    new_unknown(env)
    make_fill(env)
    before = env.answers.read_text(encoding="utf-8")
    response = env.client.request(method, url, json=body, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert env.answers.read_text(encoding="utf-8") == before and env.backups() == []
    assert len(env.client.get("/wordings").json()) == 1 and len(env.client.get("/unknown").json()) == 1


@pytest.mark.parametrize(("method", "url", "body"), CHANGES)
def test_a_change_with_a_foreign_host_is_refused(env: Env, method: str, url: str, body: dict | None) -> None:
    foreign = TestClient(env.client.app, base_url="http://evil.example")
    assert foreign.request(method, url, json=body).status_code == 403


def test_the_write_code_never_clicks_and_never_changes_the_mode() -> None:
    from engine import api_write

    source = Path(api_write.__file__).read_text(encoding="utf-8")
    for forbidden in (".click(", "playwright", "load_settings", "SETTINGS_PATH"):
        assert forbidden not in source, forbidden


def test_changes_are_serialised_by_the_write_lock(env: Env) -> None:
    """While one change holds the lock, a second one waits instead of both reading the same old file."""
    import threading

    lock: threading.Lock = env.client.app.state.write_lock  # type: ignore[attr-defined]
    results: list[int] = []
    lock.acquire()
    try:
        worker = threading.Thread(
            target=lambda: results.append(env.client.post("/answers", json={"question": "Q?", "answer": "A", "kind": "fixed"}).status_code)
        )
        worker.start()
        worker.join(timeout=0.5)
        assert worker.is_alive() and results == []  # waiting for the lock
    finally:
        lock.release()
    worker.join(timeout=10)
    assert results == [201]
