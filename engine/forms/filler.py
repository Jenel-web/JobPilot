"""The form filler: type the answer engine's decisions into the page, then STOP.

The reader (``reader.py``) says what the page asks, the answer engine (``answers.py``)
decides every value, and this module puts the values into the page.

What it does, field by field (in page order):
    1. ``safety.check("fill")`` (or ``"upload"``), then a random 1-4 s pause so it types like a person.
    2. Fills the field by its type: text, select, radio, checkbox, date, resume upload, and custom dropdowns
       (click the box, search when it has a search box, click the matching option, check it was taken).
    3. Writes one ``action_log`` row (the label and the outcome, never the value).
    4. A guess (``flagged``) gets a solid outline and a small tag in the page; a field it could
       not fill gets a dashed outline and a tag that says why. Known answers stay plain.

What it NEVER does (CLAUDE.md rule 5):
    * click Submit, Apply, Next or any other button. It only touches inputs, selects and
      textareas, plus the box and the options of a custom dropdown the reader found. It checks each
      element is the kind it expects right before using it, because the page may have changed since the
      reader looked at it. A ``<button>``, link or ``role=button`` is never clicked, even inside a dropdown.
    * navigate, retry, or move to the next step of a multi-step form. You press Fill again.

How a field is found again: the reader saved ``frame`` (which embedded frame) and ``indexes``
(the position of each input in the query ``input, textarea, select``). ``_FIELDS`` below must
stay the same query as in ``reader._EXTRACT_JS``.
"""

from __future__ import annotations

import random
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Literal

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import ElementHandle, Frame, Locator, Page

from engine import safety
from engine.forms.answers import FieldAnswer, _option_key, pick_option
from engine.forms.reader import CUSTOM_HELPERS_JS, FormField
from engine.settings import ROOT, Settings

DELAY_RANGE = (1.0, 4.0)  # seconds between actions (CLAUDE.md: random human-like delays)
ACTION_TIMEOUT_MS = 5000  # a field that does not react in 5 s is reported, not waited on forever
_FIELDS = "input, textarea, select"  # the SAME query the reader used to number the inputs
_NEVER_TOUCH = ("button", "submit", "image", "reset", "hidden", "password")
_DATE_FORMATS = ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y", "%Y/%m/%d")
OPEN_WAIT_MS = 300  # after opening a custom dropdown, before its options are read
SEARCH_WAIT_MS = 700  # after typing into a dropdown's search box (sites filter or fetch as you type)
MULTI_LIMIT = 8  # most choices put into a multi-choice dropdown when the page does not say ("up to 8")
MULTI_TRIES = 20  # most values tried in one multi-choice dropdown (each one is searched for)

