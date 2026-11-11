"""Answer engine, step 1: recognise PERSONAL fields and fill them straight from your profile.

Personal fields (name, email, phone, address, city, country, links) are handled by
plain code, before RAG or any AI (CLAUDE.md rule 3: those values never go in a
prompt). Code is also more exact than similarity search: embeddings once matched
"Address" to "Email address".

How a field is recognised (first signal that answers wins)
---------------------------------------------------------
1. ``autocomplete`` attribute: a web standard, e.g. ``given-name``, ``email``, ``tel``.
2. Input ``type``: ``email`` or ``tel``.
3. The input's ``name`` attribute, e.g. ``first_name``, ``phoneNumber``.
4. Words in a SHORT label, e.g. "Mobile number", "Last name".

Two guards keep real questions out:
* A long label is a question, not a personal box: "Do you agree to be contacted by
  email?" is left for the answer bank.
* Someone else's details are not yours: "Referrer email", "Emergency contact phone",
  "School name" are left alone.

Missing values are never invented: the field stays blank and is flagged.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Literal

from engine.forms.reader import FormField

PersonalKey = Literal[
    "first_name", "middle_name", "middle_initial", "last_name", "full_name",
    "email", "phone", "address", "location", "city", "country",
    "linkedin", "github", "portfolio",
]

MAX_LABEL_WORDS = 5  # longer labels are questions, not personal boxes

# 1. autocomplete tokens (https://html.spec.whatwg.org/#autofill) -> profile value
_AUTOCOMPLETE: dict[str, PersonalKey] = {
    "given-name": "first_name",
    "additional-name": "middle_name",
    "family-name": "last_name",
    "name": "full_name",
    "email": "email",
    "tel": "phone",
    "tel-national": "phone",
    "tel-local": "phone",
    "street-address": "address",
    "address-line1": "address",
    "address-level2": "city",
    "country": "country",
    "country-name": "country",
}

# 3 and 4. word patterns, checked IN ORDER (so "email address" is email, not address)
_PATTERNS: list[tuple[PersonalKey, re.Pattern[str]]] = [
    ("email", re.compile(r"\be ?mail\b")),
    ("phone", re.compile(r"\b(phone|mobile|cell|cellphone|telephone|contact (number|no))\b")),
    # full name before the parts: "first and last name" is the full name, not the last name
    ("full_name", re.compile(r"^((your|full|legal|complete) )?name( first and last)?$|^first and last name$|^full ?name\b")),
    ("first_name", re.compile(r"\b(first|given|fore) ?name\b|\bfname\b")),
    ("middle_initial", re.compile(r"\bmiddle initial\b|^mi$")),
    ("middle_name", re.compile(r"\bmiddle ?name\b")),
    ("last_name", re.compile(r"\b(last|family|sur) ?name\b|\blname\b")),
    ("linkedin", re.compile(r"\blinked ?in\b")),
    ("github", re.compile(r"\bgit ?hub\b")),
    ("portfolio", re.compile(r"\b(portfolio|website|personal site|web site)\b")),
    ("address", re.compile(r"\b(address|street)\b")),
    ("city", re.compile(r"\b(city|town|municipality)\b")),
    ("country", re.compile(r"\bcountry\b")),
    ("location", re.compile(r"^(current )?location$|^where are you based$")),
]

# Someone else's details, or a different thing that happens to contain "name"/"email".
_NOT_YOURS = re.compile(
    r"\b(refer\w*|emergency|reference|guardian|parent|mother|father|spouse|supervisor|manager|"
    r"school|university|company|employer|business|project|file|user ?name|nick ?name|code|confirm\w* code)\b"
)

_PERSONAL_TYPES = {"text", "email", "tel", "url", "select", "dropdown", "textarea"}
_CHOICE_TYPES = {"select", "dropdown"}


@dataclass(frozen=True)
class PersonalFill:
    """What to put in a personal field, and why.

    ``value`` is empty when your profile has no value or no dropdown option fits;
    then ``flagged`` is True so you fill it yourself.
    """

    key: PersonalKey
    value: str
    signal: str  # which hint recognised it: autocomplete / type / name / label
    flagged: bool
    note: str = ""


# ---- recognising -------------------------------------------------------------


def _words(text: str) -> str:
    """Lowercase words only: 'Mobile No.*' -> 'mobile no'; 'firstName' -> 'first name'."""
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)  # camelCase
    text = re.sub(r"\((optional|required)\)|\*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    text = re.sub(r"^(please )?(enter |provide )?(your )?", "", text.strip())
    return text.strip()


def _match_words(text: str) -> PersonalKey | None:
    words = _words(text)
    if not words or _NOT_YOURS.search(words):
        return None
    for key, pattern in _PATTERNS:
        if pattern.search(words):
            return key
    return None


def detect_personal(field: FormField) -> tuple[PersonalKey, str] | None:
    """Return ``(which profile value, which hint said so)``, or ``None`` if not a personal field."""
    if field.type not in _PERSONAL_TYPES:
        return None
    label = _words(field.label)
    if len(label.split()) > MAX_LABEL_WORDS or _NOT_YOURS.search(label) or _NOT_YOURS.search(_words(field.name)):
        return None  # a real question, or someone else's details

    token = field.autocomplete.split()[-1] if field.autocomplete else ""
    if token in _AUTOCOMPLETE:
        return _AUTOCOMPLETE[token], "autocomplete"
    if field.type in ("email", "tel"):
        return ("email" if field.type == "email" else "phone"), "type"
    by_name = _match_words(field.name.replace("[", " ").replace("]", " ")) if field.name else None
    if by_name:
        return by_name, "name"
    by_label = _match_words(field.label)
    if by_label:
        if field.type == "textarea" and by_label != "address":
            return None  # a big box labelled "name..." is a question, not your name
        return by_label, "label"
    return None


# ---- values from your profile -------------------------------------------------


def profile_values(conn: sqlite3.Connection) -> dict[str, str]:
    """Your personal values from the database, keyed like :data:`PersonalKey` (empty when unknown)."""
    row = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
    if row is None:
        return {}
    location = row["location"] or ""
    parts = [p.strip() for p in location.split(",") if p.strip()]
    middle = (row["middle_name"] or "").strip()
    return {
        "first_name": row["first_name"] or "",
        "middle_name": middle,
        "middle_initial": f"{middle[0]}." if middle else "",
        "last_name": row["last_name"] or "",
        "full_name": row["full_name"] or "",
        "email": row["email"] or "",
        "phone": row["phone"] or "",
        "address": row["address"] or "",
        "location": location,
        "city": parts[0] if parts else "",
        "country": parts[-1] if len(parts) > 1 else "",
        "linkedin": row["linkedin"] or "",
        "github": row["github"] or "",
        "portfolio": row["portfolio"] or "",
    }


def format_phone(stored: str, field: FormField) -> tuple[str, str]:
    """Write your ONE stored number in the format this field expects. Returns ``(value, why)``.

    Philippine mobile numbers have three common forms:
        international  +639171234567   (placeholder "+63...", 13 characters)
        local          09171234567     (placeholder "09...", autocomplete tel-national, 11 characters)
        bare           9171234567      (next to a separate country-code box, 10 characters)
    With no hint, the number is written the way you stored it.
    """
    digits = re.sub(r"\D", "", stored)
    if digits.startswith("63") and len(digits) == 12:
        national = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        national = digits[1:]
    else:
        return stored, "not a Philippine mobile number: written as stored"
    forms = {"international": f"+63{national}", "local": f"0{national}", "bare": national}

    placeholder = field.placeholder.replace(" ", "")
    token = field.autocomplete.split()[-1] if field.autocomplete else ""
    if token in ("tel-national", "tel-local"):
        return forms["local"], "autocomplete says national format"
    if placeholder.startswith("+"):
        return forms["international"], "placeholder starts with +"
    if re.match(r"^0\d|^0x", placeholder, re.IGNORECASE):
        return forms["local"], "placeholder starts with 0"
    if re.match(r"^9[\dx]{9}$", placeholder, re.IGNORECASE):
        return forms["bare"], "placeholder has no country code"
    if field.pattern.startswith(("\\+", "+", "[+]")):
        return forms["international"], "pattern expects +"
    if field.pattern.startswith("0"):
        return forms["local"], "pattern expects 0"
    if field.max_length in (10, 11, 13):
        kind = {10: "bare", 11: "local", 13: "international"}[field.max_length]
        return forms[kind], f"field allows {field.max_length} characters"
    stored_kind = "international" if stored.strip().startswith("+") else "local"
    return forms[stored_kind], "no hint: written the way you stored it"


def pick_option(value: str, options: list[str]) -> str:
    """The dropdown option that matches ``value`` (exact first, then partial), or "" if none fits."""
    want = value.strip().lower()
    if not want:
        return ""
    for option in options:
        if option.strip().lower() == want:
            return option
    for option in options:
        low = option.strip().lower()
        if len(low) >= 3 and (low in want or want in low):
            return option
    return ""


def fill_personal(field: FormField, values: dict[str, str]) -> PersonalFill | None:
    """Recognise a personal field and decide its value. ``None`` means "not personal": try the answer bank."""
    found = detect_personal(field)
    if found is None:
        return None
    key, signal = found
    value = values.get(key, "")
    if not value:
        return PersonalFill(key, "", signal, True, f"no {key.replace('_', ' ')} in your profile")
    note = ""
    if key == "phone":
        value, note = format_phone(value, field)
    if field.type in _CHOICE_TYPES and field.options:
        option = pick_option(value, field.options)
        if not option:
            return PersonalFill(key, "", signal, True, f"none of the {len(field.options)} options matches your {key}")
        value, note = option, "matching dropdown option"
    return PersonalFill(key, value, signal, False, note)
