"""Tests for engine/profile.py, secrets.py, safety.py and the CLI.

They use a FAKE profile, a tiny PDF made on the fly and an in-memory database.
They never read your real data/ files and never touch Windows Credential Manager.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from engine import safety, secrets
from engine.db import connect, init_db
from engine.profile import (
    ProfileError,
    extract_resume_text,
    load_answers,
    load_profile,
    lookup_answer,
    mask_email,
    mask_phone,
    profile_summary,
)
from engine.settings import Settings

FAKE_PHONE = "+63 900 123 4567"
FAKE_EMAIL = "fake.person@example.com"


def make_pdf(path: Path, text: str) -> None:
    """Write a minimal one-page PDF containing ``text`` (enough for pdfplumber to read)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


@pytest.fixture()
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    init_db(connection)
    yield connection
    connection.close()


@pytest.fixture()
def files(tmp_path: Path) -> tuple[Path, Path]:
    """A fake profile.json + resumes folder; returns (profile_path, resumes_dir)."""
    resumes = tmp_path / "resumes"
    resumes.mkdir()
    make_pdf(resumes / "first.pdf", "Java Spring Boot developer")
    make_pdf(resumes / "second.pdf", "Flutter Dart mobile developer")
    profile = {
        "name": "Fake Person",
        "email": FAKE_EMAIL,
        "phone": FAKE_PHONE,
        "address": "1 Fake Street",
        "education": {"school": "Fake University", "degree": "BS IT", "year_level": "3rd", "grad_year": 2028},
        "location": "Manila",
        "open_to_remote": True,
        "links": {"github": "https://github.com/fake"},
        "job_preferences": {"job_types": ["internship"]},
        "skills": ["java", "sql"],
        "projects": [{"name": "Fake App", "tech": ["java"], "blurb": "A made-up app."}],
        "resumes": [
            {"id": "A", "label": "one", "file": "first.pdf"},
            {"id": "B", "label": "two", "file": "second.pdf"},
        ],
        "upload_name": "Fake Person.pdf",
    }
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path, resumes


def write_answers(tmp_path: Path, items: list[dict[str, Any]]) -> Path:
    path = tmp_path / "answers.json"
    path.write_text(json.dumps(items), encoding="utf-8")
    return path


# ---- resumes ------------------------------------------------------------------


def test_extract_resume_text_reads_the_pdf(files: tuple[Path, Path]) -> None:
    assert "Spring Boot" in extract_resume_text(files[1] / "first.pdf")


def test_missing_resume_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(ProfileError, match="not found"):
        extract_resume_text(tmp_path / "nope.pdf")


# ---- profile ------------------------------------------------------------------


def test_load_profile_fills_profile_and_resumes(conn: sqlite3.Connection, files: tuple[Path, Path]) -> None:
    load_profile(conn, *files)
    assert conn.execute("SELECT full_name, upload_name FROM profile").fetchone()["upload_name"] == "Fake Person.pdf"
    texts = {r["id"]: r["extracted_text"] for r in conn.execute("SELECT * FROM resumes")}
    assert "Spring Boot" in texts["A"] and "Flutter" in texts["B"]


def test_loading_twice_does_not_duplicate(conn: sqlite3.Connection, files: tuple[Path, Path]) -> None:
    load_profile(conn, *files)
    load_profile(conn, *files)
    assert conn.execute("SELECT count(*) FROM profile").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM resumes").fetchone()[0] == 2


def test_upload_name_defaults_to_name_pdf(conn: sqlite3.Connection, files: tuple[Path, Path]) -> None:
    data = json.loads(files[0].read_text(encoding="utf-8"))
    del data["upload_name"]
    files[0].write_text(json.dumps(data), encoding="utf-8")
    load_profile(conn, *files)
    assert conn.execute("SELECT upload_name FROM profile").fetchone()[0] == "Fake Person.pdf"


def test_bad_resume_changes_nothing(conn: sqlite3.Connection, files: tuple[Path, Path]) -> None:
    (files[1] / "second.pdf").unlink()
    with pytest.raises(ProfileError):
        load_profile(conn, *files)
    assert conn.execute("SELECT count(*) FROM profile").fetchone()[0] == 0