# Custom dropdowns. The same finder as the reader (``CUSTOM_HELPERS_JS``), so ``custom_index`` points at the same box.
_FIND_CUSTOM_JS = "(cindex) => {\n" + CUSTOM_HELPERS_JS + "\n  return findCustoms()[cindex] || null;\n}"
_COMBO_BOX_JS = r"""
(input) => input.closest('[class*=container], [class*=select], [class*=dropdown], [class*=combobox]') || input.parentElement
"""
# The options you can see right now: inside the box first, then a list the box points to (aria-controls / aria-owns),
# then any open role=option list on the page (many libraries draw the menu at the end of <body>).
_OPTIONS_JS = "(box) => {\n" + CUSTOM_HELPERS_JS + r"""
  const pressable = e => e.closest('button, a, [role=button]');
  const usable = e => isOption(e) && isShown(e) && !pressable(e) && e.getAttribute('aria-disabled') !== 'true';
  let opts = [...box.querySelectorAll('*')].filter(usable);
  if (!opts.length) {
    for (const el of [box, ...box.querySelectorAll('[aria-controls], [aria-owns]')]) {
      const id = el.getAttribute('aria-controls') || el.getAttribute('aria-owns');
      const list = id && document.getElementById(id);
      if (list) opts.push(...[...list.querySelectorAll('*')].filter(usable));
    }
  }
  if (!opts.length && listFor(box)) opts = [...listFor(box).querySelectorAll('*')].filter(usable);  // a list beside the box (Workday)
  if (!opts.length) opts = [...document.querySelectorAll('[role=option]')].filter(usable);
  return opts.filter(o => !opts.some(other => other !== o && o.contains(other)));  // the innermost option element
}
"""
# What the box shows as its value: its text without the option list and the inputs.
_SHOWN_JS = "(box) => {\n" + CUSTOM_HELPERS_JS + r"""
  const copy = box.cloneNode(true);
  for (const e of [...copy.querySelectorAll('*')]) if (isOption(e) || e.tagName === 'INPUT') e.remove();
  return (copy.textContent || '').replace(/\s+/g, ' ').trim();
}
"""
# The part you click to open it, and its search box (only once it is open and showing).
_TRIGGER_JS = r"""
(box) => box.querySelector('[role=combobox], [class*=selector], [class*=trigger], [class*=control], [tabindex]') || box
"""
# May this element be clicked to open or close a dropdown? A <button> (or link) is only ever clicked when it is a
# dropdown box that CANNOT submit: <button role="combobox" type="button">. A button with no type, or type=submit,
# submits its form when clicked, so it is never touched (CLAUDE.md rule 5). Everything else (a div, a span) is fine.
_SAFE_TRIGGER_JS = r"""
(e) => {
  const PRESS_TYPES = ['submit', 'button', 'image', 'reset'];
  const pressable = e.closest('button, a, [role=button]') || (e.tagName === 'INPUT' && PRESS_TYPES.includes(e.type) ? e : null);
  if (!pressable) return true;
  return pressable.tagName === 'BUTTON' && pressable.getAttribute('role') === 'combobox'
    && (pressable.getAttribute('type') || '').trim().toLowerCase() === 'button';
}
"""
_SEARCH_JS = r"""
(box) => [...box.querySelectorAll('input')].find(i => !['hidden', 'checkbox', 'radio', 'file'].includes(i.type) && !i.readOnly
  && i.getBoundingClientRect().width > 0 && getComputedStyle(i).visibility !== 'hidden') || null
"""

_YES = {"yes", "y", "true", "agree", "accept", "accepted", "checked", "ok", "1"}
_NO = {"no", "n", "false", "unchecked", "decline", "0"}

Outcome = Literal["filled", "needs_you", "failed"]


class _CannotFill(Exception):
    """The answer cannot be put into this field (no matching option, unreadable date...). The field stays empty."""


class _PageChanged(Exception):
    """The element at the saved position is not the kind of field the reader saw. Nothing is touched."""


@dataclass(frozen=True)
class FieldResult:
    """What happened to one field."""

    label: str
    type: str
    outcome: Outcome
    note: str = ""
    flagged: bool = False  # True = it was outlined in the page for you to check


@dataclass(frozen=True)
class ResumeFile:
    """The resume to upload: the file on disk, and the formal name the employer will see."""

    path: Path
    upload_name: str


@dataclass
class FillReport:
    """Everything the review step needs after a fill."""

    url: str
    results: list[FieldResult] = field(default_factory=list)
    screenshot_path: Path | None = None

    @property
    def filled(self) -> int:
        return sum(r.outcome == "filled" for r in self.results)

    @property
    def needs_you(self) -> int:
        return sum(r.outcome == "needs_you" for r in self.results)

    @property
    def failed(self) -> int:
        return sum(r.outcome == "failed" for r in self.results)

    @property
    def flagged(self) -> int:
        """Fields outlined in the page: guesses plus everything you must do by hand."""
        return sum(r.flagged for r in self.results)

    def summary(self) -> str:
        return f"Filled {self.filled} of {len(self.results)} fields; {self.flagged} need a look ({self.needs_you} left empty, {self.failed} failed)"


# ---- small helpers -------------------------------------------------------------------------


