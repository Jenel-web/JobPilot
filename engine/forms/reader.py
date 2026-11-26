"""The form reader: look at a page and list what it asks, WITHOUT changing anything.

For every field on the page it returns a :class:`FormField`: the question
(label), the kind of input, whether it is required, and its options.

How the label is found (first match wins):
    1. a ``<label for=...>`` or a wrapping ``<label>``
    2. ``aria-labelledby`` / ``aria-label``
    3. the one ``<label>`` in the field's own small block (form libraries often break ``<label for>``)
    4. the placeholder
    5. short text just before the input ("nearby text")
Custom dropdowns built from ``<div>``s (no ``<select>``) are found by their class names and roles and read as ONE
``dropdown`` field with the options listed in the page (see ``CUSTOM_HELPERS_JS``).
Radio buttons and checkboxes that belong together (one ``<fieldset>`` with a
``<legend>``, or the same ``name``) become ONE field whose options are the
choices. Its question is the ``<legend>`` (or the group's aria label); with no
legend, the short text just before the choices (``questionOf`` in ``_EXTRACT_JS``),
and only if that is not found, the inputs' ``name``. A field with no readable
label keeps an empty label: it is reported as "needs you" instead of being guessed.

The reader only reads. It never clicks, types or submits (CLAUDE.md rule 5).
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Literal, get_args

from playwright.sync_api import Page, sync_playwright
from pydantic import BaseModel

from engine import safety
from engine.forms.browser import CDP_URL
from engine.settings import Settings

FieldType = Literal["text", "email", "tel", "url", "number", "date", "textarea", "select", "dropdown", "radio", "checkbox", "file", "unsupported"]
# "unsupported": a real question the bot cannot drive (a slider, a rich-text box, a toggle switch). It is REPORTED so the
# fill summary says "needs you" instead of skipping it silently; no position is saved, so nothing can ever touch it.

# How a CUSTOM dropdown is recognised (shared with the filler, which must find the same elements again).
# Many sites (Shopee, Element UI, Ant Design...) build dropdowns from <div>s instead of a <select>: a box you click,
# a hidden text input, and a list of option <div>s. These helpers find them by their class names and roles.
#   * a dropdown: an element whose class ends in "select", "dropdown" or "combobox" (or role=combobox, not an input),
#     that holds a text input or option elements and no real <select>. Date, time and language pickers are excluded.
#   * an option: role=option, or a class ending in "option" (or "menu-item", "list-item", "select-item"...).
# Only the OUTERMOST match counts, so one dropdown is one field. ``CUSTOM_HELPERS_JS`` defines ``findCustoms()``.
CUSTOM_HELPERS_JS = r"""
  const isShown = e => { const st = getComputedStyle(e), r = e.getBoundingClientRect(); return st.display !== 'none' && st.visibility !== 'hidden' && r.width > 0 && r.height > 0; };
  const SELECT_CLASS = /(^|[-_])(select|dropdown|combobox)$/i;
  const NOT_SELECT = /date|time|month|year|calendar|colou?r|language|lang-/i;
  const OPTION_CLASS = /(^|[-_])option$|(menu|list|select|dropdown)[-_]+item$/i;
  const isOption = e => e.getAttribute('role') === 'option' || [...e.classList].some(c => OPTION_CLASS.test(c));
  const looksCustom = e => {
    if (['INPUT', 'SELECT', 'TEXTAREA', 'OPTION'].includes(e.tagName)) return false;
    // Workday draws a dropdown as <button role="combobox">, its options in a list beside it (see listFor).
    // Any other button is an action, never a question. Whether it is safe to CLICK is the filler's call.
    if (e.tagName === 'BUTTON') return e.getAttribute('role') === 'combobox';
    const cls = [...e.classList];
    const byClass = cls.some(c => SELECT_CLASS.test(c)) && !cls.some(c => NOT_SELECT.test(c));
    const byRole = e.getAttribute('role') === 'combobox';
    if (!byClass && !byRole) return false;
    if (e.querySelector('select')) return false;  // a real <select> inside: that one is read instead
    // A box you can type into is showing (a phone widget, react-select's role=combobox input): the normal input
    // reading handles those. A custom dropdown's own search box is hidden until it opens, or read-only.
    if ([...e.querySelectorAll('input')].some(i => i.getAttribute('role') === 'combobox'
        || (!['hidden', 'checkbox', 'radio'].includes(i.type) && !i.readOnly && isShown(i)))) return false;
    return byRole || !!e.querySelector('input') || [...e.querySelectorAll('*')].some(isOption);
  };
  const findCustoms = () => {
    const all = [...document.querySelectorAll('div, span, section, button')].filter(looksCustom);
    return all.filter(e => !all.some(o => o !== e && o.contains(e)));
  };
  // The option list a dropdown box controls when the options are NOT inside it: the list its aria-controls /
  // aria-owns points to, else a role=listbox right after it (Workday). null = none of these.
  const listFor = box => {
    const id = box.getAttribute('aria-controls') || box.getAttribute('aria-owns');
    const byId = id && document.getElementById(id);
    if (byId) return byId;
    const next = box.nextElementSibling;
    return next && next.getAttribute('role') === 'listbox' ? next : null;
  };
