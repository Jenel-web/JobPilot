"""Tests for engine/forms/capture.py. Fake person only; no browser connection, no real site."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest
from playwright.sync_api import sync_playwright

from engine.db import connect, init_db
from engine.forms.capture import REDACTED, sanitize_html, sensitive_strings
from engine.forms.reader import read_fields
from engine.settings import ROOT

SAMPLE = (ROOT / "fixtures" / "forms" / "sample_form.html").read_text(encoding="utf-8")

DIRTY = """<html><head><script>var t='SECRET_TOKEN';</script><link rel="stylesheet" href="https://x.test/a.css"></head>
<body><div class="menu">Signed in as Fake Person (fake.person@example.com)</div>
<label for="a">First name</label><input id="a" type="text" value="Fake">
<label for="b">Phone</label><input id="b" type="tel" value="+63 900 111 2233">
<label for="c">About</label><textarea id="c">I live at 1 Fake Street</textarea>
<input type="hidden" name="csrf" value="SECRET_TOKEN">
<fieldset><legend>Hybrid?</legend><label><input type="radio" name="h" value="yes"> YES</label></fieldset>
<img src="https://cdn.test/me.png"><p>Call +63 917 555 0100 or mail someone@else.org</p></body></html>"""


@pytest.fixture()
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    init_db(connection)
    connection.execute(
        "INSERT INTO profile (id, full_name, email, phone, address) VALUES (1, 'Fake Person', "
        "'fake.person@example.com', '+63 900 111 2233', '1 Fake Street, Sample City')"
    )
    yield connection
    connection.close()


def test_sensitive_strings_come_from_the_profile(conn: sqlite3.Connection) -> None:
    found = sensitive_strings(conn)
    assert "Fake Person" in found and "fake.person@example.com" in found and "Fake" in found
    assert found[0] == max(found, key=len)  # longest first


def test_no_profile_means_no_secrets() -> None:
    empty = connect(":memory:")
    init_db(empty)
    assert sensitive_strings(empty) == []


def test_sanitize_removes_scripts_values_hidden_inputs_and_personal_data(conn: sqlite3.Connection) -> None:
    clean = sanitize_html(DIRTY, sensitive_strings(conn))
    for leaked in ("SECRET_TOKEN", "Fake Person", "fake.person", "900 111 2233", "1 Fake Street", "917 555 0100", "someone@else.org", "cdn.test", "x.test"):
        assert leaked not in clean, leaked
    assert REDACTED in clean
    assert "<script" not in clean and 'type="hidden"' not in clean


def test_sanitize_keeps_the_questions_and_choice_values(conn: sqlite3.Connection) -> None:
    clean = sanitize_html(DIRTY, sensitive_strings(conn))
    assert "First name" in clean and "Hybrid?" in clean and 'value="yes"' in clean


def test_a_sanitized_page_still_reads_the_same_fields() -> None:
    """Cleaning must not change what the reader sees."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(SAMPLE)
        before = [(f.label, f.type, f.options) for f in read_fields(page)]
        page.set_content(sanitize_html(SAMPLE))
        after = [(f.label, f.type, f.options) for f in read_fields(page)]
        browser.close()
    assert before == after and len(before) > 8


def test_frames_are_embedded_back_and_readable() -> None:
    """An iframe form must survive capture: it is saved inline and read the same way."""
    from engine.forms.capture import embed_frames

    inner = "<label for=a>First Name*</label><input id=a required>"
    saved = embed_frames("<html><body><p>Job post</p></body></html>", [inner])
    assert saved.count("<iframe") == 1 and saved.endswith("</body></html>")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(saved)
        page.wait_for_timeout(300)
        labels = [f.label for f in read_fields(page)]
        browser.close()
    assert labels == ["First Name"]


def test_ids_with_long_digit_runs_are_not_mistaken_for_phone_numbers() -> None:
    """Regression: 'question_38619146002' was rewritten to 'question_REDACTED', merging different fields."""
    html = '<input id="question_38619146002"><input id="question_38619147002"><p>Call +63 917 555 0100 or 0917-555-0100</p>'
    clean = sanitize_html(html)
    assert 'id="question_38619146002"' in clean and 'id="question_38619147002"' in clean
    assert "917" not in clean.split("<p>")[1]
