"""Tests for the form reader. They read the saved synthetic page in fixtures/forms/
with a headless browser and never touch a real website."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from playwright.sync_api import Page, sync_playwright

from engine.forms.reader import FormField, build_fields, clean_label, read_fields
from engine.settings import ROOT

SAMPLE = ROOT / "fixtures" / "forms" / "sample_form.html"


@pytest.fixture(scope="module")
def fields() -> Iterator[dict[str, FormField]]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page: Page = browser.new_page()
        page.set_content(SAMPLE.read_text(encoding="utf-8"))
        result = read_fields(page)
        browser.close()
    by_label = {f.label: f for f in result}
    by_label["__all__"] = result  # type: ignore[assignment]
    yield by_label


def test_labels_are_cleaned_of_stars_and_optional(fields: dict[str, FormField]) -> None:
    assert "First name" in fields and fields["First name"].required
    assert "Headline" in fields and not fields["Headline"].required
    assert "Summary" in fields


def test_required_comes_from_the_flag_or_aria(fields: dict[str, FormField]) -> None:
    assert fields["Email"].required
    assert fields["Phone"].required and fields["Phone"].type == "tel"


def test_label_fallbacks_nearby_text_and_placeholder(fields: dict[str, FormField]) -> None:
    assert "Preferred city" in fields  # text just before the input
    assert "Nickname" in fields  # placeholder


def test_unlabelled_field_is_reported_as_needs_you(fields: dict[str, FormField]) -> None:
    unlabelled = [f for f in fields["__all__"] if f.name == "mystery"]  # type: ignore[attr-defined]
    assert len(unlabelled) == 1 and unlabelled[0].needs_you


def test_radios_become_one_question_with_options(fields: dict[str, FormField]) -> None:
    hybrid = fields["Are you open to a hybrid setup?"]
    assert hybrid.type == "radio" and hybrid.options == ["YES", "NO"] and hybrid.required
    assert len(hybrid.indexes) == 2


def test_checkbox_group_and_single_checkbox(fields: dict[str, FormField]) -> None:
    assert fields["Which tools do you use?"].options == ["Git", "Docker"]
    terms = fields["I agree to the terms"]
    assert terms.type == "checkbox" and terms.options == [] and terms.required


def test_select_options_and_hidden_file_input(fields: dict[str, FormField]) -> None:
    assert fields["Year level"].options == ["2nd year", "3rd year", "4th year"]
    assert fields["Resume"].type == "file" and fields["Resume"].required  # visually hidden, still found


def test_hidden_inputs_and_buttons_are_ignored(fields: dict[str, FormField]) -> None:
    names = {f.name for f in fields["__all__"]}  # type: ignore[attr-defined]
    assert "token" not in names and "secret_trap" not in names


def test_clean_label() -> None:
    assert clean_label("* What is your name? (Optional)") == "What is your name?"
    assert clean_label("  Email *  ") == "Email"


def test_unknown_input_types_fall_back_to_text() -> None:
    raw = [{"index": 0, "tag": "input", "type": "color", "name": "c", "label": "Colour", "group": "", "required": False, "options": []}]
    assert build_fields(raw)[0].type == "text"


def test_empty_label_falls_through_to_aria_labelledby() -> None:
    """Workable-style upload: an empty <label for> plus aria-labelledby naming the field."""
    html = """<label for="f"></label><span id="a">Photo</span><span id="b">Choose file</span>
              <input id="f" type="file" aria-labelledby="a b">"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        result = read_fields(page)
        browser.close()
    assert [f.label for f in result] == ["Photo"]


def test_real_company_page_saved_offline_reads_the_same_as_live() -> None:
    """fixtures/forms/angkas_workable.html: a real Workable application, captured and sanitized."""
    html = (ROOT / "fixtures" / "forms" / "angkas_workable.html").read_text(encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        result = read_fields(page)
        browser.close()
    by_label = {f.label: f for f in result}
    assert len(result) == 20
    assert by_label["Resume"].type == "file" and by_label["Resume"].required
    assert by_label["Photo"].type == "file" and not by_label["Photo"].required
    hybrid = by_label["Are you open to working on a hybrid setup? (minimum 3 days onsite)"]
    assert hybrid.type == "radio" and hybrid.options == ["YES", "NO"] and hybrid.required
    assert by_label["Email"].type == "email" and by_label["Phone"].type == "tel"
    assert sum(1 for f in result if f.needs_you) == 3  # three unlabelled address-part boxes


def _read_html(html: str) -> list[FormField]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        page.wait_for_timeout(300)  # let embedded frames load
        result = read_fields(page)
        browser.close()
    return result


def test_form_inside_an_iframe_is_found() -> None:
    """Regression: indiecampers.com shows its own page and embeds the Greenhouse form in an iframe."""
    inner = '<label for=a>First Name*</label><input id=a required><label for=b>Email*</label><input id=b type=email required>'
    outer = f'<label for=n>Newsletter e-mail</label><input id=n><iframe srcdoc="{inner}"></iframe>'
    result = _read_html(outer)
    labels = {f.label: f for f in result}
    assert set(labels) == {"Newsletter e-mail", "First Name", "Email"}
    assert labels["Newsletter e-mail"].frame == "" and labels["First Name"].frame != ""


def test_custom_dropdown_is_one_dropdown_not_two_fields() -> None:
    """Regression: react-select style dropdowns are a labelled role=combobox input plus a bare helper box."""
    html = (
        '<label id=c-label for=c>Country*</label><div><input id=c role=combobox aria-labelledby=c-label required>'
        '<div>Select...</div><input type=text></div>'
        '<label for=p>Phone*</label><input id=p type=tel required>'
    )
    result = _read_html(html)
    assert [(f.label, f.type) for f in result] == [("Country", "dropdown"), ("Phone", "tel")]


def test_invisible_search_boxes_are_ignored() -> None:
    html = '<input id=s type=search role=combobox style="width:0;height:0;padding:0;border:0" aria-label=Search><label for=x>Name</label><input id=x>'
    assert [f.label for f in _read_html(html)] == ["Name"]


def test_greenhouse_form_embedded_in_a_company_site_reads_cleanly() -> None:
    """fixtures/forms/indiecampers_greenhouse.html: the outer site plus an embedded Greenhouse form."""
    html = (ROOT / "fixtures" / "forms" / "indiecampers_greenhouse.html").read_text(encoding="utf-8")
    result = _read_html(html)
    inside = [f for f in result if f.frame]
    labels = [f.label for f in inside]
    assert [f.label for f in inside if f.type == "dropdown"][:2] == ["Country", "Location (City)"]
    assert "First Name" in labels and "Email" in labels and "Phone" in labels
    assert len(labels) == len(set(labels))  # no duplicates from helper boxes
    assert not any(label == "Select..." for label in labels)
    assert any(f.label == "Attach" and f.type == "file" for f in inside)  # the resume upload