"""

# Runs inside the page. Returns raw facts about each input; Python groups and cleans them.
# ``index`` is the element's position in this exact query, so the Phase 4 filler can find it again.
# A custom dropdown gets ``cindex`` instead: its position in ``findCustoms()``.
_EXTRACT_JS = "() => {\n" + CUSTOM_HELPERS_JS + r"""
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const textOf = id => { const el = id && document.getElementById(id); return el ? clean(el.innerText) : ''; };
  // aria-labelledby may list a name AND descriptions ("Photo", "Choose file"): the first non-empty one is the name.
  const byIds = v => (v || '').split(' ').map(textOf).find(t => t) || '';
  const CONTROL = 'input:not([type=hidden]), select, textarea';
  // The ONE <label> in the small block around the field. Form libraries often break <label for> (the input has
  // no matching id), but the label still sits in the field's own block. Two or more labels = we left the block.
  const blockLabelOf = e => {
    let p = e.parentElement;
    for (let i = 0; i < 6 && p; i++, p = p.parentElement) {
      if (['FORM', 'BODY', 'HTML', 'FIELDSET'].includes(p.tagName)) break;
      const labels = [...p.querySelectorAll('label')].filter(l => {
        if (l.querySelector(CONTROL)) return false;  // a label wrapping a box (one radio choice) is not the question
        const target = l.htmlFor && document.getElementById(l.htmlFor);
        if (target && target !== e && target.matches(CONTROL)) return false;  // it names another field
        return !!clean(l.innerText);
      });
      // The first line only: some labels carry a help sentence under the question ("Resume*" + "We will read it...").
      if (labels.length === 1) return (labels[0].innerText.split(/\n/).map(t => t.trim()).find(Boolean)) || '';
      if (labels.length > 1) return '';
    }
    return '';
  };
  const labelOf = e => {
    if (e.id) { const l = document.querySelector('label[for="' + CSS.escape(e.id) + '"]'); const t = l && clean(l.innerText); if (t) return t; }
    const w = e.closest('label'); const wt = w && clean(w.innerText); if (wt) return wt;
    const lb = byIds(e.getAttribute('aria-labelledby')); if (lb) return lb;
    const al = clean(e.getAttribute('aria-label')); if (al) return al;
    const bl = clean(blockLabelOf(e)); if (bl) return bl;
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
  // The question of a choice group with NO <legend> (Lever, Google Forms, Greenhouse without a fieldset): the text
  // just before the choices. Radios always; checkboxes only when 2+ share a name (a lone "I agree" box is its own
  // question). Starting at the smallest block holding every choice, look at what comes BEFORE the choices, nearest
  // first, up to 4 levels up. The first block with no field in it and short text (200 chars max) is the question.
  // Reaching a block that holds a field means we walked into ANOTHER question: stop and return '' (the old name
  // fallback is safer than a section heading further up). Found nothing = '' too.
  const questionOf = e => {
    if (!e.name || (e.type !== 'radio' && e.type !== 'checkbox')) return '';
    const peers = [...document.querySelectorAll('input[type="' + e.type + '"][name="' + CSS.escape(e.name) + '"]')]
      .filter(p => p.form === e.form);
    if (!peers.length || (e.type === 'checkbox' && peers.length < 2)) return '';
    const first = peers[0];
    let wrap = first.parentElement;
    while (wrap && !peers.every(p => wrap.contains(p))) wrap = wrap.parentElement;
    const look = el => {  // the question text, '' = nothing here (keep looking), null = another field (stop)
      if (el.matches(CONTROL) || el.querySelector(CONTROL)) return null;
      const t = clean(el.innerText);
      return t && t.length <= 200 ? t : '';
    };
    const STOP = ['FORM', 'BODY', 'HTML'];
    for (let level = 0; level < 4 && wrap && !STOP.includes(wrap.tagName); level++) {
      const holder = [...wrap.children].find(c => c.contains(first));
      for (let c = holder && holder.previousElementSibling; c; c = c.previousElementSibling) {
        const t = look(c);
        if (t === null) return '';
        if (t) return t;
      }
      if (level === 3 || STOP.includes((wrap.parentElement || {}).tagName)) break;  // keep this wrap for the last try
      wrap = wrap.parentElement;
    }
    const prev = wrap && !STOP.includes(wrap.tagName) && wrap.previousElementSibling;  // last try: the block just before
    return (prev && look(prev)) || '';
  };
  const SKIP = new Set(['hidden', 'submit', 'button', 'image', 'reset', 'password', 'search']);
  const shown = e => {
    if (e.type === 'file' || e.type === 'radio' || e.type === 'checkbox') return true;  // often visually hidden
    return isShown(e);
  };
  const customs = findCustoms();
  const inCustom = e => customs.some(c => c.contains(e));
  const entries = [];
  [...document.querySelectorAll('input, textarea, select')].forEach((e, index) => {
    const type = (e.type || '').toLowerCase();
    if (SKIP.has(type) || e.disabled || !shown(e) || inCustom(e)) return;
    entries.push({node: e, item: {
      index, cindex: -1, tag: e.tagName.toLowerCase(), type, name: e.name || '', role: e.getAttribute('role') || '',
      bare: !(e.id || e.name || e.getAttribute('aria-label') || e.getAttribute('aria-labelledby') || e.getAttribute('placeholder')),
      label: labelOf(e), group: groupOf(e) || questionOf(e),
      required: !!(e.required || e.getAttribute('aria-required') === 'true') || /\*\s*$/.test(labelOf(e)),
      options: e.tagName === 'SELECT' ? [...e.options].filter(o => o.value !== '').map(o => clean(o.text)).filter(t => t) : [],
      autocomplete: clean(e.getAttribute('autocomplete')).toLowerCase(), placeholder: clean(e.getAttribute('placeholder')),
      maxLength: e.maxLength > 0 ? e.maxLength : 0, pattern: e.getAttribute('pattern') || '',
    }});
  });
  customs.forEach((c, cindex) => {
    if (!isShown(c)) return;
    const options = [];
    const collect = root => {
      for (const o of root.querySelectorAll('*')) {
        if (!isOption(o) || o.closest('button, a, [role=button]')) continue;  // a button in a list is an action, not a choice
        const t = clean(o.innerText || o.textContent);
        if (t && !options.includes(t)) options.push(t);
        if (options.length >= 1000) break;
      }
    };
    collect(c);
    if (!options.length && listFor(c)) collect(listFor(c));  // options kept outside the box (Workday)
    const ph = clean((c.querySelector('[class*=placeholder]') || {}).innerText)
      || clean([...c.querySelectorAll('input')].map(i => i.getAttribute('placeholder')).find(Boolean));
    const label = labelOf(c);
    const classes = [c, ...c.querySelectorAll('[class]')].slice(0, 40).map(x => typeof x.className === 'string' ? x.className : '').join(' ');
    entries.push({node: c, item: {
      index: -1, cindex, tag: 'div', type: 'dropdown', name: '', role: c.getAttribute('role') || '', bare: false,
      label, group: '', options, placeholder: ph, autocomplete: '', maxLength: 0, pattern: '',
      required: /\*\s*$/.test(clean(label)) || c.getAttribute('aria-required') === 'true',
      multi: /(^|[-_\s])(multiple|multi|tags)([-_\s]|$)/i.test(classes) || c.getAttribute('aria-multiselectable') === 'true'
        || /select up to|one or more|all that apply/i.test(ph),
      maxChoices: parseInt(((ph + ' ' + label).match(/up to (\d+)/i) || [])[1] || '0', 10),
    }});
  });
  // Controls the bot cannot drive: report them (type "unsupported") so they are never skipped silently. Only the
  // outermost one counts (a rich-text editor holds many editable blocks). A plain button, link or menu never has one
  // of these roles, so it is never reported; a toggle <button role="switch"> is (it is a question).
  const UNSUPPORTED_ROLES = ['slider', 'spinbutton', 'switch', 'textbox'];
  const isUnsupported = e => {
    if (['INPUT', 'SELECT', 'TEXTAREA', 'OPTION'].includes(e.tagName)) return false;  // real fields are read above
    const role = e.getAttribute('role') || '';
    const ce = e.getAttribute('contenteditable');
    const editable = ce !== null && ce.toLowerCase() !== 'false';
    if (!UNSUPPORTED_ROLES.includes(role) && !editable) return false;
    return true;
  };
  [...document.querySelectorAll('[role], [contenteditable]')].forEach(e => {
    if (!isUnsupported(e) || !isShown(e) || inCustom(e) || e.getAttribute('aria-disabled') === 'true') return;
    if (e.parentElement && e.parentElement.closest('button, a, [role=button]')) return;
    for (let p = e.parentElement; p; p = p.parentElement) if (isUnsupported(p)) return;  // inside another one: outermost only
    const label = labelOf(e);
    entries.push({node: e, item: {
      index: -1, cindex: -1, tag: e.tagName.toLowerCase(), type: 'unsupported', name: '', role: e.getAttribute('role') || '',
      bare: false, label, group: '', options: [], autocomplete: '', maxLength: 0, pattern: '',
      placeholder: clean(e.getAttribute('aria-placeholder') || e.getAttribute('data-placeholder')),
      required: e.getAttribute('aria-required') === 'true' || /\*\s*$/.test(label),
    }});
  });
  entries.sort((a, b) => (a.node.compareDocumentPosition(b.node) & Node.DOCUMENT_POSITION_FOLLOWING) ? -1 : 1);
  return entries.map(x => x.item);
}
"""


class FormField(BaseModel):
    """One question on a form."""

    label: str  # the question; empty if the page gave no readable label
    type: FieldType
    required: bool = False
    options: list[str] = []  # choices for select / radio / checkbox groups
    name: str = ""  # the input's name attribute, if any
    indexes: list[int] = []  # positions of its input(s) in its frame (the filler uses these)
    custom_index: int = -1  # a custom (<div>-built) dropdown: its position in ``findCustoms()``; -1 = not one
    multi: bool = False  # a custom dropdown that takes several choices (e.g. "Select up to 8 skills")
    max_choices: int = 0  # how many choices it takes, when the page says ("up to 8"); 0 = not said
    frame: str = ""  # address of the embedded frame it lives in; empty = the outer page
    frame_number: int = 0  # position of that frame in ``page.frames`` (0 = outer page). Needed because several frames can share one address (about:srcdoc)
    # Hints the page gives about the expected value (used to recognise personal fields
    # and to pick a phone number format). Empty / 0 when the page gives none.
    autocomplete: str = ""  # e.g. "given-name", "email", "tel-national", "address-level2"
    placeholder: str = ""  # grey example text, e.g. "09XX XXX XXXX"
    max_length: int = 0
    pattern: str = ""  # a regular expression the page checks the value against

    @property
    def needs_you(self) -> bool:
        """True if the page gave no readable label, so the bot cannot know what is asked."""
        return not self.label


def clean_label(raw: str) -> str:
    """Remove the required-star and "(Optional)" that sites add to labels."""
    text = re.sub(r"\(\s*optional\s*\)", "", raw, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip(" *\t")


# Embedded frames that are never application forms (cookie banners, CAPTCHA, ad and analytics widgets).
_NOISE_FRAME_HOSTS = (
    "recaptcha", "hcaptcha", "usercentrics", "cookiebot", "onetrust", "doubleclick",
    "googletagmanager", "facebook.com", "googleapis.com/static", "youtube.com", "stripe.com",
)


def read_fields(page: Page) -> list[FormField]:
    """Read every field on ``page``, including forms embedded in frames. Pure reading.

    Many career sites show their own page and embed the real application form from
    another site (Greenhouse, Lever, Workable...) in an ``<iframe>``. Looking only
    at the outer page would miss the form, so every frame is read. Each field
    remembers which frame it came from (``FormField.frame``; empty = the outer page).
    """
    fields: list[FormField] = []
    for number, frame in enumerate(page.frames):
        is_main = frame == page.main_frame
        if not is_main and any(host in frame.url.lower() for host in _NOISE_FRAME_HOSTS):
            continue
        try:
            raw: list[dict[str, Any]] = frame.evaluate(_EXTRACT_JS)
        except Exception:  # frame was removed or is still loading: skip it, keep the rest
            continue
        for field in build_fields(raw):
            field.frame = "" if is_main else frame.url
            field.frame_number = 0 if is_main else number
            fields.append(field)
    return fields


def build_fields(raw: list[dict[str, Any]]) -> list[FormField]:
    """Turn the page's raw input facts into clean :class:`FormField` items (testable without a browser)."""
    fields: list[FormField] = []
    groups: dict[tuple[str, str, str], FormField] = {}
    same_name = Counter((i["type"], i["name"]) for i in raw if i["name"])
    previous: dict[str, Any] | None = None
    for item in raw:
        if item.get("cindex", -1) >= 0:  # a <div>-built dropdown: options were read from its option elements
            previous = item
            fields.append(
                FormField(
                    label=clean_label(item["label"]),
                    type="dropdown",
                    required=item["required"],
                    options=item["options"],
                    custom_index=item["cindex"],
                    multi=bool(item.get("multi")),
                    max_choices=int(item.get("maxChoices") or 0),
                    placeholder=item.get("placeholder", ""),
                )
            )
            continue
        if item.get("type") == "unsupported":  # reported only: no index, so the filler can never touch it
            previous = item
            fields.append(FormField(label=clean_label(item["label"]), type="unsupported", required=item["required"],
                                    placeholder=item.get("placeholder", "")))
            continue
        # Custom dropdowns (react-select and similar) are two inputs: the real question
        # (role=combobox) plus a bare helper box right after it. Keep only the real one.
        helper = previous is not None and previous.get("role") == "combobox" and item.get("bare") and item["tag"] == "input"
        previous = item
        if helper:
            continue
        kind = "dropdown" if item.get("role") == "combobox" and item["tag"] == "input" else "select" if item["tag"] == "select" else "textarea" if item["tag"] == "textarea" else item["type"] or "text"
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
                autocomplete=item.get("autocomplete", ""),
                placeholder=item.get("placeholder", ""),
                max_length=item.get("maxLength", 0) or 0,
                pattern=item.get("pattern", ""),
            )
        )
    return fields


