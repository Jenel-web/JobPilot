"""Tests for the sensitive-question detector (engine/forms/answers.py, ``is_sensitive``).

A sensitive question is legal / eligibility / identity related. The AI must never write
its answer, so this detector has to catch every wording, and must not fire on ordinary
questions (a false alarm only costs you a manual answer, but too many make the tool useless).
"""

from __future__ import annotations

import pytest

from engine.forms.answers import is_sensitive


@pytest.mark.parametrize(
    "label",
    [
        "Will you now or in the future require visa sponsorship?",
        "Are you legally authorized to work in the Philippines?",
        "Are you authorised to work in this country?",
        "Do you have the right to work here?",
        "Do you hold a valid work permit?",
        "Are you a citizen of the Philippines?",
        "What is your nationality?",
        "Have you ever been employed by a government agency?",
        "Have you ever been convicted of a crime?",
        "Do you have a criminal record?",
        "Do you consent to a background check?",
        "I agree to the terms and conditions and consent to data processing",
        "Are you related to an employee of this company?",
        "Do you have a disability?",
        "Gender",
        "What is your ethnicity?",
        "Race / ethnic origin",
        "Are you a protected veteran?",
        "What was your GPA?",
        "What is your grade point average?",
        "What is your current salary?",
        "Date of birth",
        "Are you 18 years or older?",
        "Pronouns",
        "Marital status",
        "Religion",
    ],
)
def test_sensitive_wordings_are_caught(label: str) -> None:
    assert is_sensitive(label), label


@pytest.mark.parametrize(
    "label",
    [
        "Why do you want to work here?",
        "Describe a project you are proud of",
        "Do you have Docker experience? Please explain",
        "When can you start?",
        "What is your expected monthly salary?",
        "Are you comfortable working in a hybrid setup?",
        "Tell us about your biggest strength",
        "Which programming languages do you know?",
        "Cover letter",
    ],
)
def test_ordinary_questions_are_not_sensitive(label: str) -> None:
    assert not is_sensitive(label), label


def test_words_inside_other_words_do_not_fire() -> None:
    # "race" in "embrace", "grade" in "upgrade", "gender" in "engender" are not the sensitive words
    assert not is_sensitive("How do you embrace feedback?")
    assert not is_sensitive("Describe a time you had to upgrade a system")


def test_related_to_only_fires_for_people() -> None:
    assert is_sensitive("Are you related to any current employee?")
    assert not is_sensitive("Describe a project related to a web app")


def test_blank_label_is_not_sensitive() -> None:
    assert not is_sensitive("")
