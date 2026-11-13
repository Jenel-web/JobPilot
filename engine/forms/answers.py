"""The answer engine: decide what goes in each form field, and where it came from.

Order for every field (first rule that applies wins; see :func:`answer_field`):

1. No readable label  -> empty, "needs you".
2. Personal field     -> your profile, by code. No search, no AI.
3. Everything else is looked up in your answer bank (``learning.triage_question``) and:
   * matched ``protected`` -> your saved text exactly, flagged for review
   * matched ``fixed``     -> your saved text as written (strong match, so not flagged)
   * sensitive, weak match -> closest saved text, flagged NOT RECOMMENDED; nothing saved -> empty
   The AI never writes a sensitive or protected answer.

Part 1: recognise PERSONAL fields and fill them straight from your profile.

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

from engine import learning, safety
from engine.forms import drafting
from engine.forms.reader import FormField
from engine.profile import lookup_answer
from engine.rag import RagError
from engine.settings import Settings

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

# Sensitive = legal, eligibility or identity questions (CLAUDE.md rules 4 and 5b). The AI never
# writes these: the answer is your saved text word for word, or empty for you to fill in.
# Matched on whole words in the lowercased label, so "embrace" does not trigger "race".
# One list in one place: add a word here when a form slips through.
SENSITIVE_PATTERN = re.compile(
    r"\b("
    r"visas?|sponsor\w*|authori[sz]\w*|work permits?|right to work|eligible to work|"
    r"citizens?|citizenship|nationality|immigration|"
    r"have you ever|convict\w*|criminal|felony|misdemeanou?r|arrest\w*|"
    r"background checks?|consents?|terms and conditions|"
    r"related to (an?|any) (current |former )?(employee|officer|director|member)|relatives?|"
    r"disabilit\w+|disabled|gender|sex|pronouns?|ethnic\w*|race|racial|veterans?|"
    r"marital status|religio\w+|sexual orientation|"
    r"gpa|grade point average|"
    r"(current|previous|last|present) (salary|pay|compensation)|salary history|"
    r"date of birth|dob|birth ?date|birthday|"
    r"(18|21) years|over (18|21)|legal age"
    r")\b"
)

_PERSONAL_TYPES = {"text", "email", "tel", "url", "select", "dropdown", "textarea"}
_CHOICE_TYPES = {"select", "dropdown"}
_GROUP_TYPES = {"select", "dropdown", "radio", "checkbox"}  # answers picked from a list of options


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


def is_sensitive(label: str) -> bool:
    """True if the question is legal / eligibility / identity related (visa, "have you ever", GPA, gender...).

    Such a question is treated as ``protected`` even when no saved answer matches it: the AI
    must never write its answer.
    """
    return bool(SENSITIVE_PATTERN.search(_words(label)))


# Reflective = asks for YOUR VIEW, so the answer is an opinion drawn from your projects (not a lookup).
REFLECTIVE_PATTERN = re.compile(
    r"\bstrengths?\b|"
    r"\bhow do you (?:decide|choose|approach|handle|learn|prioriti[sz]e|solve|tackle|work|pick)\b|"
    r"\bwhat (?:motivates|drives|inspires|excites|interests) you\b|"
    r"\babout yourself\b|\bdescribe yourself\b|\bwho are you\b|"
    r"\bwhat (?:kind|type|sort) of (?:apps?|projects?|problems?|work|software)\b|"
    r"\bwhat do you (?:enjoy|like|love|care about|value)\b|"
    r"\byour (?:approach|philosophy|process) to\b"
)

# Company questions need the job post to answer well. Until Phase 4 gives us the job post, the AI does not
# touch them: an open answer you saved is used as written, otherwise the field is left for you.
COMPANY_PATTERN = re.compile(
    r"\bwhy (?:do|would|did) you want to (?:work|join)\b|\bwhy (?:us|this (?:company|role|position|job)|our (?:company|team))\b|"
    r"\bwhy are you (?:interested|applying)\b|"
    r"\bwhat (?:attracts|interests|excites|draws) you (?:about|to) (?:us|this|our|the (?:company|role|position))\b|"
    r"\bwhy do you want this (?:job|role|position|internship)\b"
)


def is_reflective(label: str) -> bool:
    """True if the question asks for your own view (strengths, how you decide, what drives you)."""
    return bool(REFLECTIVE_PATTERN.search(_words(label)))


def is_company_question(label: str) -> bool:
    """True if the question asks why you want THIS company or role (best answered with the job post, Phase 4)."""
    return bool(COMPANY_PATTERN.search(_words(label)))


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


# ---- the answer engine -----------------------------------------------------------------------

AnswerSource = Literal["personal", "bank", "draft", "none"]


@dataclass(frozen=True)
class FieldAnswer:
    """What the engine decided for one form field. Everything the review screen needs.

    ``value`` is empty when you must fill the field yourself. ``flagged`` means "look at this
    before you submit". ``recommended`` is False for a weak match (shown as NOT RECOMMENDED).
    """

    label: str
    value: str
    source: AnswerSource
    flagged: bool
    note: str = ""
    kind: str = ""  # the saved answer's kind: fixed / open / protected
    confidence: float = 0.0  # RAG similarity; 1.0 for personal fields
    recommended: bool = True
    matched_question: str = ""
    unknown_id: int | None = None  # row on the unknown questions list, when the question was filed there


def _needs_you(label: str, note: str, unknown_id: int | None = None) -> FieldAnswer:
    """An empty, flagged field: you fill it yourself."""
    return FieldAnswer(label, "", "none", True, note, unknown_id=unknown_id)


def answer_field(
    conn: sqlite3.Connection,
    field: FormField,
    values: dict[str, str],
    *,
    job_scope: str = "any",
    job_city: str = "",
    page_url: str = "",
    settings: Settings | None = None,
) -> FieldAnswer:
    """Decide the answer for ONE field. Reads and decides only: nothing is typed or clicked.

    Args:
        values: your personal values (:func:`profile_values`).
        job_scope / job_city: where the job is, so the right location-scoped answer is used.
        page_url: remembered with unknown questions and suggested wordings.

    Raises:
        learning.LearningError, rag.RagError, sqlite3.Error: the lookup failed
            (:func:`answer_form` turns these into a flagged field).
    """
    if field.needs_you:
        return _needs_you(field.label, "no readable label: needs you")

    personal = fill_personal(field, values)
    if personal is not None:
        return FieldAnswer(
            field.label, personal.value, "personal", personal.flagged,
            personal.note, confidence=1.0 if personal.value else 0.0,
        )

    triage = learning.triage_question(
        conn, field.label, page_url=page_url, field_type=field.type, options=tuple(field.options), settings=settings
    )
    hit = triage.match.hit
    row = lookup_answer(conn, hit.ref, job_scope=job_scope, job_city=job_city) if hit is not None else None
    score = hit.score if hit is not None else 0.0

    if triage.outcome == "matched" and row is not None:
        if row["kind"] == "open" and field.type in drafting.DRAFTABLE_TYPES and not is_sensitive(field.label):
            if is_company_question(field.label):
                return _saved_open(field, row, score, "company question: saved text used; the AI needs the job post to adapt it (Phase 4)")
            return _rewritten_answer(conn, field, row, score, settings)
        return _matched_answer(field, row, score)

    # No close saved question (or no saved row for this job's location).
    if is_sensitive(field.label):
        if row is not None and hit is not None:
            return FieldAnswer(
                field.label, _pick(field, row["answer"]), "bank", True,
                f"NOT RECOMMENDED: closest saved question scored {score:.2f} (needs {triage.match.threshold:.2f})",
                kind=row["kind"], confidence=score, recommended=False,
                matched_question=hit.ref, unknown_id=triage.unknown_id,
            )
        return _needs_you(field.label, "legal/eligibility question: you must answer this yourself", triage.unknown_id)
    # New non-sensitive question: the AI may draft it, but only into a text box.
    if field.type not in drafting.DRAFTABLE_TYPES:
        return _needs_you(field.label, "new question: choose this one yourself (the AI only writes into text boxes)", triage.unknown_id)
    if is_company_question(field.label):
        return _needs_you(field.label, "company question: needs the job post (Phase 4), so answer it yourself for now", triage.unknown_id)
    if is_reflective(field.label):
        draft = drafting.reflect_answer(conn, field, settings=settings)
        kind_of_note = "AI interpretation (an opinion drawn from your projects, edit freely)"
    else:
        draft = drafting.draft_answer(conn, field, settings=settings)
        kind_of_note = "AI draft"
    if draft.ok:
        return FieldAnswer(
            field.label, draft.text, "draft", True,
            f"{kind_of_note} from {draft.source}: check it before submitting",
            confidence=draft.confidence, unknown_id=triage.unknown_id,
        )
    return _needs_you(field.label, f"AI draft rejected: {draft.note}", triage.unknown_id)


def _rewritten_answer(
    conn: sqlite3.Connection, field: FormField, row: sqlite3.Row, score: float, settings: Settings | None
) -> FieldAnswer:
    """A matched ``open`` answer, adapted to this form's wording by the AI (flagged). Falls back to the saved text."""
    reflective = is_reflective(field.label)
    if reflective:
        result = drafting.reflect_answer(conn, field, row["answer"], row["kind"], settings=settings)
    else:
        result = drafting.rewrite_open(conn, field, row["answer"], row["kind"], settings=settings)
    common = {"kind": row["kind"], "confidence": score, "matched_question": row["question"]}
    if result.ok and reflective:
        note = f"AI interpretation of your saved answer and projects ({result.source}): an opinion drawn from your data, edit freely"
        return FieldAnswer(field.label, result.text, "bank", True, note, **common)
    if result.ok:
        note = f"open answer rewritten for this question (from {result.source}): check it"
        return FieldAnswer(field.label, result.text, "bank", True, note, **common)
    note = f"AI rewrite not used ({result.note}): saved text used"
    return FieldAnswer(field.label, row["answer"], "bank", True, note, **common)


