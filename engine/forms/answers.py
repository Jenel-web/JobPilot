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

import dataclasses
import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Literal

from engine import learning, safety
from engine.forms import drafting, jobpost
from engine.forms.reader import FormField
from engine.profile import lookup_answer
from engine.rag import RagError
from engine.settings import Settings

PersonalKey = Literal[
    "first_name", "middle_name", "middle_initial", "last_name", "full_name",
    "email", "phone", "address", "location", "city", "country",
    "linkedin", "github", "portfolio",
    "school", "degree", "education_level", "year_level", "grad_year", "skills",
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

# Education and skills, from the profile. Checked BEFORE the "someone else's details" words below, because those
# include "school" and "university" (a school's email is not yours, but "School" alone asks for your school).
# Whole-label patterns only, so "School email" or "Course you are applying for" never match.
_EDUCATION_PATTERNS: list[tuple[PersonalKey, re.Pattern[str]]] = [
    ("school", re.compile(r"^(name of (your )?)?(current |last )?(school|university|college|institution|alma mater)( name| attended)?$")),
    ("degree", re.compile(r"^(course( of study)?|degree( program(me)?)?|program(me)?( of study)?|major|field of study|area of study|course name|degree name)$")),
    ("education_level", re.compile(r"^(highest )?(education(al)? level|level of education|education(al)? attainment|highest (level of )?education|education)$")),
    ("year_level", re.compile(r"^(current )?year level$|^year of study$")),
    ("grad_year", re.compile(r"^(expected |anticipated )?(graduation|grad)( year| date)?$|^(expected )?year of graduation$")),
    ("skills", re.compile(r"^(technical |key |relevant )?skills?( set)?$")),
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

# A dropdown of country calling codes ("Country Phone Code", "Phone code", "Dialing code"). Checked BEFORE the
# "someone else's details" words, which contain "code" (so referral, promo and verification codes stay not personal).
_PHONE_CODE = re.compile(r"^(country )?(phone |calling |dial(l)?ing )(country )?code$|^country code$")
# "Phone Device Type" / "Type of phone": Mobile, Home or Work (Workday). Answered from your number only.
_PHONE_TYPE = re.compile(r"\b(phone|device|number) (device )?type\b|\btype of (phone|number|device)\b")
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
# Wide on purpose: forms word opinion questions in many ways, and a question this list misses falls back to
# the strict fact-only prompt, which answered "Why do you like software engineering?" with a list of skills.
REFLECTIVE_PATTERN = re.compile(
    r"\bstrengths?\b|"
    r"\bhow (?:do|did|would|have|can) you (?!hear|find out|know about)|"
    r"\bwhy (?:do|did|would|are|have) you\b|"
    r"\bwhat (?:motivates|drives|inspires|excites|interests|got|made|makes) you\b|"
    r"\bwhat (?:do|did|would) you (?:enjoy|like|love|care about|value|find|think|hope|consider)\b|"
    r"\bwhat (?:is|are|was) your (?:biggest |greatest |main |top )?(?:strengths?|goals?|passions?|interests?|motivation|approach|philosophy|favou?rite)\b|"
    r"\bwhat (?:kind|type|sort) of (?:apps?|projects?|problems?|work|software|developer|engineer)\b|"
    r"\b(?:about|describe|introduce) yourself\b|\bwho are you\b|"
    r"\bwhere do you see yourself\b|\bcareer goals?\b|\blong[- ]term goals?\b|"
    r"\bgood fit\b|\bwhat makes you\b|"
    r"\banything else\b|"
    r"\bexplain (?:what|how|why)\b|"
    r"\byour (?:approach|philosophy|process) to\b"
)

# A STORY question asks for one example told well ("describe a project / a challenge / a time when").
# It gets the reflective treatment too, but with only the single best project.
STORY_PATTERN = re.compile(
    r"\b(?:describe|tell us about|tell me about|share|give an example of) (?:a|an|one|the) "
    r"(?:project|time|situation|challenge|problem|experience|accomplishment|achievement)\b|"
    r"\b(?:biggest|greatest) (?:challenge|accomplishment|achievement|project)\b|"
    r"\bmost (?:challenging|difficult|impressive|significant) (?:project|challenge|thing)\b|"
    r"\bproud of\b|\ba time (?:when|you)\b"
)

# Company questions need the job post. With one, the AI reads a company brief from it and writes (or adapts your
# saved answer) from that brief; without one, a saved open answer is used as written, otherwise the field is left
# for you.
COMPANY_PATTERN = re.compile(
    r"\bwhy (?:do|would|did) you want to (?:work|join)\b|\bwhy (?:us|this (?:company|role|position|job)|our (?:company|team))\b|"
    r"\bwhy are you (?:interested|applying)\b|\bwhy (?:did|do) you apply\b|"
    r"\bwhat (?:attracts|interests|excites|draws) you (?:about|to) (?:us|this|our|the (?:company|role|position))\b|"
    r"\bwhy do you want this (?:job|role|position|internship)\b|"
    r"\bwhat (?:do you know|can you tell us) about (?:us|our (?:company|team)|this (?:company|organi[sz]ation))\b|"
    r"\bwhat do you (?:like|admire) about (?:us|our (?:company|team)|this (?:company|organi[sz]ation))\b|"
    r"\btell us why you (?:want to (?:work|join)|are (?:interested|applying))\b"
)


def is_company_question(label: str) -> bool:
    """True if the question asks why you want THIS company or role (answered from the job post's company brief)."""
    return bool(COMPANY_PATTERN.search(_words(label)))


def is_reflective(label: str) -> bool:
    """True if the question asks for your own view (strengths, why you like it, how you decide, what drives you)."""
    words = _words(label)
    return bool(REFLECTIVE_PATTERN.search(words)) and not COMPANY_PATTERN.search(words)


def is_story(label: str) -> bool:
    """True if the question asks for one example told well (a project, a challenge, a time when...)."""
    return bool(STORY_PATTERN.search(_words(label)))


_QUESTION_START = re.compile(
    r"^(why|what|how|which|who|where|when|describe|tell|explain|share|list|give|briefly|in what|"
    r"do|did|does|are|is|have|has|can|could|would|will|should)\b"
)
FACT_LABEL_WORDS = 8  # a label this short with no question in it names a fact ("Previous Company"), not a question


def is_fact_label(label: str) -> bool:
    """True if a short box asks for a FACT ("Previous / Current Company", "Designation"), not a question.

    Facts come from your profile or your saved answers. The AI never drafts them: a guessed company or job title
    would be a made-up fact (CLAUDE.md rule 4). A real question ("Why do you want to join us?") is not a fact.
    """
    raw = label.strip()
    words = _words(raw)
    if not words or raw.endswith("?"):
        return False
    return len(words.split()) <= FACT_LABEL_WORDS and not _QUESTION_START.match(words)


def wants_opinion(label: str) -> bool:
    """Reflective or story: the answer is built from your projects with a reflective closing (not a fact lookup)."""
    return is_reflective(label) or is_story(label)


def detect_personal(field: FormField) -> tuple[PersonalKey, str] | None:
    """Return ``(which profile value, which hint said so)``, or ``None`` if not a personal field."""
    if field.type not in _PERSONAL_TYPES:
        return None
    label = _words(field.label)
    if field.type != "textarea":
        for key, pattern in _EDUCATION_PATTERNS:
            if pattern.search(label):
                return key, "label"
    if field.type in _CHOICE_TYPES and _PHONE_CODE.search(label):
        return "phone", "label"  # the country-code box beside the number (fill_personal picks your country's code)
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
        "school": row["school"] or "",
        "degree": row["degree"] or "",
        "education_level": education_level(row["degree"] or ""),
        "year_level": row["year_level"] or "",
        "grad_year": str(row["grad_year"] or ""),
        "skills": ", ".join(str(skill) for skill in _json_list(row["skills"])),
    }


def _json_list(text: str | None) -> list[object]:
    try:
        value = json.loads(text or "[]")
    except ValueError:
        return []
    return value if isinstance(value, list) else []


def education_level(degree: str) -> str:
    """The level of a degree, in the words forms use: "Bachelor of Science in IT" -> "Bachelor's Degree".

    Decided from words in YOUR degree, never guessed: an unknown degree gives "" (you choose).
    """
    words = " ".join(re.sub(r"[^a-z0-9]+", " ", degree.lower()).split())  # plain words: "PhD" stays one word
    if re.search(r"\b(phd|doctor\w*|doctorate)\b", words):
        return "Doctorate"
    if re.search(r"\b(master\w*|mba|msc)\b", words):
        return "Master's Degree"
    if re.search(r"\b(bachelor\w*|bs|bsc|ba|ab)\b", words):
        return "Bachelor's Degree"
    if re.search(r"\bassociate\w*\b", words):
        return "Associate's Degree"
    return ""


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


_OPTION_STOP = frozenset({"of", "in", "the", "and", "a", "an", "for", "at", "to", "on"})


def _option_key(text: str) -> str:
    """Compare options by words only: "Bachelor's Degree" == "bachelors degree"; "R&D" == "r and d"."""
    text = text.lower().replace("&", " and ").replace("'", "").replace("’", "")
    return " ".join(re.sub(r"[^a-z0-9+]+", " ", text).split())


def _option_tokens(text: str) -> set[str]:
    return {t for t in _option_key(text).split() if t not in _OPTION_STOP}


def pick_option(value: str, options: list[str]) -> str:
    """The option that matches ``value``, or "" when none does or two fit equally well (it never guesses).

    In order:
        1. the same words ("Bachelor's Degree" for "bachelors degree")
        2. a yes/no answer picks the "Yes"/"No" option ("No, I do not need a visa" -> "No")
        3. the option whose words are all in the answer, or whose words hold all of the answer:
           "Philippines" for "Mandaluyong, Metro Manila, Philippines", "Information Technology" for
           "Bachelor of Science in Information Technology". The most specific one wins; a tie gives "".
    Words, not letters: "Java" never matches "JavaScript".
    """
    want = _option_key(value)
    if not want:
        return ""
    for option in options:
        if _option_key(option) == want:
            return option
    stance = re.match(r"^(yes|no)\b", want)
    if stance:
        same = [o for o in options if _option_key(o) == stance.group(1)]
        if len(same) == 1:
            return same[0]
    want_tokens = _option_tokens(value)
    scored: list[tuple[float, str]] = []
    for option in options:
        tokens = _option_tokens(option)
        if not tokens or len(_option_key(option)) < 3:
            continue
        if tokens <= want_tokens:  # every word of the option is in the answer
            scored.append((len(tokens), option))
        elif want_tokens <= tokens and len(tokens) - len(want_tokens) <= 3:  # the option is the answer plus a little
            scored.append((len(want_tokens) - 0.1 * (len(tokens) - len(want_tokens)), option))
    if not scored:
        return ""
    scored.sort(key=lambda pair: -pair[0])
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return ""  # two options fit equally well: you choose
    return scored[0][1]


def _same_meaning(option: str, value: str) -> bool:
    """True if the option says the same as the value, or as one comma part of it.

    Codes and numbers are ignored: "Philippines (+63)" says "Philippines". "Philippines" also says the same as
    "Mandaluyong, Metro Manila, Philippines" (it is one part of it). Used to decide whether a pick needs a look.
    """
    def words(text: str) -> set[str]:
        return {t for t in _option_tokens(text) if not re.fullmatch(r"[+\d]+", t)}

    target = words(option)
    return bool(target) and any(target == words(part) for part in [value, *value.split(",")])


def country_code_option(stored: str, options: list[str]) -> str:
    """The country-code option for your number ("Philippines +63" for +63 917...), or "" if none fits for sure."""
    digits = re.sub(r"\D", "", stored)
    if (digits.startswith("63") and len(digits) == 12) or (digits.startswith("0") and len(digits) == 11):
        codes = ["63"]  # a Philippine mobile number (the same rule as format_phone)
    elif stored.strip().startswith("+"):
        codes = [digits[:3], digits[:2], digits[:1]]
    else:
        return ""
    for code in codes:
        found = [o for o in options if re.search(rf"\+\s?{code}(?!\d)", o)]
        if len(found) == 1:
            return found[0]
    return ""


def bare_phone(stored: str) -> str:
    """Your number without the country code (9171234567), for a number box next to a country-code dropdown."""
    digits = re.sub(r"\D", "", stored)
    if digits.startswith("63") and len(digits) == 12:
        return digits[2:]
    if digits.startswith("0") and len(digits) == 11:
        return digits[1:]
    return stored


def is_ph_mobile(stored: str) -> bool:
    """True for a Philippine MOBILE number (09XX... or +639XX..., 10 digits after the 0 / +63). Landlines are False."""
    digits = re.sub(r"\D", "", stored)
    return (digits.startswith("639") and len(digits) == 12) or (digits.startswith("09") and len(digits) == 11)


def phone_type_fill(stored: str, field: FormField, signal: str) -> PersonalFill:
    """A "Phone Device Type" dropdown: "Mobile" for a Philippine mobile number. Anything else is left for you.

    Decided by code from your ONE stored number, never guessed: a landline could be Home or Work, so it stays empty.
    """
    if not is_ph_mobile(stored):
        return PersonalFill("phone", "", signal, True, "phone device type: your number is not a mobile number, so choose it yourself")
    option = pick_option("Mobile", field.options) or pick_option("Cell", field.options) or pick_option("Cellphone", field.options)
    if not option:
        return PersonalFill("phone", "", signal, True, "phone device type: no Mobile option in the list")
    return PersonalFill("phone", option, signal, False, "a mobile number: Mobile")


def fill_personal(field: FormField, values: dict[str, str]) -> PersonalFill | None:
    """Recognise a personal field and decide its value. ``None`` means "not personal": try the answer bank."""
    found = detect_personal(field)
    if found is None:
        return None
    key, signal = found
    value = values.get(key, "")
    flagged = False
    note = ""
    if not value and key == "portfolio" and values.get("github"):  # a developer's GitHub is a fair website answer
        value, flagged, note = values["github"], True, "no portfolio saved: your GitHub is used"
    if not value:
        return PersonalFill(key, "", signal, True, f"no {key.replace('_', ' ')} in your profile")
    if key == "phone" and field.type in _CHOICE_TYPES and _PHONE_TYPE.search(_words(field.label)):
        return phone_type_fill(value, field, signal)
    if key == "phone" and field.type in _CHOICE_TYPES:  # the country-code box next to the number
        option = country_code_option(value, field.options)
        if not option:
            return PersonalFill(key, "", signal, True, "country code: no option matches your number's country")
        return PersonalFill(key, option, signal, False, "country code from your number")
    if key == "phone":
        value, note = format_phone(value, field)
    if key == "skills" and field.type in _CHOICE_TYPES:
        # Every skill, in your order: the filler searches the list for each one and picks exact matches only.
        return PersonalFill(key, value, signal, False, "your skills, in the order of your profile")
    if field.type in _CHOICE_TYPES and field.options:
        option = pick_option(value, field.options)
        if option:
            exact = _same_meaning(option, value)
            return PersonalFill(key, option, signal, flagged or not exact, note or ("matching option" if exact else f"closest option to your {key.replace('_', ' ')}: check it"))
        if field.custom_index < 0:
            return PersonalFill(key, "", signal, True, f"none of the {len(field.options)} options matches your {key.replace('_', ' ')}")
        # A custom dropdown often shows only part of a long list: the filler searches it for your value.
        return PersonalFill(key, value, signal, True, f"not in the visible part of the list: it will be searched for ({key.replace('_', ' ')})")
    return PersonalFill(key, value, signal, flagged, note)


# ---- the answer engine -----------------------------------------------------------------------

AnswerSource = Literal["personal", "bank", "draft", "resume", "none"]


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


UNSUPPORTED_NOTE = "a control JobPilot cannot fill (slider, rich-text box or switch): fill it yourself"


def _needs_you(label: str, note: str, unknown_id: int | None = None) -> FieldAnswer:
    """An empty, flagged field: you fill it yourself."""
    return FieldAnswer(label, "", "none", True, note, unknown_id=unknown_id)


_RESUME_FILE = re.compile(r"\b(resume|cv|curriculum vitae)\b")
_COVER_LETTER = re.compile(r"\bcover letter\b")
_GENERIC_FILE = re.compile(r"(attach|attachment|upload|choose|browse|select|add)( a| your)?( file| files| document)?")


def file_answer(field: FormField, has_job_post: bool) -> FieldAnswer:
    """Decide a ``file`` field: say which file is wanted. The engine never picks or opens a file itself.

    * Resume / CV: ``source="resume"`` with an empty value. In Phase 4 the filler uploads the file the
      resume picker chose from the job post. Flagged while there is no job post to pick from.
    * A bare "Attach" / "Upload": probably the resume, but it could be anything, so it is a flagged guess.
    * Cover letter, photo, anything else: you upload it yourself (nothing to upload yet).

    File fields are never looked up in the answer bank and never added to the unknown questions list:
    no saved text can fill a file input.
    """
    words = _words(field.label)
    if _COVER_LETTER.search(words):
        return _needs_you(field.label, "cover letter file: needs you (nothing to upload yet)")
    if _RESUME_FILE.search(words):
        if has_job_post:
            return FieldAnswer(field.label, "", "resume", False, "resume upload: the picker chooses A or B from the job post")
        return FieldAnswer(field.label, "", "resume", True, "resume upload: needs a job post to pick the resume (Phase 4)")
    if _GENERIC_FILE.fullmatch(words):
        return FieldAnswer(
            field.label, "", "resume", True, "guess: a bare attach button, probably the resume; check what it asks for"
        )
    return _needs_you(field.label, "file upload: needs you (only the resume is uploaded by the bot)")


EARLIER_MIN_WORDS = 15 # an answer this long counts as "already said" for the next open question on the form

RELOCATION_PATTERN = re.compile(r"\brelocat\w*|\bwilling to move\b|\bmove (?:to|for) (?:this|the|a)\b")


def is_relocation_question(label: str) -> bool:
    """True if the question asks whether you would relocate / move for the job."""
    return bool(RELOCATION_PATTERN.search(_words(label))) and not is_sensitive(label)


def wants_relocation_stance(field: FormField, job_text: str | None) -> bool:
    """True when the yes/no for this question is decided from the job's location.

    ``job_text is None`` means no job post was given at all, so the saved answers (with their location scope)
    work as before. ``""`` means a post was given but showed no location: that is "unknown", and unknown is NO.
    """
    return job_text is not None and is_relocation_question(field.label)


def _relocation_answer(
    conn: sqlite3.Connection, field: FormField, job_text: str, job_scope: str, job_city: str, settings: Settings | None
) -> FieldAnswer:
    """Decide yes/no from where the job is (code), then let the AI word it in a text box. Always flagged."""
    location = jobpost.read_job_location(job_text, scope=job_scope, city=job_city)
    stance = jobpost.relocation_stance(location)
    word = "YES" if stance.yes else "NO"
    where = f"found {location.evidence!r} in the job post" if location.evidence else "no Metro Manila place or remote wording found, so NO"
    if field.type not in drafting.DRAFTABLE_TYPES:
        value = pick_option("Yes" if stance.yes else "No", field.options) if field.options else ("Yes" if stance.yes else "No")
        return FieldAnswer(field.label, value, "bank", True, f"relocation: {word} decided from the job location ({where})")
    result = drafting.elaborate_relocation(conn, field, stance.yes, stance.reason, settings=settings)
    note = f"relocation: {word} decided from the job location ({where}); the AI only worded it, check it" + _warning_text(result.note)
    return FieldAnswer(field.label, result.text, "draft", True, note, confidence=result.confidence)


def answer_field(
    conn: sqlite3.Connection,
    field: FormField,
    values: dict[str, str],
    *,
    job_scope: str = "any",
    job_city: str = "",
    page_url: str = "",
    settings: Settings | None = None,
    earlier: list[str] | None = None,
    job_text: str | None = None,
    record: bool = True,
    brief_cache: dict[str, drafting.CompanyBrief | None] | None = None,
) -> FieldAnswer:
    """Decide the answer for ONE field. Reads and decides only: nothing is typed or clicked.

    Args:
        values: your personal values (:func:`profile_values`).
        job_scope / job_city: where the job is, so the right location-scoped answer is used.
        page_url: remembered with unknown questions and suggested wordings.
        earlier: long answers already written on this form, so a new open answer does not repeat them.
        job_text: the job post's text. A relocation question is answered YES or NO from where the job is
            (:mod:`engine.forms.jobpost`); ``None`` means no job post was given (saved answers are used as before).
        record: False for a preview: nothing is written to the unknown questions list or the suggested wordings.
        brief_cache: the company brief read from ``job_text``, shared by every company question on one form so the
            post is only read once (:func:`answer_form` passes one in).

    Raises:
        learning.LearningError, rag.RagError, sqlite3.Error: the lookup failed
            (:func:`answer_form` turns these into a flagged field).
    """
    if field.needs_you:
        return _needs_you(field.label, "no readable label: needs you")

    if field.type == "file":
        return file_answer(field, has_job_post=bool(job_text))

    if field.type == "unsupported":  # a slider, rich-text box or switch: the bot cannot fill it, so it never asks or saves
        return _needs_you(field.label, UNSUPPORTED_NOTE)

    personal = fill_personal(field, values)
    if personal is not None:
        return FieldAnswer(
            field.label, personal.value, "personal", personal.flagged,
            personal.note, confidence=1.0 if personal.value else 0.0,
        )

    if wants_relocation_stance(field, job_text):
        return _relocation_answer(conn, field, job_text or "", job_scope, job_city, settings)

    triage = learning.triage_question(
        conn, field.label, page_url=page_url, field_type=field.type, options=tuple(field.options), settings=settings,
        record=record,
    )
    hit = triage.match.hit
    row = lookup_answer(conn, hit.ref, job_scope=job_scope, job_city=job_city) if hit is not None else None
    score = hit.score if hit is not None else 0.0

    if triage.outcome == "matched" and row is not None:
        if row["kind"] == "open" and field.type in drafting.DRAFTABLE_TYPES and not is_sensitive(field.label):
            if is_company_question(field.label):
                return _company_answer(
                    conn, field, row, score, hit.ref if hit else "", None, job_text, settings, earlier, brief_cache
                )
            return _rewritten_answer(conn, field, row, score, settings, earlier)
        if wants_elaboration(field, row["kind"], row["answer"]):
            return _elaborated_answer(conn, field, row, score, settings)
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
    if field.type == "text" and is_fact_label(field.label):
        return _needs_you(
            field.label, "a fact about you that is not saved: add it to your answers (the AI never guesses facts)", triage.unknown_id
        )
    if is_company_question(field.label):
        return _company_answer(conn, field, None, 0.0, "", triage.unknown_id, job_text, settings, earlier, brief_cache)
    if wants_opinion(field.label):
        draft = drafting.reflect_answer(
            conn, field, settings=settings, single_project=is_story(field.label), earlier=earlier
        )
        kind_of_note = "AI interpretation (an opinion drawn from your projects, edit freely)"
    else:
        draft = drafting.draft_answer(conn, field, settings=settings)
        kind_of_note = "AI draft"
    if draft.ok:
        return FieldAnswer(
            field.label, draft.text, "draft", True,
            f"{kind_of_note} from {draft.source}: check it before submitting" + _warning_text(draft.note),
            confidence=draft.confidence, unknown_id=triage.unknown_id,
        )
    return _needs_you(field.label, f"AI draft rejected: {draft.note}", triage.unknown_id)


def _company_brief(
    job_text: str, settings: Settings | None, cache: dict[str, drafting.CompanyBrief | None] | None
) -> drafting.CompanyBrief | None:
    """The brief for this post, built once per form: later company questions reuse it (a failure is reused too)."""
    if cache is None:
        return drafting.build_company_brief(job_text, settings)
    if job_text not in cache:
        cache[job_text] = drafting.build_company_brief(job_text, settings)
    return cache[job_text]


def _company_answer(
    conn: sqlite3.Connection,
    field: FormField,
    row: sqlite3.Row | None,
    score: float,
    matched: str,
    unknown_id: int | None,
    job_text: str | None,
    settings: Settings | None,
    earlier: list[str] | None,
    brief_cache: dict[str, drafting.CompanyBrief | None] | None,
) -> FieldAnswer:
    """"Why do you want to work here?": written from the job post's company brief, your saved answer (if any) as a note.

    Every way this can fall short ends the same: your saved text as written (flagged) when there is one, else an empty
    flagged field for you. The AI never fills a gap with something it knows about the company.
    """

    def fall_back(why: str) -> FieldAnswer:
        if row is not None:
            return _saved_open(field, row, score, f"company question: saved text used as written ({why})")
        return _needs_you(field.label, f"company question: {why}, so answer it yourself", unknown_id)

    if not job_text:
        return fall_back("needs the job post and none was found")
    brief = _company_brief(job_text, settings, brief_cache)
    if brief is None or not brief.usable:
        return fall_back("the job post says nothing about the company or the role")
    draft = drafting.company_answer(
        conn, field, brief, row["answer"] if row is not None else "", job_text=job_text, settings=settings, earlier=earlier
    )
    if not draft.ok:
        return fall_back(f"AI draft rejected: {draft.note}")
    basis = "your saved answer adapted to this company" if row is not None else "written from the job post"
    return FieldAnswer(
        field.label, draft.text, "draft", True,
        f"company answer, {basis} ({'role only' if brief.thin else 'company brief'}): check it before submitting"
        + _warning_text(draft.note),
        kind=row["kind"] if row is not None else "", confidence=draft.confidence,
        matched_question=matched, unknown_id=unknown_id,
    )


def _warning_text(note: str) -> str:
    """The checks that did not reject an AI answer but that you may want to fix, as a sentence for the note."""
    return f". Warnings: {note}" if note else ""


def _rewritten_answer(
    conn: sqlite3.Connection,
    field: FormField,
    row: sqlite3.Row,
    score: float,
    settings: Settings | None,
    earlier: list[str] | None = None,
) -> FieldAnswer:
    """A matched ``open`` answer, adapted to this form's wording by the AI (flagged). Falls back to the saved text."""
    reflective = wants_opinion(field.label)
    if reflective:
        result = drafting.reflect_answer(
            conn, field, row["answer"], row["kind"], settings=settings, single_project=is_story(field.label),
            earlier=earlier,
        )
    else:
        result = drafting.rewrite_open(conn, field, row["answer"], row["kind"], settings=settings)
    common = {"kind": row["kind"], "confidence": score, "matched_question": row["question"]}
    if result.ok and reflective:
        note = f"AI interpretation of your saved answer and projects ({result.source}): an opinion drawn from your data, edit freely" + _warning_text(result.note)
        return FieldAnswer(field.label, result.text, "bank", True, note, **common)
    if result.ok:
        note = f"open answer rewritten for this question (from {result.source}): check it"
        return FieldAnswer(field.label, result.text, "bank", True, note, **common)
    note = f"AI rewrite not used ({result.note}): saved text used"
    return FieldAnswer(field.label, row["answer"], "bank", True, note, **common)


EXPERIENCE_PATTERN = re.compile(
    r"\b(?:familiar\w*|experienc\w*|knowledg\w*|proficien\w*|skilled|exposure|hands[- ]on|understand\w*|know)\b"
    r"|\bworked (?:with|on)\b|\bhave you (?:ever )?(?:used|built|developed|worked)\b"
)


def is_experience_question(label: str) -> bool:
    """True if the question asks about your knowledge or experience ("Do you have experience with Docker?").

    Logistics and willingness questions ("Are you open to hybrid?", "Do you have your own laptop?") are not:
    their plain Yes/No is already the right answer, and project notes would only add noise.
    """
    return bool(EXPERIENCE_PATTERN.search(_words(label)))


def wants_elaboration(field: FormField, kind: str, saved: str) -> bool:
    """True for a ``fixed`` bare yes/no (3 words or fewer) to an experience/knowledge question, in a free-text box.

    Radios and dropdowns get the plain answer; ``protected`` and ``open`` answers and sensitive questions
    (work authorization, GPA, "have you ever"...) are never expanded.
    """
    return (
        kind == "fixed"
        and field.type in drafting.DRAFTABLE_TYPES
        and not is_sensitive(field.label)
        and is_experience_question(field.label)
        and drafting.short_yes_no(saved) is not None
    )


def _elaborated_answer(
    conn: sqlite3.Connection, field: FormField, row: sqlite3.Row, score: float, settings: Settings | None
) -> FieldAnswer:
    """A short saved yes/no with 1-2 sentences of real reasons from your notes (flagged).

    If nothing safe came back, the plain saved answer is used, unflagged, exactly as before elaboration existed.
    """
    result = drafting.elaborate_short(conn, field, row["answer"], settings=settings)
    common = {"kind": row["kind"], "confidence": score, "matched_question": row["question"]}
    if result.source == "rules":
        return FieldAnswer(field.label, row["answer"], "bank", False, f"not elaborated ({result.note})", **common)
    note = f"saved {row['answer']!r} elaborated from your notes ({result.source}): check it" + _warning_text(result.note)
    return FieldAnswer(field.label, result.text, "bank", True, note, **common)


def _pick(field: FormField, saved: str) -> str:
    """The saved text for a text box; for a list of options, the option that matches it ("" if none)."""
    if field.type in _GROUP_TYPES and field.options:
        if field.multi:  # "Prosple, Friends": each part is one choice
            parts = [p.strip() for p in re.split(r"[,;\n]+", saved) if p.strip()]
            # A custom dropdown may show only part of its list: a part not in view is kept, and the filler searches it.
            keep = (lambda part: pick_option(part, field.options) or part) if field.custom_index >= 0 else (lambda part: pick_option(part, field.options))
            picked = list(dict.fromkeys(p for p in map(keep, parts) if p))
            return ", ".join(picked)
        option = pick_option(saved, field.options)
        if not option and field.custom_index >= 0:
            return saved  # a custom dropdown may show only part of its list: the filler searches it
        return option
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
    if field.type in _GROUP_TYPES and field.options and any(
        part.strip() not in field.options for part in (value.split(",") if field.multi else [value])
    ):
        return make(value, True, "your saved answer is not in the visible part of the list: it will be searched for")
    if kind == "protected":
        return make(value, True, "protected: used exactly as saved, never sent to the AI")
    if kind == "open":
        # Only reached for non-text fields or sensitive questions: the AI is not used, so the saved text, flagged.
        return make(value, True, "open answer: saved text, check it fits")
    return make(value, False, "")


def preview_company_answer(
    conn: sqlite3.Connection,
    job_text: str,
    question: str = "Why do you want to work here?",
    *,
    settings: Settings | None = None,
    max_length: int | None = None,
) -> tuple[drafting.CompanyBrief | None, FieldAnswer]:
    """What the engine would write for a company question on this job post, without any form. Saves nothing.

    Runs the real path (:func:`answer_field` with ``record=False``), so a saved answer that matches the question is
    adapted exactly as in a fill. Returns the brief too, so you can check it against the post.
    """
    field = FormField(label=question, type="textarea", max_length=max_length or 0)
    cache: dict[str, drafting.CompanyBrief | None] = {}
    answer = answer_field(
        conn, field, profile_values(conn), job_text=job_text, settings=settings, record=False, brief_cache=cache
    )
    return cache.get(job_text), answer


def answer_form(
    conn: sqlite3.Connection,
    fields: list[FormField],
    *,
    job_scope: str = "any",
    job_city: str = "",
    page_url: str = "",
    settings: Settings | None = None,
    job_text: str | None = None,
    record: bool = True,
    brief_cache: dict[str, drafting.CompanyBrief | None] | None = None,
) -> list[FieldAnswer]:
    """Answer every field, in page order. One failing field never stops the others.

    ``record=False`` makes it a preview: unknown questions and suggested wordings are not saved.
    ``brief_cache`` is the company brief already built for ``job_text`` (``{job_text: brief}``); without one the
    brief is built when the first company question needs it.

    Logs one ``read`` row to ``action_log`` (a count only: values can hold phone or email).
    """
    values = profile_values(conn)
    results: list[FieldAnswer] = []
    earlier: list[str] = []  # long open answers written so far on this page, so the next one sounds different
    briefs = brief_cache if brief_cache is not None else {}  # the company brief, read once for the whole form
    for f in fields:
        try:
            answer = answer_field(
                conn, f, values, job_scope=job_scope, job_city=job_city, page_url=page_url, settings=settings,
                earlier=list(earlier), job_text=job_text, record=record, brief_cache=briefs,
            )
            results.append(answer)
            if answer.source in ("draft", "bank") and len(answer.value.split()) >= EARLIER_MIN_WORDS:
                earlier.append(answer.value)
        except (learning.LearningError, drafting.DraftError, RagError, sqlite3.Error, RuntimeError, ValueError, OSError) as exc:
            results.append(_needs_you(f.label, f"error: {type(exc).__name__}: {exc}"))
    _pair_phone_boxes(fields, results, values)
    flagged = sum(r.flagged for r in results)
    safety.log_action(conn, "read", page_url, f"answered {len(results)} fields, {flagged} flagged")
    return results


def _pair_phone_boxes(fields: list[FormField], results: list[FieldAnswer], values: dict[str, str]) -> None:
    """A phone number box that sits next to a country-code dropdown (same label) gets the number WITHOUT the code."""
    code_boxes = {
        f.label for f, r in zip(fields, results)
        if f.type in _CHOICE_TYPES and r.source == "personal" and r.note == "country code from your number"
    }
    for i, (f, r) in enumerate(zip(fields, results)):
        if f.type not in _CHOICE_TYPES and r.source == "personal" and f.label in code_boxes and values.get("phone"):
            found = detect_personal(f)
            if found and found[0] == "phone":
                results[i] = dataclasses.replace(r, value=bare_phone(values["phone"]), note="number without the country code (chosen in the box next to it)")