def to_iso_date(text: str) -> str | None:
    """``"March 5, 2027"`` -> ``"2027-03-05"``; ``None`` if it is not clearly a date.

    Slash dates like 03/05/2027 are refused on purpose: nobody can tell month from day,
    and a wrong date on an application is worse than an empty box.
    """
    cleaned = " ".join(text.replace(",", ", ").split()).replace(" ,", ",")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _stance(value: str) -> bool | None:
    """Read a saved answer as tick (True) / leave unticked (False) / unclear (None), by its first word."""
    words = re.findall(r"[a-z0-9]+", value.lower())
    if not words:
        return None
    first = words[0]
    if first in _YES:
        return True
    if first in _NO:
        return False
    return None


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


@cache
def amber_colors() -> dict[str, str]:
    """The flag colours, read from ``design/tokens.css`` so the page tags match the dashboard (fallbacks if unreadable)."""
    wanted = {"line": ("amber", "#B45309"), "text": ("amber-text", "#8A4A07"), "bg": ("amber-bg", "#FDF3DC"), "border": ("amber-border", "#E9CF95")}
    try:
        css = (ROOT / "design" / "tokens.css").read_text(encoding="utf-8")
    except OSError:
        css = ""
    colors: dict[str, str] = {}
    for key, (token, fallback) in wanted.items():
        found = re.search(rf"--jp-{re.escape(token)}:\s*(#[0-9A-Fa-f]{{3,8}})", css)
        colors[key] = found.group(1) if found else fallback
    return colors


def load_resume_file(conn: sqlite3.Connection, resume_id: str) -> ResumeFile:
    """The saved resume ``A`` or ``B`` plus the formal upload name from your profile.

    Raises:
        ValueError: nothing is loaded yet (run ``python -m engine.cli load``) or the file is missing.
    """
    row = conn.execute("SELECT file_path FROM resumes WHERE id = ?", (resume_id.upper(),)).fetchone()
    profile = conn.execute("SELECT upload_name FROM profile LIMIT 1").fetchone()
    if row is None or profile is None:
        raise ValueError(f"Resume {resume_id!r} is not loaded. Run: python -m engine.cli load")
    path = Path(row["file_path"])
    path = path if path.is_absolute() else ROOT / path
    if not path.is_file():
        raise ValueError(f"The file for resume {resume_id.upper()} is missing: {path}")
    return ResumeFile(path, profile["upload_name"] or path.name)


# Runs in the page. Outlines the field and puts a small tag in an overlay (a shadow DOM, pointer-events off),
# so nothing is added to the site's form and the overlay can never be clicked or block a button.
_HIGHLIGHT_JS = r"""
(el, a) => {
  const area = n => { const r = n.getBoundingClientRect(); return r.width * r.height; };
  const BIG = ['BODY', 'FORM', 'HTML'];  // never outline the whole page or form
  const group = el.closest('fieldset, [role=radiogroup], [role=group]');
  const label = (el.id && document.querySelector('label[for="' + CSS.escape(el.id) + '"]')) || el.closest('label');
  let target = el;
  if (a.group && group) target = group;
  else if (area(el) === 0 && label) target = label;  // a visually hidden input: outline what you can see
  while (target && area(target) === 0 && !BIG.includes(target.tagName)) target = target.parentElement;
  if (!target || area(target) === 0 || BIG.includes(target.tagName)) return false;
  target.style.outline = '2px ' + (a.dashed ? 'dashed' : 'solid') + ' ' + a.line;
  target.style.outlineOffset = '2px';
  let host = document.getElementById('jobpilot-flags');
  if (!host) {
    host = document.createElement('div');
    host.id = 'jobpilot-flags';
    host.style.cssText = 'position:absolute;top:0;left:0;width:0;height:0;z-index:2147483647;pointer-events:none';
    const root = host.attachShadow({mode: 'open'});
    root.innerHTML = '<style>.tag,.why{position:absolute;font:600 12px/1.4 system-ui,sans-serif;border-radius:4px;' +
      'width:max-content;max-width:min(420px,calc(100vw - 16px))}' +
      '.tag{background:' + a.bg + ';color:' + a.text + ';border:1px solid ' + a.border + ';padding:2px 8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
      '.tag::before{content:"▲ ";font-size:10px;color:' + a.line + '}' +
      '.why{font-weight:400;color:' + a.text + ';background:' + a.bg + ';padding:1px 6px}</style>';
    document.documentElement.appendChild(host);
    window.__jpFlags = [];
    window.__jpPlace = () => {
      const right = document.documentElement.clientWidth + scrollX;  // keep every note inside the visible width
      const inside = (x, width) => Math.max(scrollX + 4, Math.min(x, right - width - 4));
      for (const f of window.__jpFlags) {
        const r = f.target.getBoundingClientRect();
        f.tag.style.left = inside(r.right + scrollX - f.tag.offsetWidth, f.tag.offsetWidth) + 'px';
        f.tag.style.top = (r.top + scrollY - f.tag.offsetHeight - 4) + 'px';
        f.why.style.left = inside(r.left + scrollX, f.why.offsetWidth) + 'px';
        f.why.style.top = (r.bottom + scrollY + 4) + 'px';
      }
    };
    addEventListener('resize', window.__jpPlace);
    new ResizeObserver(window.__jpPlace).observe(document.body);
  }
  const tag = document.createElement('div'); tag.className = 'tag'; tag.textContent = a.tag;
  const why = document.createElement('div'); why.className = 'why'; why.textContent = a.why;
  host.shadowRoot.append(tag, why);
  window.__jpFlags.push({target, tag, why});
  window.__jpPlace();
  return true;
}
"""


