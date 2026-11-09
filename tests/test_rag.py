"""Tests for engine/rag.py. Fake data, an in-memory database and mock vectors only:
no Ollama, no network, none of your real files.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator

import pytest

from engine import ai, rag
from engine.db import connect, init_db
from engine.settings import Settings

MOCK = Settings(run_mode="mock")
FAKE_PHONE = "+63 900 123 4567"
FAKE_EMAIL = "fake.person@example.com"
FAKE_ADDRESS = "12 Imaginary Street, Faketown"
PROTECTED_ANSWER = "No, I have never been convicted of anything"

RESUME_TEXT = f"""Fake Person
{FAKE_EMAIL} | {FAKE_PHONE} | {FAKE_ADDRESS}
ID 123456789
EXPERIENCE
Built a mobile app with Kotlin and Jetpack Compose for a campus club.
SKILLS
Java, Kotlin, SQL, Git and unit testing with JUnit.
"""


@pytest.fixture(autouse=True)
def no_real_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any test that forgets to use mock vectors fails loudly instead of reaching Ollama."""

    def boom(model: str, texts: list[str]) -> list[list[float]]:
        raise AssertionError("A test tried to call the real Ollama embeddings")

    monkeypatch.setattr(ai, "_call_ollama_embed", boom)


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    init_db(connection)
    connection.execute(
        "INSERT INTO profile (id, full_name, email, phone, address, gpa, summary, skills, projects, school, degree,"
        " year_level, grad_year) VALUES (1, 'Fake Person', ?, ?, ?, '3.99', 'Student who likes building Android apps',"
        " ?, ?, 'Fake University', 'BS Computer Science', '3rd year', 2027)",
        (
            FAKE_EMAIL,
            FAKE_PHONE,
            FAKE_ADDRESS,
            json.dumps(["Java", "Kotlin"]),
            json.dumps([{"name": "PetTracker", "tech": ["Kotlin", "Room"], "blurb": "Android app to track pet vaccines"}]),
        ),
    )
    connection.execute("INSERT INTO resumes (id, label, file_path, extracted_text) VALUES ('A', 'x', 'a.pdf', ?)", (RESUME_TEXT,))
    for question, answer, scope, city, kind in [
        ("What is your expected monthly salary?", "PHP 20,000", "city", "Makati", "fixed"),
        ("What is your expected monthly salary?", "USD 600", "remote", "", "fixed"),
        ("Have you ever been convicted of a crime?", PROTECTED_ANSWER, "any", "", "protected"),
        ("When can you start?", "Immediately", "any", "", "fixed"),
    ]:
        connection.execute(
            "INSERT INTO answers (question, answer, location_scope, city, kind) VALUES (?, ?, ?, ?, ?)",
            (question, answer, scope, city, kind),
        )
    connection.commit()
    yield connection
    connection.close()


def all_chunk_text(conn: sqlite3.Connection) -> str:
    return "\n".join(r["text"] for r in conn.execute("SELECT text FROM chunks"))


# ---- chunking and privacy ---------------------------------------------------------


def test_scrub_removes_email_phone_ids_and_private_values() -> None:
    cleaned = rag.scrub(f"{FAKE_EMAIL} {FAKE_PHONE} 123456789 lives at {FAKE_ADDRESS}", [FAKE_ADDRESS])
    for secret in (FAKE_EMAIL, "900 123 4567", "123456789", "Imaginary Street"):
        assert secret not in cleaned
    assert "lives at" in cleaned


def test_scrub_keeps_normal_numbers() -> None:
    assert "2027" in rag.scrub("Graduating 2027 with 3.9 average")


def test_split_resume_follows_sections_and_never_exceeds_limit() -> None:
    text = "EXPERIENCE\n" + "Built something useful for a club. " * 40 + "\nSKILLS\nJava, Kotlin, SQL, Git and testing."
    chunks = rag.split_resume(text, max_chars=300)
    assert len(chunks) >= 3
    assert any(c.startswith("SKILLS") for c in chunks)
    assert all(len(c) <= 300 for c in chunks)
    assert chunks[0].startswith("EXPERIENCE Built")  # a heading stays with its content


def test_split_resume_drops_tiny_pieces() -> None:
    assert rag.split_resume("1\n\n2\n") == []


def test_no_chunk_contains_private_data(conn: sqlite3.Connection) -> None:
    rag.reindex(conn, MOCK)
    text = all_chunk_text(conn)
    for secret in (FAKE_EMAIL, "900 123 4567", "123456789", "Imaginary Street", "3.99"):
        assert secret not in text


