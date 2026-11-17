"""Tests for relocation questions ("Are you open to relocating?").

The yes/no is decided by CODE from where the job is (the job post text, or the scope/city); the AI only words it.
The AI and the search are faked. Nothing here touches Ollama, Gemini or a browser.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from engine import ai, rag
from engine.db import connect, init_db
from engine.forms import answers, drafting
from engine.forms.jobpost import JobLocation, read_job_location, relocation_stance
from engine.forms.reader import FormField

QUESTION = "Are you open to relocating?"


# ---- reading where the job is -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, kind",
    [
        ("Software Engineer Intern. Location: Makati City. Hybrid, 3 days in office.", "metro_manila"),
        ("Based in BGC, Taguig. Full-time.", "metro_manila"),
        ("Office: Ortigas Center, Pasig", "metro_manila"),
        ("Quezon City, Metro Manila", "metro_manila"),
        ("Fully remote role. Work from anywhere in the Philippines.", "remote"),
        ("This is a work-from-home position.", "remote"),
        ("Hybrid: Makati or remote", "metro_manila"),
        ("Location: Cebu City. On-site.", "unknown"),
        ("Singapore office, relocation package offered", "unknown"),
        ("Remote work is not available. On-site in Davao.", "unknown"),
        ("", "unknown"),
        ("We are a fast-growing startup. Apply now!", "unknown"),
    ],
)
def test_the_job_post_text_gives_where_the_job_is(text: str, kind: str) -> None:
    assert read_job_location(text).kind == kind


def test_the_evidence_is_the_words_found_in_the_post() -> None:
    assert read_job_location("Office in Makati City").evidence.lower() == "makati"
    assert "remote" in read_job_location("Fully remote").evidence.lower()


def test_a_scope_and_city_are_used_when_there_is_no_text() -> None:
    assert read_job_location("", scope="remote").kind == "remote"
    assert read_job_location("", scope="city", city="Pasig").kind == "metro_manila"
    assert read_job_location("", scope="city", city="Cebu").kind == "unknown"
    assert read_job_location("", scope="abroad").kind == "unknown"
    assert read_job_location("", scope="any").kind == "unknown"


def test_the_text_wins_over_the_scope() -> None:
    assert read_job_location("On-site in Cebu City", scope="remote").kind == "unknown"


def test_remote_and_commutable_are_yes_everything_else_is_no() -> None:
    assert relocation_stance(JobLocation("remote", "remote")).yes
    assert relocation_stance(JobLocation("metro_manila", "Makati")).yes
    unknown = relocation_stance(JobLocation("unknown", ""))
    assert not unknown.yes and "not willing to relocate" in unknown.reason


# ---- the answer ------------------------------------------------------------------------------------------


class FakeAI:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.text = ""
        self.confidence = 0.9

    def __call__(self, task: str, prompt: str, **kw: object) -> dict:
        self.prompts.append(prompt)
        return {"answer": self.text, "confidence": self.confidence}


@pytest.fixture
def fake_ai(monkeypatch: pytest.MonkeyPatch) -> FakeAI:
    fake = FakeAI()
    monkeypatch.setattr(ai, "ask_ai", fake)
    return fake


@pytest.fixture(autouse=True)
def facts(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_retrieve(conn: object, q: str, k: int = 5, *, sources: object = None, settings: object = None) -> list[rag.Hit]:
        return [
            rag.Hit(1, "profile", "preferences", "Target roles: Java developer intern. Based in Mandaluyong, Metro Manila.", 0.7),
            rag.Hit(2, "profile", "about:values", "What I value: staying close to family, so I prefer to live at home.", 0.6),
            rag.Hit(3, "profile", "skills", "Skills: java", 0.5),
        ]

    monkeypatch.setattr(rag, "retrieve", fake_retrieve)


@pytest.fixture
def conn() -> Iterator:
    connection = connect(":memory:")
    init_db(connection)
    yield connection
    connection.close()


def box(label: str = QUESTION, type: str = "textarea", **kw: object) -> FormField:
    return FormField(label=label, type=type, **kw)  # type: ignore[arg-type]


def ask(conn: object, job_text: str | None, field: FormField | None = None):
    return answers.answer_field(conn, field or box(), {}, job_text=job_text)  # type: ignore[arg-type]


@pytest.mark.parametrize("label", [QUESTION, "Are you willing to relocate?", "Would you be willing to relocate for this role?", "Open to relocation?"])
def test_relocation_questions_are_recognised(label: str) -> None:
    assert answers.is_relocation_question(label)


@pytest.mark.parametrize("label", ["Where are you currently located?", "Are you authorized to work in the Philippines?", "Describe a project"])
def test_other_questions_are_not_relocation_questions(label: str) -> None:
    assert not answers.is_relocation_question(label)


def test_a_far_job_is_no_even_if_the_ai_says_yes(conn: object, fake_ai: FakeAI) -> None:
    fake_ai.text = "Yes, I would love to relocate for this role."
    result = ask(conn, "On-site in Cebu City")
    assert result.value.lower().startswith("no")  # the AI's yes is rejected, the plain "no" is used
    assert result.flagged


def test_a_remote_job_is_yes(conn: object, fake_ai: FakeAI) -> None:
    fake_ai.text = "Yes, I'm open to it, and since the role is remote there is no move involved."
    result = ask(conn, "Fully remote position")
    assert result.value == fake_ai.text and result.flagged and result.source == "draft"


def test_a_metro_manila_job_is_yes_and_the_ai_may_use_your_notes(conn: object, fake_ai: FakeAI) -> None:
    fake_ai.text = "I don't need to relocate: the role is in Makati and I'm based in Mandaluyong, so I can commute."
    result = ask(conn, "Office: Makati City")
    assert result.value == fake_ai.text
    assert "Mandaluyong" in fake_ai.prompts[0] and "STANCE: YES" in fake_ai.prompts[0]


def test_an_unknown_location_is_no_and_flagged(conn: object, fake_ai: FakeAI) -> None:
    fake_ai.text = "I'm not able to relocate, but I can work remotely or on-site in Metro Manila."
    result = ask(conn, "")
    assert result.value == fake_ai.text and "STANCE: NO" in fake_ai.prompts[0]
    assert result.flagged and "location" in result.note.lower()


def test_a_reply_that_flips_the_stance_is_replaced_by_the_plain_answer(conn: object, fake_ai: FakeAI) -> None:
    fake_ai.text = "I'm not able to relocate."
    result = ask(conn, "Fully remote position")
    assert result.value.lower().startswith("yes")


def test_a_new_place_in_the_reply_is_rejected(conn: object, fake_ai: FakeAI) -> None:
    fake_ai.text = "No, but I could move to Davao for the right role."
    result = ask(conn, "On-site in Cebu City")
    assert "Davao" not in result.value and result.value.lower().startswith("no")


def test_private_data_in_the_reply_is_rejected(conn: object, fake_ai: FakeAI) -> None:
    fake_ai.text = "No. Call me on 09171234567."
    assert "0917" not in ask(conn, "On-site in Cebu City").value


def test_a_radio_gets_the_plain_option_and_never_calls_the_ai(conn: object, fake_ai: FakeAI) -> None:
    field = box(type="radio", options=["Yes", "No"])
    assert ask(conn, "Office in Makati", field).value == "Yes"
    assert ask(conn, "On-site in Cebu City", field).value == "No"
    assert fake_ai.prompts == []


def test_without_a_job_post_the_saved_answers_work_as_before(conn: object, fake_ai: FakeAI) -> None:
    """``job_text=None`` means no job post was given at all: the relocation branch stays out of the way."""
    assert not answers.wants_relocation_stance(box(), None)
    assert answers.wants_relocation_stance(box(), "")  # a post was given but it is empty: the location is unknown


def test_answer_form_passes_the_job_text_on(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[object] = []

    def fake_field(c: object, f: FormField, values: object, **kw: object) -> answers.FieldAnswer:
        seen.append(kw["job_text"])
        return answers.FieldAnswer(f.label, "x", "bank", False)

    monkeypatch.setattr(answers, "profile_values", lambda c: {})
    monkeypatch.setattr(answers, "answer_field", fake_field)
    monkeypatch.setattr(answers.safety, "log_action", lambda *a, **k: None)
    answers.answer_form(None, [box()], job_text="Makati")  # type: ignore[arg-type]
    assert seen == ["Makati"]
    assert drafting  # the module is imported for the relocation prompt