class _Filler:
    """Holds what one fill needs, so the per-field methods stay short."""

    def __init__(
        self,
        page: Page,
        conn: sqlite3.Connection | None,
        resume: ResumeFile | None,
        settings: Settings | None,
        fill_id: int | None,
        sleep: Callable[[float], None],
        delay_range: tuple[float, float],
        screenshot_path: Path | None,
    ) -> None:
        self.page, self.conn, self.resume, self.settings = page, conn, resume, settings
        self.fill_id, self.sleep, self.delay_range = fill_id, sleep, delay_range
        self.screenshot_path = screenshot_path
        self.acted = False

    # -- bookkeeping --

    def _log(self, kind: str, target: str, details: str, *, screenshot: bool = False) -> None:
        if self.conn is not None:
            shot = str(self.screenshot_path) if screenshot and self.screenshot_path else None
            safety.log_action(self.conn, kind, target, details, fill_id=self.fill_id, screenshot_path=shot)

    def _begin(self, kind: str) -> None:
        """Ask safety, then pause like a person (no pause before the very first action)."""
        safety.check(kind, self.page.url, settings=self.settings)
        if self.acted:
            self.sleep(random.uniform(*self.delay_range))
        self.acted = True

    # -- the loop --

    def run(self, fields: list[FormField], answers: list[FieldAnswer]) -> list[FieldResult]:
        results = []
        for f, a in zip(fields, answers):
            result = self._one(f, a)
            results.append(result)
            self._highlight(f, a, result)
        return results

    def _one(self, f: FormField, a: FieldAnswer) -> FieldResult:
        """Fill one field. Never raises for a field problem: it becomes ``needs_you`` or ``failed``."""
        name = f.label or "(no label)"
        if f.needs_you:
            return self._leave(f,"the page gave no readable question")
        if f.type == "unsupported":  # reported by the reader so it is never skipped silently; never touched
            return self._leave(f, a.note or "a control JobPilot cannot fill: fill it yourself")
        if f.type == "file":
            if a.source != "resume":
                return self._leave(f,a.note or "only the resume is uploaded by the bot")
            if self.resume is None:
                return self._leave(f,"no resume chosen yet (needs a job post, or pass --resume)")
        elif not a.value.strip():
            return self._leave(f,a.note or "no answer for this field")
        frame = self._frame(f)
        if frame is None:
            return self._fail(f, "its frame is no longer on the page")
        try:
            extra = self._write(f, a, frame)
        except safety.SafetyError as exc:
            return self._leave(f,f"blocked by the safety check: {exc}")
        except _CannotFill as exc:
            return self._leave(f,str(exc))
        except (_PageChanged, PlaywrightError) as exc:
            return self._fail(f, f"{type(exc).__name__}: {_short(str(exc), 120)}")
        self._log("upload" if f.type == "file" else "fill", name, f"{f.type}: filled")
        flagged = a.flagged or bool(extra)
        note = " ".join(part for part in (a.note, extra) if part)
        return FieldResult(f.label, f.type, "filled", note, flagged)

    def _leave(self, f: FormField, reason: str) -> FieldResult:
        self._log("fill", f.label or "(no label)", f"{f.type}: left empty, needs you")
        return FieldResult(f.label, f.type, "needs_you", reason, True)

    def _fail(self, f: FormField, reason: str) -> FieldResult:
        self._log("error", f.label or "(no label)", f"{f.type}: failed", screenshot=True)
        return FieldResult(f.label, f.type, "failed", reason, True)

    def _frame(self, f: FormField) -> Frame | None:
        if not f.frame:
            return self.page.main_frame
        frames = self.page.frames
        # Several frames can share one address (about:srcdoc), so the saved position comes first; the address confirms it.
        if f.frame_number < len(frames) and frames[f.frame_number].url == f.frame:
            return frames[f.frame_number]
        same = [fr for fr in frames if fr.url == f.frame]
        return same[0] if len(same) == 1 else None

    # -- the writers --

    def _element(self, frame: Frame, f: FormField, which: int = 0) -> Locator:
        """The field's input at the saved position, after checking it really is that kind of field."""
        if which >= len(f.indexes):
            raise _PageChanged("the reader did not save where this field is")
        el = frame.locator(_FIELDS).nth(f.indexes[which])
        info = el.evaluate(
            "e => ({tag: e.tagName.toLowerCase(), type: (e.type || '').toLowerCase(), name: e.name || ''})", timeout=ACTION_TIMEOUT_MS
        )
        tag, kind = info["tag"], info["type"]
        if f.name and info["name"] != f.name:  # the page moved things around since the reader looked
            raise _PageChanged(f"the field at this position is now named {info['name'] or '(none)'!r}, not {f.name!r}")
        ok = {
            "select": tag == "select",
            "textarea": tag == "textarea",
            "radio": tag == "input" and kind == "radio",
            "checkbox": tag == "input" and kind == "checkbox",
            "file": tag == "input" and kind == "file",
        }.get(f.type, tag in ("input", "textarea") and kind not in _NEVER_TOUCH)
        if not ok or kind in ("button", "submit", "image", "reset"):
            raise _PageChanged(f"expected a {f.type} field but found <{tag} type={kind or '-'}>")
        return el

    def _write(self, f: FormField, a: FieldAnswer, frame: Frame) -> str:
        """Put the answer in the field. Returns an extra note when the result needs a second look ("" if none)."""
        if f.type == "file":
            return self._upload(f, frame)
        if f.type == "select":
            return self._select(f, a, frame)
        if f.type == "dropdown":
            return self._dropdown(f, a, frame)
        if f.type in ("radio", "checkbox"):
            return self._choose(f, a, frame)
        if f.type == "date":
            iso = to_iso_date(a.value)
            if iso is None:
                raise _CannotFill("the saved answer is not a date I can read safely")
            el = self._element(frame, f)
            self._begin("fill")
            el.fill(iso, timeout=ACTION_TIMEOUT_MS)
            return ""
        el = self._element(frame, f)
        self._begin("fill")
        el.fill(a.value, timeout=ACTION_TIMEOUT_MS)
        if f.max_length and len(a.value) > f.max_length:
            return f"longer than the page's limit of {f.max_length} characters: shorten it"
        return ""

    def _upload(self, f: FormField, frame: Frame) -> str:
        assert self.resume is not None
        el = self._element(frame, f)
        self._begin("upload")
        suffix = self.resume.path.suffix.lower()
        mime = "application/pdf" if suffix == ".pdf" else "application/octet-stream"
        # The name the employer sees comes from here; the file on disk keeps its own name.
        el.set_input_files(
            {"name": self.resume.upload_name, "mimeType": mime, "buffer": self.resume.path.read_bytes()},
            timeout=ACTION_TIMEOUT_MS,
        )
        return ""

    def _select(self, f: FormField, a: FieldAnswer, frame: Frame) -> str:
        option = pick_option(a.value, f.options)
        if not option:
            raise _CannotFill(f"none of the {len(f.options)} options matches the saved answer")
        el = self._element(frame, f)
        value = el.evaluate(
            r"(e, want) => { const o = [...e.options].find(o => o.text.replace(/\s+/g, ' ').trim() === want); return o ? o.value : null; }",
            option,
            timeout=ACTION_TIMEOUT_MS,
        )
        if value is None:
            raise _PageChanged("the option disappeared from the list")
        self._begin("fill")
        el.select_option(value=value, timeout=ACTION_TIMEOUT_MS)
        return ""

    def _choose(self, f: FormField, a: FieldAnswer, frame: Frame) -> str:
        """Radio buttons and checkboxes: tick the option(s) the answer names. Nothing else is ticked or cleared."""
        if not f.options:  # one lone box ("I agree"): the saved answer says tick or not
            stance = _stance(a.value)
            if stance is None:
                raise _CannotFill("cannot tell from the saved answer whether this box should be ticked")
            if not stance:
                return ""  # a "no": the box stays as it is
            self._set_checked(self._element(frame, f), True)
            return ""
        wanted: list[str] = []
        if f.type == "checkbox":  # "Git, Docker" names two boxes: look at each part (the whole text would partly match just one)
            for part in re.split(r"[,;\n]+", a.value):
                option = pick_option(part, f.options)
                if option and option not in wanted:
                    wanted.append(option)
        if not wanted:
            whole = pick_option(a.value, f.options)
            wanted = [whole] if whole else []
        if not wanted:
            raise _CannotFill(f"none of the {len(f.options)} options matches the saved answer")
        for option in wanted:
            self._set_checked(self._element(frame, f, f.options.index(option)), True)
        return ""

    def _set_checked(self, el: Locator, wanted: bool) -> None:
        """Tick a box. Works on the real input; a visually hidden input is ticked with a click on the input itself."""
        if el.is_checked() == wanted:
            return
        self._begin("fill")
        try:
            el.check(timeout=3000)
        except PlaywrightError:  # a custom-styled box: another element covers it, or it is invisible
            el.evaluate("e => e.click()", timeout=ACTION_TIMEOUT_MS)
        if el.is_checked() != wanted:
            raise _PageChanged("the box did not change")

    # -- custom dropdowns --

    def _dropdown_box(self, frame: Frame, f: FormField) -> tuple[ElementHandle, ElementHandle | None]:
        """``(the dropdown's box, its own text input or None)``. A <div> dropdown is found again by ``custom_index``."""
        if f.custom_index >= 0:
            handle = frame.evaluate_handle(_FIND_CUSTOM_JS, f.custom_index)
            box = handle.as_element()
            if box is None:
                raise _PageChanged("the custom dropdown is no longer on the page")
            return box, None
        el = self._element(frame, f)  # a react-select style role=combobox input: it is the box AND the search box
        handle = el.element_handle(timeout=ACTION_TIMEOUT_MS)
        box = handle.evaluate_handle(_COMBO_BOX_JS).as_element()
        return (box or handle), handle

    def _options(self, box: ElementHandle) -> list[tuple[str, ElementHandle]]:
        """The options showing right now, as ``(text, element)``."""
        found = box.evaluate_handle(_OPTIONS_JS)
        out: list[tuple[str, ElementHandle]] = []
        for handle in found.get_properties().values():
            element = handle.as_element()
            if element is not None:
                text = " ".join(element.inner_text().split())
                if text:
                    out.append((text, element))
        return out

    def _open_dropdown(self, box: ElementHandle, own_input: ElementHandle | None) -> None:
        """Click the dropdown's box so its list shows (only if it is not showing already)."""
        if self._options(box):
            return
        trigger = own_input or box.evaluate_handle(_TRIGGER_JS).as_element() or box
        if not trigger.evaluate(_SAFE_TRIGGER_JS):
            raise _CannotFill("this dropdown is a button that could submit the form: pick it yourself")
        trigger.click(timeout=ACTION_TIMEOUT_MS)
        self.page.wait_for_timeout(OPEN_WAIT_MS)

    def _search(self, box: ElementHandle, own_input: ElementHandle | None, query: str) -> bool:
        """Type ``query`` into the dropdown's search box, if it has one. Returns False when there is none."""
        search = own_input or box.evaluate_handle(_SEARCH_JS).as_element()
        if search is None:
            return False
        search.fill(query, timeout=ACTION_TIMEOUT_MS)
        self.page.wait_for_timeout(SEARCH_WAIT_MS)
        return True

    def _clear_search(self, box: ElementHandle, own_input: ElementHandle | None) -> None:
        """Remove what was typed into the search box, so no stray text is left in the form."""
        search = own_input or box.evaluate_handle(_SEARCH_JS).as_element()
        if search is not None:
            try:
                search.fill("", timeout=ACTION_TIMEOUT_MS)
            except PlaywrightError:
                pass

    def _click_option(self, element: ElementHandle) -> None:
        """Click one option of an open dropdown list (never a button or link: those are filtered out)."""
        element.click(timeout=ACTION_TIMEOUT_MS)

    def _pick_one(self, box: ElementHandle, own_input: ElementHandle | None, value: str, strict: bool) -> str:
        """Open the list, find ``value`` (searching for it when it is not showing), click it. Returns the option or ""."""

        def choose(options: list[tuple[str, ElementHandle]]) -> tuple[str, ElementHandle] | None:
            texts = [text for text, _ in options]
            if strict:  # skills: the very same word only ("Java" is not "JavaScript")
                name = next((t for t in texts if _option_key(t) == _option_key(value)), "")
            else:
                name = pick_option(value, texts)
            return next(((t, e) for t, e in options if t == name), None) if name else None

        self._open_dropdown(box, own_input)
        hit = choose(self._options(box))
        if hit is None:
            queries = [value]
            subject = re.split(r"\s+in\s+", value)[-1].strip()  # "Bachelor of Science in IT" is listed as "IT"
            if subject and subject.lower() != value.lower():
                queries.append(subject)
            first_word = next((w for w in re.findall(r"[A-Za-z0-9+#.]+", subject or value) if len(w) >= 4), "")
            if first_word and first_word.lower() not in (q.lower() for q in queries):
                queries.append(first_word)  # a long name may be written slightly differently in the list
            for query in queries:
                if not self._search(box, own_input, query):
                    break
                hit = choose(self._options(box))
                if hit is not None:
                    break
        if hit is None:
            self._clear_search(box, own_input)
            return ""
        before = _option_key(box.evaluate(_SHOWN_JS))
        self._click_option(hit[1])
        self.page.wait_for_timeout(OPEN_WAIT_MS)
        after = _option_key(box.evaluate(_SHOWN_JS))
        if after == before or not (set(_option_key(hit[0]).split()) & set(after.split())):
            raise _PageChanged(f"the dropdown did not take {hit[0]!r}")
        return hit[0]

    def _close_dropdown(self, box: ElementHandle, own_input: ElementHandle | None) -> None:
        """A multi-choice list stays open after a pick: click its box again to close it."""
        try:
            if self._options(box):
                trigger = own_input or box.evaluate_handle(_TRIGGER_JS).as_element() or box
                if trigger.evaluate(_SAFE_TRIGGER_JS):
                    trigger.click(timeout=ACTION_TIMEOUT_MS)
        except PlaywrightError:
            pass

    def _dropdown(self, f: FormField, a: FieldAnswer, frame: Frame) -> str:
        """A custom dropdown: pick the option(s) the answer names. A value that is not in the list is left out."""
        box, own_input = self._dropdown_box(frame, f)
        values = [v.strip() for v in re.split(r"[,;\n]+", a.value)] if f.multi else [a.value.strip()]
        values = [v for v in values if v][:MULTI_TRIES]
        limit = (f.max_choices or MULTI_LIMIT) if f.multi else 1
        strict = f.multi and len(values) > 1  # a list of skills: the very same word only
        chosen: list[str] = []
        for value in values:
            if len(chosen) >= limit:
                break
            self._begin("fill")
            option = self._pick_one(box, own_input, value, strict)
            if option and option not in chosen:
                chosen.append(option)
        if f.multi:
            self._close_dropdown(box, own_input)
        if not chosen:
            raise _CannotFill(f"custom dropdown: no option matching {_short(a.value, 40)!r} appeared in its list")
        if f.multi:
            return f"chose {len(chosen)}: {', '.join(chosen)}"
        return "" if _option_key(chosen[0]) == _option_key(a.value) else f"chose {chosen[0]!r}"

    # -- showing flags --

    def _highlight(self, f: FormField, a: FieldAnswer, result: FieldResult) -> None:
        """Outline a flagged field and tag it. A cosmetic step: if it cannot be drawn, the report still has the facts."""
        if not result.flagged or not (f.indexes or f.custom_index >= 0):
            return
        if result.outcome == "filled":
            tag = self._guess_tag(a)
            why = _short(result.note, 140)
            dashed = False
        else:
            if result.note.startswith("error:"):  # an engine error: the tag stays short, the page gets the first line of the reason
                tag, why = "needs you: no answer could be decided", _short(result.note, 110)
            else:
                tag = f"needs you: {_short(result.note, 45)}"
                why = _short(result.note, 110) if len(result.note) > 45 else ""
            dashed = True
        frame = self._frame(f)
        if frame is None:
            return
        args = {**amber_colors(), "tag": tag, "why": why, "dashed": dashed, "group": len(f.indexes) > 1}
        try:
            if f.custom_index >= 0:
                box = frame.evaluate_handle(_FIND_CUSTOM_JS, f.custom_index).as_element()
                if box is not None:
                    box.evaluate(_HIGHLIGHT_JS, args)
            else:
                frame.locator(_FIELDS).nth(f.indexes[0]).evaluate(_HIGHLIGHT_JS, args, timeout=ACTION_TIMEOUT_MS)
        except PlaywrightError:
            pass

    @staticmethod
    def _guess_tag(a: FieldAnswer) -> str:
        if a.source == "draft":
            return "drafted by AI: check me"
        if a.kind == "protected":
            return "protected answer: check it"
        if a.source == "resume":
            return "guess: check this file"
        if not a.recommended:
            return "weak match: check me"
        return "check me"


