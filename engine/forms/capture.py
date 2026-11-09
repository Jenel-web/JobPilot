"""Save the page open in the bot's browser as an offline test file, with personal data removed.

Why: tests must never touch real websites (CLAUDE.md). A saved copy of a real
form lets the reader be tested offline, and a site redesign can't break the tests.

What is removed before saving (``sanitize_html``):
    * all <script>, <link>, <iframe> tags (tracking, tokens, network calls)
    * hidden inputs, and the typed value of every text box and textarea
    * every absolute web address in src / srcset / href attributes
    * your name, email, phone and address (read from the profile table), plus
      anything that looks like an email address or phone number
The questions, labels and options stay, because those are what we test.
"""

from __future__ import annotations

import html as htmllib
import re
import sqlite3
from pathlib import Path

from playwright.sync_api import sync_playwright

from engine import safety
from engine.forms.reader import _NOISE_FRAME_HOSTS, connect_to_bot_browser, find_current_page
from engine.settings import ROOT, Settings

FIXTURES_DIR = ROOT / "fixtures" / "forms"
REDACTED = "REDACTED"
_KEEP_VALUE_TYPES = ("radio", "checkbox", "submit", "button")
_FLAGS = re.IGNORECASE | re.DOTALL
# Phone-like text: "+63 917 555 0100" or "0917-555-0100". Plain digit runs ("38619146002") and digits glued to
# words ("question_38619146002") are NOT phone numbers; they are ids, and changing them would break the page.
_PHONE_PATTERN = r"(?<![\w-])(?:\+\d[\d\s().-]{7,}\d|\d{2,4}[\s().-]\d[\d\s().-]{5,}\d)(?![\w-])"


def sensitive_strings(conn: sqlite3.Connection) -> list[str]:
    """Strings from your profile that must never appear in a saved page (longest first)."""
    row = conn.execute("SELECT full_name, email, phone, address FROM profile WHERE id = 1").fetchone()
    if row is None:
        return []
    name, email, phone, address = (row[k] or "" for k in ("full_name", "email", "phone", "address"))
    values = [v.strip() for v in (name, email, phone, address) if v.strip()]
    values += [part for part in re.split(r"[\s,]+", name) if len(part) >= 3]
    values += [part.strip() for part in address.split(",") if len(part.strip()) >= 4]
    digits = re.sub(r"\D", "", phone)
    if len(digits) >= 7:
        values.append(digits[-10:])
    return sorted(set(values), key=len, reverse=True)


def sanitize_html(html: str, secrets: list[str] | None = None) -> str:
    """Return ``html`` with scripts, typed values and personal data removed (see module docstring)."""
    out = re.sub(r"<script\b.*?</script\s*>", "", html, flags=_FLAGS)
    out = re.sub(r"<iframe\b.*?</iframe\s*>", "", out, flags=_FLAGS)
    out = re.sub(r"<link\b[^>]*>", "", out, flags=_FLAGS)
    out = re.sub(r"<input\b[^>]*\btype=[\"']?hidden[\"']?[^>]*>", "", out, flags=_FLAGS)
    out = re.sub(r"(<textarea\b[^>]*>).*?(</textarea\s*>)", r"\1\2", out, flags=_FLAGS)
    out = re.sub(r"<input\b[^>]*>", _strip_typed_value, out, flags=_FLAGS)
    out = re.sub(r"\s(?:src|srcset|href)=\"https?://[^\"]*\"", "", out, flags=_FLAGS)
    for secret in secrets or []:
        out = re.sub(re.escape(secret), REDACTED, out, flags=_FLAGS)
    out = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", f"{REDACTED}@example.com", out)
    return re.sub(_PHONE_PATTERN, REDACTED, out)


def _frame_contents(page) -> list[str]:  # type: ignore[no-untyped-def]
    """HTML of the embedded frames that may hold a form (skips cookie banners, CAPTCHA and ads)."""
    contents: list[str] = []
    for frame in page.frames:
        if frame == page.main_frame or any(host in frame.url.lower() for host in _NOISE_FRAME_HOSTS):
            continue
        try:
            contents.append(frame.content())
        except Exception:  # frame went away: skip it
            continue
    return contents


def embed_frames(main_html: str, frames_html: list[str]) -> str:
    """Put each frame's page back inside the saved page as ``<iframe srcdoc=...>``.

    The saved file then holds the whole form in ONE file, and the reader finds it the
    same way it finds the live iframe.
    """
    embedded = "".join(f'<iframe srcdoc="{htmllib.escape(inner, quote=True)}"></iframe>' for inner in frames_html)
    if "</body>" in main_html.lower():
        index = main_html.lower().rindex("</body>")
        return main_html[:index] + embedded + main_html[index:]
    return main_html + embedded


def _strip_typed_value(match: re.Match[str]) -> str:
    """Drop ``value="..."`` from text-like inputs (keep it for radios, checkboxes and buttons)."""
    tag = match.group(0)
    kind = re.search(r"\btype=[\"']?(\w+)", tag, flags=re.IGNORECASE)
    if kind and kind.group(1).lower() in _KEEP_VALUE_TYPES:
        return tag
    return re.sub(r"\svalue=(\"[^\"]*\"|'[^']*'|\S+)", "", tag, flags=re.IGNORECASE)


def capture_current_page(
    name: str, *, conn: sqlite3.Connection, settings: Settings | None = None, folder: Path = FIXTURES_DIR
) -> Path:
    """Save the open page as ``fixtures/forms/<name>.html`` (sanitized) and return the path.

    Raises:
        ValueError: ``name`` is not letters, digits, ``_`` or ``-``.
        RuntimeError: the bot's browser is not open.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", name):
        raise ValueError("Use only letters, digits, _ and - in the name")
    with sync_playwright() as p:
        page = find_current_page(connect_to_bot_browser(p))
        safety.check("read", page.url, settings=settings)
        html = page.content()
        url = page.url
        frame_pages = _frame_contents(page)
    secrets = sensitive_strings(conn)
    clean = embed_frames(sanitize_html(html, secrets), [sanitize_html(f, secrets) for f in frame_pages])
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.html"
    path.write_text(clean, encoding="utf-8")
    safety.log_action(conn, "read", url, f"captured page as {path.name}")
    return path
