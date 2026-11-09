"""The form reader: look at a page and list what it asks, WITHOUT changing anything.

For every field on the page it returns a :class:`FormField`: the question
(label), the kind of input, whether it is required, and its options.

How the label is found (first match wins):
    1. a ``<label for=...>`` or a wrapping ``<label>``
    2. ``aria-labelledby`` / ``aria-label``
    3. the placeholder
    4. short text just before the input ("nearby text")
Radio buttons and checkboxes that belong together (one ``<fieldset>`` with a
``<legend>``, or the same ``name``) become ONE field whose options are the
choices. A field with no readable label keeps an empty label: it is reported as
"needs you" instead of being guessed.

The reader only reads. It never clicks, types or submits (CLAUDE.md rule 5).
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from typing import Any, Literal, get_args

from playwright.sync_api import Page, sync_playwright
from pydantic import BaseModel

from engine import safety
from engine.forms.browser import CDP_URL
from engine.settings import Settings

FieldType = Literal["text", "email", "tel", "url", "number", "date", "textarea", "select", "radio", "checkbox", "file"]

# Runs inside the page. Returns raw facts about each input; Python groups and cleans them.
# ``index`` is the element's position in this exact query, so the Phase 4 filler can find it again.
_EXTRACT_JS = r"""
() => {
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const textOf = id => { const el = id && document.getElementById(id); return el ? clean(el.innerText) : ''; };
  // aria-labelledby may list a name AND descriptions ("Photo", "Choose file"): the first non-empty one is the name.
  const byIds = v => (v || '').split(' ').map(textOf).find(t => t) || '';
  const labelOf = e => {
    if (e.id) { const l = document.querySelector('label[for="' + CSS.escape(e.id) + '"]'); const t = l && clean(l.innerText); if (t) return t; }
    const w = e.closest('label'); const wt = w && clean(w.innerText); if (wt) return wt;
    const lb = byIds(e.getAttribute('aria-labelledby')); if (lb) return lb;
    const al = clean(e.getAttribute('aria-label')); if (al) return al;
    const ph = clean(e.getAttribute('placeholder')); if (ph) return ph;
    let p = e;
    for (let i = 0; i < 3 && p; i++, p = p.parentElement) {
      if (['FORM', 'BODY', 'HTML', 'FIELDSET'].includes(p.tagName)) break;  // never look outside the field's own block
      const prev = p.previousElementSibling;
      if (prev) { const t = clean(prev.innerText); if (t && t.length <= 120) return t; }
    }
    return '';
  };
  const groupOf = e => {
    const g = e.closest('fieldset, [role=radiogroup], [role=group]');
    if (!g) return '';
    const lg = g.querySelector('legend'); if (lg) return clean(lg.innerText);
    return byIds(g.getAttribute('aria-labelledby')) || clean(g.getAttribute('aria-label'));
  };
  const SKIP = new Set(['hidden', 'submit', 'button', 'image', 'reset', 'password']);
  const shown = e => {
    if (e.type === 'file' || e.type === 'radio' || e.type === 'checkbox') return true;  // often visually hidden
    const st = getComputedStyle(e), r = e.getBoundingClientRect();
    return st.display !== 'none' && st.visibility !== 'hidden' && (r.width > 0 || r.height > 0);
  };
  return [...document.querySelectorAll('input, textarea, select')].map((e, index) => ({
    index, tag: e.tagName.toLowerCase(), type: (e.type || '').toLowerCase(), name: e.name || '',
    label: labelOf(e), group: groupOf(e),
    required: !!(e.required || e.getAttribute('aria-required') === 'true'),
    options: e.tagName === 'SELECT' ? [...e.options].filter(o => o.value !== '').map(o => clean(o.text)).filter(t => t) : [],
    skip: SKIP.has((e.type || '').toLowerCase()) || e.disabled || !shown(e),
  })).filter(r => !r.skip);
}
"""


class FormField(BaseModel):
    """One question on a form."""

    label: str  # the question; empty if the page gave no readable label
    type: FieldType
    required: bool = False
    options: list[str] = []  # choices for select / radio / checkbox groups
    name: str = ""  # the input's name attribute, if any
    indexes: list[int] = []  # positions of its input(s) on the page (the filler uses these)

    @property
    def needs_you(self) -> bool:
        """True if the page gave no readable label, so the bot cannot know what is asked."""
        return not self.label


def clean_label(raw: str) -> str:
    """Remove the required-star and "(Optional)" that sites add to labels."""
    text = re.sub(r"\(\s*optional\s*\)", "", raw, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip(" *\t")


def read_fields(page: Page) -> list[FormField]:
    """Read every field on ``page``. Pure reading: nothing on the page is changed."""
    raw: list[dict[str, Any]] = page.evaluate(_EXTRACT_JS)
    return build_fields(raw)


def build_fields(raw: list[dict[str, Any]]) -> list[FormField]:
    """Turn the page's raw input facts into clean :class:`FormField` items (testable without a browser)."""
    fields: list[FormField] = []
    groups: dict[tuple[str, str, str], FormField] = {}
    same_name = Counter((i["type"], i["name"]) for i in raw if i["name"])
    for item in raw:
        kind = "select" if item["tag"] == "select" else "textarea" if item["tag"] == "textarea" else item["type"] or "text"
        if kind not in get_args(FieldType):
            kind = "text"
        label = clean_label(item["label"])
        # Choices of one question: inside a <fieldset>/radiogroup, or several inputs sharing a name.
        # A lone checkbox ("I agree") is just its own field.
        shares_name = bool(item["name"]) and same_name[(item["type"], item["name"])] > 1
        if kind in ("radio", "checkbox") and (item["group"] or shares_name):
            # Choices of one question are merged into one field.
            key = (kind, item["name"], item["group"])
            question = clean_label(item["group"]) or item["name"]
            existing = groups.get(key)
            if existing is None:
                existing = FormField(label=question, type=kind, name=item["name"])  # type: ignore[arg-type]
                groups[key] = existing
                fields.append(existing)
            existing.options.append(label or f"option {len(existing.options) + 1}")
            existing.indexes.append(item["index"])
            existing.required = existing.required or item["required"]
            continue
        fields.append(
            FormField(
                label=label,
                type=kind,  # type: ignore[arg-type]
                required=item["required"],
                options=item["options"],
                name=item["name"],
                indexes=[item["index"]],
            )
        )
    return fields


def read_current_page(
    *, settings: Settings | None = None, conn: sqlite3.Connection | None = None
) -> tuple[str, list[FormField]]:
    """Read the page open in the bot's browser (start it with ``python -m engine.cli browser open``).

    Returns ``(url, fields)``. Calls ``safety.check("read", url)`` first and
    logs the read to ``action_log`` when ``conn`` is given.

    Raises:
        RuntimeError: the bot's browser is not running or has no web page open.
    """
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception as exc:
            raise RuntimeError("The bot's browser is not open. Run: python -m engine.cli browser open") from exc
        pages = [pg for ctx in browser.contexts for pg in ctx.pages if pg.url.startswith(("http", "file"))]
        if not pages:
            raise RuntimeError("No web page is open in the bot's browser.")
        visible = [pg for pg in pages if pg.evaluate("document.visibilityState") == "visible"]
        page = (visible or pages)[-1]
        safety.check("read", page.url, settings=settings)
        fields = read_fields(page)
        if conn is not None:
            safety.log_action(conn, "read", page.url, f"{len(fields)} fields")
        return page.url, fields
