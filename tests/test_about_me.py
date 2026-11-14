"""Tests for the richer profile data: project detail fields and the ``about_me`` section.

These are YOUR OWN words (why you built things, how you work, your goals). They are optional: an
empty field changes nothing. Fake data and an in-memory database only.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from engine import rag
from engine.db import connect, init_db
from engine.profile import AboutMe, Project, load_profile

PROFILE = {
    "first_name": "Juan",
    "last_name": "Dela Cruz",
    "email": "juan.fake@example.com",
    "phone": "+63 900 123 4567",
    "summary": "A student developer.",
    "projects": [
        {
            "name": "Fake App",
            "problem": "Nobody could see the queue.",
            "hardest_part": "Keeping the screens in sync.",
            "why_i_built_it": "I waited in that queue every week.",
            "my_part": "I led a team of 3 and wrote the backend.",
            "key_decision": "I chose polling over websockets because it was simpler to debug.",
            "what_i_learned": "Simple beats clever when you have a deadline.",
            "would_change": "I would add tests before adding features.",
            "proud_of": "It was used by the whole class.",
        }
    ],
    "about_me": {
        "why_software_engineering": "I like that a small idea can help many people. Reach me at juan.fake@example.com.",
        "how_i_choose_what_to_build": "I start from a problem I have lived with.",
        "how_i_work": "I break a big problem into the smallest piece I can ship.",
        "working_with_others": "I explain my reasoning and ask for review early.",
        "strengths": [{"name": "Finishing", "evidence": "I shipped Fake App before the deadline."}],
        "growth_area": "Writing tests first.",
        "goals": {"next_year": "Do an internship.", "five_years": "Lead a small team.", "kind_of_work": "Products people use daily."},
        "values": "Honest work and clear communication.",
        "voice_notes": "Direct and plain. No buzzwords.",
    },
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


# ---- the shapes --------------------------------------------------------------------------------------


def test_new_project_fields_are_optional_and_default_empty() -> None:
    project = Project(name="Fake App")
    for name in ("why_i_built_it", "my_part", "key_decision", "what_i_learned", "would_change", "proud_of"):
        assert getattr(project, name) == "", name


def test_about_me_is_optional_and_empty_by_default() -> None:
    about = AboutMe()
    assert about.strengths == [] and about.goals.five_years == "" and about.voice_notes == ""


# ---- loading and storing ------------------------------------------------------------------------------


def test_load_profile_keeps_the_new_project_fields(conn: sqlite3.Connection) -> None:
    project = json.loads(conn.execute("SELECT projects FROM profile").fetchone()[0])[0]
    assert project["why_i_built_it"] == "I waited in that queue every week."
    assert project["key_decision"].startswith("I chose polling")


def test_load_profile_stores_about_me(conn: sqlite3.Connection) -> None:
    about = json.loads(conn.execute("SELECT about_me FROM profile").fetchone()[0])
    assert about["goals"]["five_years"] == "Lead a small team."
    assert about["strengths"][0]["name"] == "Finishing"
    assert about["voice_notes"] == "Direct and plain. No buzzwords."


def test_a_profile_without_about_me_still_loads(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"first_name": "Juan", "last_name": "Dela Cruz"}), encoding="utf-8")
    connection = connect(":memory:")
    init_db(connection)
    load_profile(connection, path, tmp_path)
    assert json.loads(connection.execute("SELECT about_me FROM profile").fetchone()[0])["strengths"] == []


def test_init_db_adds_the_about_me_column_to_an_older_database() -> None:
    old = connect(":memory:")
    old.execute("CREATE TABLE profile (id INTEGER PRIMARY KEY, full_name TEXT NOT NULL)")  # an old shape, no about_me
    init_db(old)
    assert "about_me" in {row["name"] for row in old.execute("PRAGMA table_info(profile)")}


# ---- the search index ----------------------------------------------------------------------------------


def test_about_me_becomes_profile_chunks_and_private_text_is_removed(conn: sqlite3.Connection) -> None:
    chunks = {c.ref: c for c in rag.build_chunks(conn) if c.source == "profile"}
    assert "about:why_software_engineering" in chunks
    assert "about:strength:Finishing" in chunks and "I shipped Fake App" in chunks["about:strength:Finishing"].text
    assert "about:goals" in chunks and "Lead a small team." in chunks["about:goals"].text
    assert "juan.fake@example.com" not in chunks["about:why_software_engineering"].text  # scrubbed (rule 3)
    assert not any("voice" in ref for ref in chunks)  # voice notes are an instruction, not a fact to search


def test_empty_about_me_entries_make_no_chunks(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"first_name": "Juan", "last_name": "Dela Cruz", "about_me": {"values": "Honest work."}}), encoding="utf-8")
    connection = connect(":memory:")
    init_db(connection)
    load_profile(connection, path, tmp_path)
    refs = [c.ref for c in rag.build_chunks(connection) if c.ref.startswith("about:")]
    assert refs == ["about:values"]


def test_project_story_chunk_includes_the_new_fields(conn: sqlite3.Connection) -> None:
    story = next(c for c in rag.build_chunks(conn) if c.ref == "Fake App (story)")
    assert "Why I built it: I waited in that queue every week." in story.text
    assert "What I learned: Simple beats clever" in story.text


def test_the_index_version_changed_so_an_old_index_is_rebuilt() -> None:
    assert rag.INDEX_VERSION >= 3


def test_blank_strength_slots_from_the_template_load_and_make_no_chunks(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps({"first_name": "Juan", "last_name": "Dela Cruz",
                    "about_me": {"strengths": [{"name": "", "evidence": ""}, {"name": "Finishing", "evidence": "Shipped on time."}]}}),
        encoding="utf-8",
    )
    connection = connect(":memory:")
    init_db(connection)
    load_profile(connection, path, tmp_path)  # must not raise
    refs = [c.ref for c in rag.build_chunks(connection) if c.ref.startswith("about:")]
    assert refs == ["about:strength:Finishing"]