def test_profile_json_problems_are_readable(conn: sqlite3.Connection, tmp_path: Path) -> None:
    bad = tmp_path / "profile.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ProfileError, match="not valid JSON"):
        load_profile(conn, bad, tmp_path)
    bad.write_text(json.dumps({"name": ""}), encoding="utf-8")
    with pytest.raises(ProfileError, match="name"):
        load_profile(conn, bad, tmp_path)


def test_summary_masks_private_fields(conn: sqlite3.Connection, files: tuple[Path, Path]) -> None:
    load_profile(conn, *files)
    printed = json.dumps(profile_summary(conn))
    for secret in (FAKE_EMAIL, FAKE_PHONE, "1 Fake Street", "4567", "fake.person"):
        assert secret not in printed
    assert "Fake Person" in printed


def test_masking_helpers() -> None:
    assert mask_email("mark@gmail.com") == "m***@gmail.com"
    assert mask_phone("+63 900 111 2233") == "***33"
    assert mask_email("") == "" and mask_phone("") == ""


# ---- answers ------------------------------------------------------------------

SALARY = "What is your expected monthly salary?"


def test_load_answers_and_defaults(conn: sqlite3.Connection, tmp_path: Path) -> None:
    path = write_answers(tmp_path, [{"question": "Q1", "answer": "A1"}])
    assert load_answers(conn, path) == 1
    row = conn.execute("SELECT kind, location_scope FROM answers").fetchone()
    assert (row["kind"], row["location_scope"]) == ("protected", "any")  # safest default


def test_reload_updates_but_keeps_times_used(conn: sqlite3.Connection, tmp_path: Path) -> None:
    path = write_answers(tmp_path, [{"question": "Q1", "answer": "old", "kind": "fixed"}])
    load_answers(conn, path)
    conn.execute("UPDATE answers SET times_used = 5")
    write_answers(tmp_path, [{"question": "Q1", "answer": "new", "kind": "fixed"}])
    load_answers(conn, path)
    row = conn.execute("SELECT answer, times_used FROM answers").fetchone()
    assert (row["answer"], row["times_used"]) == ("new", 5)


@pytest.mark.parametrize(
    "bad",
    [
        {"question": "Q", "answer": "A", "kind": "legal"},
        {"question": "Q", "answer": "A", "location_scope": "mars"},
        {"question": "Q", "answer": "A", "location_scope": "city"},  # city scope without a city
        {"question": "Q", "answer": ""},
    ],
)
def test_invalid_answers_are_rejected_with_a_position(conn: sqlite3.Connection, tmp_path: Path, bad: dict[str, str]) -> None:
    with pytest.raises(ProfileError, match="answer #1"):
        load_answers(conn, write_answers(tmp_path, [bad]))


@pytest.fixture()
def salary_bank(conn: sqlite3.Connection, tmp_path: Path) -> sqlite3.Connection:
    load_answers(
        conn,
        write_answers(
            tmp_path,
            [
                {"question": SALARY, "answer": "PHP 20,000", "location_scope": "city", "city": "Metro Manila", "kind": "fixed"},
                {"question": SALARY, "answer": "USD 600", "location_scope": "remote", "kind": "fixed"},
                {"question": "Can you start now?", "answer": "Yes", "kind": "fixed"},
            ],
        ),
    )
    return conn


def test_lookup_picks_the_answer_for_the_jobs_location(salary_bank: sqlite3.Connection) -> None:
    makati = lookup_answer(salary_bank, SALARY, job_scope="city", job_city="metro manila")
    remote = lookup_answer(salary_bank, SALARY, job_scope="remote")
    assert makati is not None and makati["answer"] == "PHP 20,000"
    assert remote is not None and remote["answer"] == "USD 600"


def test_lookup_returns_none_when_no_answer_fits(salary_bank: sqlite3.Connection) -> None:
    """A job in Cebu has no saved salary: it must become an unknown question, not a wrong answer."""
    assert lookup_answer(salary_bank, SALARY, job_scope="city", job_city="Cebu") is None
    assert lookup_answer(salary_bank, SALARY, job_scope="abroad") is None