def fill_page(
    page: Page,
    fields: list[FormField],
    answers: list[FieldAnswer],
    *,
    conn: sqlite3.Connection | None = None,
    resume: ResumeFile | None = None,
    settings: Settings | None = None,
    fill_id: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    delay_range: tuple[float, float] = DELAY_RANGE,
    screenshot_path: Path | None = None,
) -> FillReport:
    """Fill the open page from the answer engine's decisions, then stop. Never submits.

    Args:
        page: the page (or the bot's browser tab) to fill. The visible step of a multi-step form only.
        fields: from ``reader.read_fields(page)``.
        answers: from ``answers.answer_form(...)``, same order and length as ``fields``.
        conn: when given, every action is written to ``action_log`` (labels and outcomes, never values).
        resume: the file to upload into a resume field. ``None`` leaves resume fields empty and flagged.
        settings: override settings (tests). Defaults to ``settings.json``.
        sleep, delay_range: the pause between actions. Tests pass a fake ``sleep`` so they run instantly.
        screenshot_path: where to save a full-page screenshot of the result (outlines included).

    Raises:
        safety.SafetyError: this page may not be filled in the current mode (mock mode and a real website).
        ValueError: ``fields`` and ``answers`` do not line up.
    """
    if len(fields) != len(answers) or any(f.label != a.label for f, a in zip(fields, answers)):
        raise ValueError("fields and answers must be the same list, in the same order")
    safety.check("fill", page.url, settings=settings)
    filler = _Filler(page, conn, resume, settings, fill_id, sleep, delay_range, screenshot_path)
    report = FillReport(url=page.url, results=filler.run(fields, answers))
    if screenshot_path is not None:
        try:
            safety.check("screenshot", page.url, settings=settings)
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot_path), full_page=True)
            report.screenshot_path = screenshot_path
            filler._log("screenshot", page.url, report.summary(), screenshot=True)
        except (PlaywrightError, OSError, safety.SafetyError) as exc:
            filler._log("error", page.url, f"screenshot failed: {type(exc).__name__}")
    return report
