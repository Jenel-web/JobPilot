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