def test_lookup_ignores_case_and_spaces_and_falls_back_to_any(salary_bank: sqlite3.Connection) -> None:
    row = lookup_answer(salary_bank, "  can you START now?  ", job_scope="remote")
    assert row is not None and row["answer"] == "Yes"


# ---- secrets (fake keyring, never the real Credential Manager) ------------------


@pytest.fixture()
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], str]:
    store: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(secrets.keyring, "get_password", lambda s, n: store.get((s, n)))
    monkeypatch.setattr(secrets.keyring, "set_password", lambda s, n, v: store.__setitem__((s, n), v))

    def delete(service: str, name: str) -> None:
        if (service, name) not in store:
            raise secrets.PasswordDeleteError("missing")
        del store[(service, name)]

    monkeypatch.setattr(secrets.keyring, "delete_password", delete)
    return store


def test_secret_round_trip(fake_keyring: dict[tuple[str, str], str]) -> None:
    assert secrets.get_secret("hunter_api_key") is None
    secrets.set_secret("hunter_api_key", "abc")
    assert secrets.get_secret("hunter_api_key") == "abc"
    assert secrets.delete_secret("hunter_api_key") is True
    assert secrets.delete_secret("hunter_api_key") is False


@pytest.mark.parametrize("name", ["", "../x", "a b"])
def test_bad_secret_names_and_empty_values_are_refused(fake_keyring: dict[tuple[str, str], str], name: str) -> None:
    with pytest.raises(secrets.SecretsError):
        secrets.set_secret(name, "value")
    with pytest.raises(secrets.SecretsError):
        secrets.set_secret("good_name", "")


# ---- safety ---------------------------------------------------------------------

MOCK = Settings(run_mode="mock")
DRY = Settings(run_mode="dry_run")


@pytest.mark.parametrize("settings", [MOCK, DRY, Settings(run_mode="live")])
@pytest.mark.parametrize("kind", ["submit", "send"])
def test_submit_and_send_are_never_allowed_in_v0(settings: Settings, kind: str) -> None:
    with pytest.raises(safety.SafetyError, match="never done automatically"):
        safety.check(kind, "anything", settings=settings)


def test_mock_mode_blocks_real_websites_but_not_fixtures() -> None:
    with pytest.raises(safety.SafetyError):
        safety.check("navigate", "https://prosple.com", settings=MOCK)
    safety.check("navigate", "file:///fixtures/forms/a.html", settings=MOCK)
    safety.check("navigate", "https://prosple.com", settings=DRY)


def test_unknown_action_is_refused() -> None:
    with pytest.raises(safety.SafetyError):
        safety.check("delete_everything", settings=DRY)


def test_log_action_writes_a_row(conn: sqlite3.Connection) -> None:
    row_id = safety.log_action(conn, "fill", "Expected salary", "answer from bank #1")
    row = conn.execute("SELECT * FROM action_log WHERE id = ?", (row_id,)).fetchone()
    assert (row["kind"], row["target"]) == ("fill", "Expected salary")


def test_also_asked_as_loads_into_aliases_and_is_rebuilt(tmp_path: Path) -> None:
    conn = connect(":memory:")
    init_db(conn)
    path = tmp_path / "answers.json"
    path.write_text(json.dumps([
        {"question": "When can you start?", "answer": "Now", "kind": "fixed",
         "also_asked_as": ["Earliest start date", "  ", "when can you start?"]},
    ]), encoding="utf-8")
    load_answers(conn, path)
    rows = conn.execute("SELECT question, alias FROM answer_aliases").fetchall()
    assert [(r["question"], r["alias"]) for r in rows] == [("When can you start?", "Earliest start date")]

    path.write_text(json.dumps([{"question": "When can you start?", "answer": "Now", "kind": "fixed"}]), encoding="utf-8")
    load_answers(conn, path)
    assert conn.execute("SELECT count(*) FROM answer_aliases").fetchone()[0] == 0
