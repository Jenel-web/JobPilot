"""Tests for the personal-field detector (engine/forms/answers.py).

Fake profile values only. The two real-form tests read the saved, sanitized
fixtures offline: no network, no AI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from engine.db import connect, init_db
from engine.forms.answers import detect_personal, fill_personal, format_phone, pick_option, profile_values
from engine.forms.reader import FormField, read_fields
from engine.settings import ROOT

VALUES = {
    "first_name": "Juan", "middle_name": "Santos", "middle_initial": "S.", "last_name": "Dela Cruz",
    "full_name": "Juan Santos Dela Cruz", "email": "juan@example.com", "phone": "+63 900 123 4567",
    "address": "12 Fake St, Faketown", "location": "Faketown, Philippines", "city": "Faketown",
    "country": "Philippines", "linkedin": "https://linkedin.com/in/fake", "github": "https://github.com/fake",
    "portfolio": "",
}


def field(label: str = "", type: str = "text", **kw: object) -> FormField:
    return FormField(label=label, type=type, **kw)  # type: ignore[arg-type]


# ---- recognising ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("First name", "first_name"),
        ("Given Name*", "first_name"),
        ("Middle name (optional)", "middle_name"),
        ("Middle initial", "middle_initial"),
        ("Last name", "last_name"),
        ("Surname", "last_name"),
        ("Full name", "full_name"),
        ("Name", "full_name"),
        ("Your name", "full_name"),
        ("First and last name", "full_name"),
        ("Enter your e-mail", "email"),
        ("Email address", "email"),  # email wins over address
        ("Mobile number", "phone"),
        ("Contact No.", "phone"),
        ("Address", "address"),
        ("Home address", "address"),
        ("Location (City)", "city"),
        ("City", "city"),
        ("Country", "country"),
        ("Location", "location"),
        ("LinkedIn profile URL", "linkedin"),
        ("GitHub", "github"),
        ("Portfolio or personal website URL", "portfolio"),
    ],
)
def test_short_labels_are_recognised(label: str, expected: str) -> None:
    assert detect_personal(field(label)) == (expected, "label")


@pytest.mark.parametrize(
    "label",
    [
        "Do you agree to be contacted by email or phone about this application?",  # long: a consent question
        "Referrer email",  # someone else's
        "Emergency contact phone",
        "Name of the employee who referred you",
        "School name",
        "Company name",
        "Username",
        "Headline",
        "Summary",
        "Country code",
        "",
    ],
)
def test_questions_and_other_peoples_details_are_not_personal(label: str) -> None:
    assert detect_personal(field(label)) is None


def test_autocomplete_beats_everything() -> None:
    # Label says "Name" but the page marks it as the family name.
    assert detect_personal(field("Name", autocomplete="family-name")) == ("last_name", "autocomplete")
    assert detect_personal(field("", autocomplete="section-apply shipping address-level2")) == ("city", "autocomplete")


def test_input_type_recognises_email_and_phone() -> None:
    assert detect_personal(field("Primary", type="email")) == ("email", "type")
    assert detect_personal(field("Primary", type="tel")) == ("phone", "type")


def test_name_attribute_is_used_when_the_label_is_missing() -> None:
    assert detect_personal(field("", name="job_application[first_name]")) == ("first_name", "name")
    assert detect_personal(field("", name="phoneNumber")) == ("phone", "name")
    assert detect_personal(field("", name="question_38619146002")) is None


def test_choice_fields_other_than_dropdowns_are_never_personal() -> None:
    assert detect_personal(field("Email", type="checkbox", options=["Yes"])) is None
    assert detect_personal(field("Name", type="radio", options=["A", "B"])) is None
    assert detect_personal(field("Name", type="file")) is None


def test_textarea_only_counts_for_address() -> None:
    assert detect_personal(field("Address", type="textarea")) == ("address", "label")
    assert detect_personal(field("Full name", type="textarea")) is None


# ---- phone format ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("hints", "expected"),
    [
        ({"autocomplete": "tel-national"}, "09001234567"),
        ({"placeholder": "+63 9XX XXX XXXX"}, "+639001234567"),
        ({"placeholder": "09XX XXX XXXX"}, "09001234567"),
        ({"placeholder": "9XXXXXXXXX"}, "9001234567"),
        ({"pattern": "\\+63[0-9]{10}"}, "+639001234567"),
        ({"pattern": "09[0-9]{9}"}, "09001234567"),
        ({"max_length": 11}, "09001234567"),
        ({"max_length": 10}, "9001234567"),
        ({}, "+639001234567"),  # no hint: the way it is stored (+63...)
    ],
)
def test_phone_is_written_in_the_format_the_field_expects(hints: dict[str, object], expected: str) -> None:
    value, why = format_phone("+63 900 123 4567", field("Phone", type="tel", **hints))
    assert value == expected and why


def test_phone_stored_locally_defaults_to_local() -> None:
    assert format_phone("0900-123-4567", field("Phone", type="tel"))[0] == "09001234567"


def test_unusual_phone_is_left_as_stored() -> None:
    assert format_phone("+1 415 555 0100", field("Phone", type="tel", placeholder="09XX"))[0] == "+1 415 555 0100"


# ---- values ------------------------------------------------------------------------


def test_fill_uses_profile_values() -> None:
    fill = fill_personal(field("Last name"), VALUES)
    assert fill is not None and (fill.value, fill.flagged) == ("Dela Cruz", False)
    assert fill_personal(field("Middle initial"), VALUES).value == "S."  # type: ignore[union-attr]


def test_missing_value_is_left_blank_and_flagged() -> None:
    fill = fill_personal(field("Portfolio"), VALUES)
    assert fill is not None and fill.value == "" and fill.flagged and "portfolio" in fill.note


def test_dropdown_picks_the_matching_option() -> None:
    fill = fill_personal(field("Country", type="select", options=["Japan", "Philippines (+63)", "Peru"]), VALUES)
    assert fill is not None and fill.value == "Philippines (+63)" and not fill.flagged


def test_dropdown_with_no_matching_option_is_flagged() -> None:
    fill = fill_personal(field("Country", type="select", options=["Japan", "Peru"]), VALUES)
    assert fill is not None and fill.value == "" and fill.flagged


def test_pick_option_ignores_tiny_options() -> None:
    assert pick_option("Philippines", ["A", "Ph"]) == ""


def test_not_personal_returns_none() -> None:
    assert fill_personal(field("Why do you want to work here?", type="textarea"), VALUES) is None


def test_profile_values_from_the_database(tmp_path: Path) -> None:
    from engine.profile import load_profile

    conn = connect(":memory:")
    init_db(conn)
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({
        "first_name": "Juan", "middle_name": "Santos", "last_name": "Dela Cruz",
        "email": "juan@example.com", "phone": "+63 900 123 4567", "location": "Faketown, Metro Manila, Philippines",
        "links": {"github": "https://github.com/fake"},
    }), encoding="utf-8")
    load_profile(conn, path, tmp_path)
    values = profile_values(conn)
    assert values["middle_initial"] == "S."
    assert (values["city"], values["country"]) == ("Faketown", "Philippines")
    assert values["github"] == "https://github.com/fake" and values["portfolio"] == ""


# ---- the two saved real forms -----------------------------------------------------------


def read_fixture(name: str) -> list[FormField]:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content((ROOT / "fixtures" / "forms" / f"{name}.html").read_text(encoding="utf-8"))
        page.wait_for_timeout(300)
        fields = read_fields(page)
        browser.close()
    return fields


def personal_map(fields: list[FormField]) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in fields:
        found = detect_personal(f)
        if found and f.label:
            out[f.label] = found[0]
    return out


def test_workable_form_personal_fields() -> None:
    found = personal_map(read_fixture("angkas_workable"))
    assert found == {
        "First name": "first_name",
        "Last name": "last_name",
        "Email": "email",
        "Phone": "phone",
        "Address": "address",
    }


def test_greenhouse_form_personal_fields() -> None:
    found = personal_map(read_fixture("indiecampers_greenhouse"))
    assert found["First Name"] == "first_name"
    assert found["Last Name"] == "last_name"
    assert found["Email"] == "email"
    assert found["Phone"] == "phone"
    assert found["Country"] == "country"
    assert found["Location (City)"] == "city"
    assert "Write a message..." not in found
    assert not any("English" in label or "university" in label for label in found)