def read_fixture(path: Path) -> list[FormField]:
    """Read the fields of a saved page (``fixtures/forms/*.html``) in a throwaway headless browser.

    Offline and read-only: the HTML is loaded into a blank page, so no site is contacted
    and the bot's own browser is not needed.

    Raises:
        OSError: the file cannot be read.
    """
    html = path.read_text(encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html)
            page.wait_for_timeout(300)  # let scripts on the saved page build their fields
            return read_fields(page)
        finally:
            browser.close()


def find_current_page(browser: Any) -> Page:
    """Pick the page you are looking at in the bot's browser (the visible web page).

    Raises:
        RuntimeError: no web page is open.
    """
    pages = [pg for ctx in browser.contexts for pg in ctx.pages if pg.url.startswith(("http", "file"))]
    if not pages:
        raise RuntimeError("No web page is open in the bot's browser.")
    visible = [pg for pg in pages if pg.evaluate("document.visibilityState") == "visible"]
    return (visible or pages)[-1]


def connect_to_bot_browser(playwright: Any) -> Any:
    """Attach to the already-open bot browser (see ``browser.py``). Does not start a new one."""
    try:
        return playwright.chromium.connect_over_cdp(CDP_URL)
    except Exception as exc:
        raise RuntimeError("The bot's browser is not open. Run: python -m engine.cli browser open") from exc


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
        page = find_current_page(connect_to_bot_browser(p))
        safety.check("read", page.url, settings=settings)
        fields = read_fields(page)
        if conn is not None:
            safety.log_action(conn, "read", page.url, f"{len(fields)} fields")
        return page.url, fields