def _pick(field: FormField, saved: str) -> str:
    """The saved text for a text box; for a list of options, the option that matches it ("" if none)."""
    if field.type in _GROUP_TYPES and field.options:
        return pick_option(saved, field.options)
    return saved


def _saved_open(field: FormField, row: sqlite3.Row, score: float, note: str) -> FieldAnswer:
    """Your saved open answer, used as written (no AI) and flagged."""
    return FieldAnswer(
        field.label, row["answer"], "bank", True, note,
        kind=row["kind"], confidence=score, matched_question=row["question"],
    )


def _matched_answer(field: FormField, row: sqlite3.Row, score: float) -> FieldAnswer:
    """A strong match: use the saved answer according to its kind."""
    kind = row["kind"]
    value = _pick(field, row["answer"])

    def make(text: str, flagged: bool, note: str) -> FieldAnswer:
        return FieldAnswer(
            field.label, text, "bank", flagged, note,
            kind=kind, confidence=score, matched_question=row["question"],
        )

    if not value:
        return make("", True, f"none of the {len(field.options)} options matches your saved answer")
    if kind == "protected":
        return make(value, True, "protected: used exactly as saved, never sent to the AI")
    if kind == "open":
        # Only reached for non-text fields or sensitive questions: the AI is not used, so the saved text, flagged.
        return make(value, True, "open answer: saved text, check it fits")
    return make(value, False, "")


def answer_form(
    conn: sqlite3.Connection,
    fields: list[FormField],
    *,
    job_scope: str = "any",
    job_city: str = "",
    page_url: str = "",
    settings: Settings | None = None,
) -> list[FieldAnswer]:
    """Answer every field, in page order. One failing field never stops the others.

    Logs one ``read`` row to ``action_log`` (a count only: values can hold phone or email).
    """
    values = profile_values(conn)
    results: list[FieldAnswer] = []
    for f in fields:
        try:
            results.append(
                answer_field(conn, f, values, job_scope=job_scope, job_city=job_city, page_url=page_url, settings=settings)
            )
        except (learning.LearningError, drafting.DraftError, RagError, sqlite3.Error, RuntimeError, ValueError, OSError) as exc:
            results.append(_needs_you(f.label, f"error: {type(exc).__name__}: {exc}"))
    flagged = sum(r.flagged for r in results)
    safety.log_action(conn, "read", page_url, f"answered {len(results)} fields, {flagged} flagged")
    return results