def test_no_chunk_contains_any_saved_answer(conn: sqlite3.Connection) -> None:
    """Only questions are embedded, so even a protected answer can never reach a prompt."""
    rag.reindex(conn, MOCK)
    text = all_chunk_text(conn)
    for answer in ("PHP 20,000", "USD 600", PROTECTED_ANSWER, "Immediately"):
        assert answer not in text


def test_answer_variants_share_one_chunk(conn: sqlite3.Connection) -> None:
    counts = rag.reindex(conn, MOCK)
    assert counts["answer"] == 3  # 4 saved rows, 3 distinct questions
    assert counts["project"] == 1
    assert counts["resume"] >= 1
    assert counts["profile"] >= 3


# ---- indexing and retrieval ----------------------------------------------------------


def test_retrieve_finds_the_matching_saved_question(conn: sqlite3.Connection) -> None:
    rag.reindex(conn, MOCK)
    hits = rag.retrieve(conn, "expected monthly salary", 5, sources=("answer",), settings=MOCK)
    assert hits[0].ref == "What is your expected monthly salary?"
    assert hits == sorted(hits, key=lambda h: -h.score)


def test_retrieve_respects_k_and_source_filter(conn: sqlite3.Connection) -> None:
    rag.reindex(conn, MOCK)
    assert len(rag.retrieve(conn, "Android app", 2, settings=MOCK)) == 2
    facts = rag.retrieve(conn, "Android app", 5, sources=("project", "resume", "profile"), settings=MOCK)
    assert facts and all(h.source != "answer" for h in facts)
    assert facts[0].source == "project"


def test_reindex_twice_does_not_duplicate(conn: sqlite3.Connection) -> None:
    first = rag.reindex(conn, MOCK)
    second = rag.reindex(conn, MOCK)
    assert first == second
    assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == sum(first.values())
    assert conn.execute("SELECT count(*) FROM chunks_vec").fetchone()[0] == sum(first.values())


def test_retrieve_before_reindex_says_what_to_do(conn: sqlite3.Connection) -> None:
    with pytest.raises(rag.RagError, match="rag reindex"):
        rag.retrieve(conn, "anything", settings=MOCK)


def test_retrieve_rejects_empty_question_and_bad_k(conn: sqlite3.Connection) -> None:
    rag.reindex(conn, MOCK)
    with pytest.raises(rag.RagError):
        rag.retrieve(conn, "   ", settings=MOCK)
    with pytest.raises(rag.RagError):
        rag.retrieve(conn, "ok", 0, settings=MOCK)


def test_index_built_with_mock_cannot_be_searched_with_real_embedder(conn: sqlite3.Connection) -> None:
    rag.reindex(conn, MOCK)
    with pytest.raises(rag.RagError, match="rag reindex"):
        rag.retrieve(conn, "salary", settings=Settings(run_mode="dry_run", ai_provider="ollama"))


def test_failed_embedding_keeps_the_old_index(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    before = rag.reindex(conn, MOCK)

    def down(texts: list[str], *, settings: Settings | None = None) -> list[list[float]]:
        raise ai.AIError("server down")

    monkeypatch.setattr(ai, "embed", down)
    with pytest.raises(ai.AIError):
        rag.reindex(conn, MOCK)
    assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == sum(before.values())


def test_wrong_vector_size_is_rejected(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai, "embed", lambda texts, *, settings=None: [[1.0, 0.0] for _ in texts])
    with pytest.raises(rag.RagError, match="768"):
        rag.reindex(conn, MOCK)


def test_real_ollama_path_sends_prefixed_text_in_batches(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    """With a real-looking embedder the model sees document/query prefixes and batches of at most 32."""
    sizes: list[int] = []
    seen: list[str] = []

    def fake(model: str, texts: list[str]) -> list[list[float]]:
        sizes.append(len(texts))
        seen.extend(texts)
        return [ai._mock_vector(t) for t in texts]

    monkeypatch.setattr(ai, "_call_ollama_embed", fake)
    real = Settings(run_mode="dry_run", ai_provider="ollama")
    rag.reindex(conn, real)
    rag.retrieve(conn, "When can you start?", 3, settings=real)
    assert max(sizes) <= 32
    assert all(t.startswith(("search_document: ", "search_query: ")) for t in seen)
    assert seen[-1] == "search_query: When can you start?"
    for secret in (FAKE_EMAIL, "900 123 4567", PROTECTED_ANSWER):
        assert not any(secret in t for t in seen)
