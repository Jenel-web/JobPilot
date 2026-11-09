"""Profile, resumes and the answer bank: load them from files into SQLite, read them back.

Your files are the source of truth in v0:

    data/profile.json     your details + the list of resume files
    data/resumes/*.pdf    your two resumes
    data/answers.json     your saved answers

``load_all()`` copies them into the database. It is safe to run again after you
edit a file: rows are updated, not duplicated (``times_used`` is kept).

Privacy: ``profile_summary()`` masks email and phone, so printing it never
leaks them. Private fields are filled into forms by code and never put in an
AI prompt (CLAUDE.md rule 3).
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from engine.db import ANSWER_KINDS, LOCATION_SCOPES
from engine.settings import ROOT

DATA_DIR = ROOT / "data"
PROFILE_PATH = DATA_DIR / "profile.json"
ANSWERS_PATH = DATA_DIR / "answers.json"
RESUMES_DIR = DATA_DIR / "resumes"


class ProfileError(Exception):
    """A data file is missing, malformed or unreadable (the message says which)."""


# ---- shapes of the files (Pydantic checks them before anything reaches SQLite) ----


class Education(BaseModel):
    school: str = ""
    degree: str = ""
    year_level: str = ""
    grad_year: int | None = None
    gpa: str = ""


class Links(BaseModel):
    github: str = ""
    linkedin: str = ""
    portfolio: str = ""


class JobPreferences(BaseModel):
    job_types: list[str] = []
    target_roles: list[str] = []
    preferred_locations: list[str] = []


class Project(BaseModel):
    name: str = Field(min_length=1)
    tech: list[str] = []
    blurb: str = ""


class ResumeEntry(BaseModel):
    id: Literal["A", "B"]
    label: str = ""
    file: str = Field(min_length=1)  # file name inside data/resumes/


class ProfileFile(BaseModel):
    """Shape of ``data/profile.json``."""

    name: str = Field(min_length=1)
    email: str = ""
    phone: str = ""
    address: str = ""
    education: Education = Education()
    location: str = ""
    open_to_remote: bool = False
    links: Links = Links()
    job_preferences: JobPreferences = JobPreferences()
    skills: list[str] = []
    summary: str = ""
    projects: list[Project] = []
    resumes: list[ResumeEntry] = []
    upload_name: str = ""


class AnswerEntry(BaseModel):
    """One item of ``data/answers.json``."""

    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    location_scope: Literal["any", "city", "remote", "abroad"] = "any"
    city: str = ""
    kind: Literal["fixed", "open", "protected"] = "protected"  # safest default
    # Other ways a form may word this question. They only help RAG find it;
    # the answer above is used for all of them.
    also_asked_as: list[str] = []


# ---- reading files ----------------------------------------------------------


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise ProfileError(f"Cannot read {path.name}: {exc.strerror}") from exc
    except ValueError as exc:
        raise ProfileError(f"{path.name} is not valid JSON: {exc}") from exc


def extract_resume_text(pdf_path: Path) -> str:
    """Return all the text in a resume PDF (read with pdfplumber).

    Raises ``ProfileError`` if the file is missing or has no text layer (a scanned
    image PDF), because the resume picker and RAG need real text.
    """
    import pdfplumber  # imported here so the rest of the module works without it

    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join((page.extract_text() or "") for page in pdf.pages).strip()
    except FileNotFoundError as exc:
        raise ProfileError(f"Resume file not found: {pdf_path.name}") from exc
    except Exception as exc:  # corrupt or encrypted PDF
        raise ProfileError(f"Cannot read resume {pdf_path.name}: {type(exc).__name__}") from exc
    if not text:
        raise ProfileError(f"Resume {pdf_path.name} has no readable text (is it a scanned image?)")
    return text


# ---- loading into SQLite ----------------------------------------------------


def load_profile(
    conn: sqlite3.Connection,
    profile_path: Path = PROFILE_PATH,
    resumes_dir: Path = RESUMES_DIR,
) -> ProfileFile:
    """Load ``profile.json`` and the resume PDFs into the ``profile`` and ``resumes`` tables."""
    try:
        data = ProfileFile.model_validate(_read_json(profile_path))
    except ValidationError as exc:
        raise ProfileError(f"{profile_path.name} has a problem: {_first_error(exc)}") from exc

    # Read every PDF first so a bad file changes nothing in the database.
    texts = {r.id: extract_resume_text(resumes_dir / r.file) for r in data.resumes}

    with conn:  # one transaction: all or nothing
        conn.execute(
            """
            INSERT INTO profile (id, full_name, email, phone, address, school, degree, year_level,
                grad_year, gpa, location, open_to_remote, github, linkedin, portfolio, job_types,
                target_roles, preferred_locations, skills, summary, projects, upload_name)
            VALUES (1, :full_name, :email, :phone, :address, :school, :degree, :year_level,
                :grad_year, :gpa, :location, :open_to_remote, :github, :linkedin, :portfolio,
                :job_types, :target_roles, :preferred_locations, :skills, :summary, :projects,
                :upload_name)
            ON CONFLICT(id) DO UPDATE SET
                full_name=excluded.full_name, email=excluded.email, phone=excluded.phone,
                address=excluded.address, school=excluded.school, degree=excluded.degree,
                year_level=excluded.year_level, grad_year=excluded.grad_year, gpa=excluded.gpa,
                location=excluded.location, open_to_remote=excluded.open_to_remote,
                github=excluded.github, linkedin=excluded.linkedin, portfolio=excluded.portfolio,
                job_types=excluded.job_types, target_roles=excluded.target_roles,
                preferred_locations=excluded.preferred_locations, skills=excluded.skills,
                summary=excluded.summary, projects=excluded.projects,
                upload_name=excluded.upload_name
            """,
            {
                "full_name": data.name,
                "email": data.email,
                "phone": data.phone,
                "address": data.address,
                "school": data.education.school,
                "degree": data.education.degree,
                "year_level": data.education.year_level,
                "grad_year": data.education.grad_year,
                "gpa": data.education.gpa,
                "location": data.location,
                "open_to_remote": int(data.open_to_remote),
                "github": data.links.github,
                "linkedin": data.links.linkedin,
                "portfolio": data.links.portfolio,
                "job_types": json.dumps(data.job_preferences.job_types),
                "target_roles": json.dumps(data.job_preferences.target_roles),
                "preferred_locations": json.dumps(data.job_preferences.preferred_locations),
                "skills": json.dumps(data.skills),
                "summary": data.summary,
                "projects": json.dumps([p.model_dump() for p in data.projects]),
                "upload_name": data.upload_name or f"{data.name}.pdf",
            },
        )
        for r in data.resumes:
            conn.execute(
                """
                INSERT INTO resumes (id, label, file_path, extracted_text) VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET label=excluded.label,
                    file_path=excluded.file_path, extracted_text=excluded.extracted_text
                """,
                (r.id, r.label, _display_path(resumes_dir / r.file), texts[r.id]),
            )
    return data


def load_answers(conn: sqlite3.Connection, answers_path: Path = ANSWERS_PATH) -> int:
    """Load ``answers.json`` into the ``answers`` table; returns how many answers were loaded.

    Existing answers (same question + scope + city) are updated in place and keep
    their ``times_used``. Answers missing from the file are NOT deleted.

    Alternate wordings (``also_asked_as``) are rebuilt from the file every time,
    so the file stays the only place you edit them. Run ``rag reindex`` after.
    """
    raw = _read_json(answers_path)
    if not isinstance(raw, list):
        raise ProfileError(f"{answers_path.name} must be a list of answers")
    entries: list[AnswerEntry] = []
    for index, item in enumerate(raw, start=1):
        try:
            entry = AnswerEntry.model_validate(item)
        except ValidationError as exc:
            raise ProfileError(f"{answers_path.name}, answer #{index}: {_first_error(exc)}") from exc
        if entry.location_scope == "city" and not entry.city.strip():
            raise ProfileError(f"{answers_path.name}, answer #{index}: scope 'city' needs a city")
        entries.append(entry)

    with conn:
        for e in entries:
            conn.execute(
                """
                INSERT INTO answers (question, answer, location_scope, city, kind)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(question, location_scope, city)
                DO UPDATE SET answer=excluded.answer, kind=excluded.kind
                """,
                (e.question.strip(), e.answer, e.location_scope, e.city.strip(), e.kind),
            )
        conn.execute("DELETE FROM answer_aliases")
        for e in entries:
            for alias in e.also_asked_as:
                if alias.strip() and alias.strip().lower() != e.question.strip().lower():
                    conn.execute(
                        "INSERT OR IGNORE INTO answer_aliases (question, alias) VALUES (?, ?)",
                        (e.question.strip(), alias.strip()),
                    )
    return len(entries)


def load_all(conn: sqlite3.Connection) -> dict[str, int]:
    """Load profile, resumes and answers. Returns counts, e.g. ``{"resumes": 2, "answers": 96}``."""
    profile = load_profile(conn)
    return {"resumes": len(profile.resumes), "answers": load_answers(conn)}


# ---- reading from SQLite ----------------------------------------------------


def lookup_answer(
    conn: sqlite3.Connection,
    question: str,
    *,
    job_scope: str = "any",
    job_city: str = "",
) -> sqlite3.Row | None:
    """Find the saved answer for ``question`` that fits the job's location.

    Matching is exact (ignoring case and extra spaces); smarter matching of
    reworded questions comes with RAG in Phase 3.

    Args:
        job_scope: where the job is: ``"city"`` (on-site in ``job_city``),
            ``"remote"`` or ``"abroad"``. ``"any"`` if unknown.
        job_city: the job's city when ``job_scope == "city"``.

    Preference: an answer for exactly this location beats the ``any`` answer.
    Returns ``None`` if no saved answer fits (the caller adds it to unknown questions).
    """
    if job_scope not in LOCATION_SCOPES:
        raise ValueError(f"unknown location scope: {job_scope!r}")
    rows = conn.execute(
        "SELECT * FROM answers WHERE lower(trim(question)) = lower(trim(?))", (question,)
    ).fetchall()
    exact = [
        r
        for r in rows
        if r["location_scope"] == job_scope
        and (job_scope != "city" or r["city"].lower() == job_city.strip().lower())
    ]
    if job_scope != "any" and exact:
        return exact[0]
    any_rows = [r for r in rows if r["location_scope"] == "any"]
    return any_rows[0] if any_rows else None


def mask_email(email: str) -> str:
    """``mark@gmail.com`` -> ``m***@gmail.com``."""
    if "@" not in email:
        return "***" if email else ""
    name, domain = email.split("@", 1)
    return f"{name[:1]}***@{domain}"


def mask_phone(phone: str) -> str:
    """Keep only the last 2 digits: ``+63 900 111 2233`` -> ``***33``."""
    digits = re.sub(r"\D", "", phone)
    return f"***{digits[-2:]}" if digits else ""


def profile_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """The profile as a dict that is safe to print: email/phone masked, address hidden."""
    row = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
    if row is None:
        raise ProfileError("No profile in the database yet. Run: python -m engine.cli load")
    resumes = conn.execute("SELECT id, label, file_path, length(extracted_text) AS chars FROM resumes ORDER BY id")
    return {
        "name": row["full_name"],
        "email": mask_email(row["email"] or ""),
        "phone": mask_phone(row["phone"] or ""),
        "address": "(hidden)" if row["address"] else "",
        "education": f'{row["degree"]}, {row["school"]} ({row["year_level"]}, grad {row["grad_year"]})',
        "location": row["location"],
        "upload_name": row["upload_name"],
        "skills": len(json.loads(row["skills"])),
        "projects": [p["name"] for p in json.loads(row["projects"])],
        "resumes": [
            {"id": r["id"], "label": r["label"], "file": r["file_path"], "text_chars": r["chars"]}
            for r in resumes
        ],
    }


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    where = ".".join(str(part) for part in err["loc"]) or "(root)"
    return f"{where}: {err['msg']}"


def _display_path(path: Path) -> str:
    """Store paths relative to the project folder, so the database never holds ``C:\\...``."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


__all__ = [
    "ANSWER_KINDS",
    "ProfileError",
    "extract_resume_text",
    "load_all",
    "load_answers",
    "load_profile",
    "lookup_answer",
    "profile_summary",
]
