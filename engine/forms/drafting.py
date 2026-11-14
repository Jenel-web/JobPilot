"""The AI side of the answer engine: draft new answers and rewrite ``open`` ones, with guardrails.

``answers.py`` decides WHICH fields may use the AI. This file does the work and does not trust the
model. Layers of protection (each catches what the one before it missed):

1. The prompt (``prompts/form.md``): facts only, first person, no company claims, one good and one
   "cannot answer" example. A request, not a guarantee.
2. Only the question and the 4 closest facts are sent. Facts come from your profile, projects and
   resumes, already scrubbed of email, phone and address. Protected answers are never in a prompt.
3. Code checks every reply (:func:`check_reply`): right question, not empty, fits the box, no email
   or phone, first person, no "as an AI", the cited source is one we gave it, every number and every
   capitalised name appears in the facts, the saved answer or the question.
4. Any failed check gives an empty result with a reason; the caller shows it flagged for you.
5. The caller flags every AI-written answer and shows which fact it came from.

Defence in depth: :func:`draft_answer` and :func:`rewrite_open` refuse sensitive questions, and
refuse to rewrite ``fixed`` or ``protected`` answers, even if ``answers.py`` ever sent one by mistake.
All AI calls go through ``ai.ask_ai`` (CLAUDE.md rule 2).
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass

from engine import ai, rag
from engine.forms.reader import FormField
from engine.settings import ROOT, Settings

PROMPT_PATH = ROOT / "prompts" / "form.md"
DRAFTABLE_TYPES = frozenset({"text", "textarea"})  # the AI only writes into text boxes
FACT_COUNT = 4  # facts sent with each question
# (sentences, characters) when the page gives no limit of its own
_LIMITS = {"textarea": (4, 1200), "text": (1, 250)}
_REFLECT_LIMITS = {"textarea": (8, 1500), "text": (2, 300)}  # default box sizes; the sentence budget comes from the size
REFLECT_PROJECTS = 2  # the best-matching projects sent for a reflective question: two examples are enough, and
# fewer facts keep the answer short and the opinion in front
MAX_FACT_CHARS = 1600  # one fact is cut here before it goes in a prompt
_EXAMPLE_LENGTH_SHORT = (
    'ONE short sentence (about 25 words) naming the project and saying what started it or what was hard about it, in a '
    'normal spoken sentence (not "Project name: description", not a list). Do not list features or technologies.'
)
_EXAMPLE_LENGTH_FULL = (
    "TWO sentences (about 45 words) each: the first names the project, says what started it and why you built it; the "
    "second says what you did or decided, or what was hard or what you learned. Normal spoken sentences, not a list. "
    "Do not list features or technologies."
)
_DEPTH_SHORT = "Keep it tight: this box is small."
_DEPTH_FULL = (
    "THIS BOX HAS ROOM. Explain properly: give each example real substance (what you decided and why, not only what "
    "happened) and let the closing take two or three sentences."
)
MAX_EXAMPLES = 2  # examples in a reflective answer: the facts are the support, the closing is the point
MIN_CHARS_FOR_TWO_EXAMPLES = 400  # a smaller box only needs one project as evidence


class DraftError(Exception):
    """A programming mistake: the AI was asked to do something it must never do."""


@dataclass(frozen=True)
class DraftResult:
    """What came back. ``text`` is empty when nothing safe was produced; ``note`` says why."""

    text: str
    confidence: float
    source: str  # the fact the AI says it used, e.g. "project:EconLens PH"
    note: str

    @property
    def ok(self) -> bool:
        return bool(self.text)


def _rejected(note: str) -> DraftResult:
    return DraftResult("", 0.0, "none", note)


# ---- the prompt file ------------------------------------------------------------------------------


def load_prompt(section: str, **values: str) -> str:
    """Read one ``## SECTION`` of ``prompts/form.md`` and fill its ``{{placeholders}}``.

    Replacement happens in ONE pass, so text inside a value (a question that contains
    ``{{facts}}``) is never treated as a placeholder.

    Raises:
        DraftError: no such section, or a placeholder without a value.
    """
    try:
        text = PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise DraftError(f"Cannot read {PROMPT_PATH.name}: {exc}") from exc
    sections = dict(re.findall(r"^## (\w+)\s*\n(.*?)(?=^## |\Z)", text, flags=re.MULTILINE | re.DOTALL))
    if section not in sections:
        raise DraftError(f"{PROMPT_PATH.name} has no section {section!r} (has: {sorted(sections)})")

    def fill(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise DraftError(f"Prompt section {section} needs a value for {{{{{name}}}}}")
        return values[name]

    return re.sub(r"\{\{(\w+)\}\}", fill, sections[section]).strip()


# ---- facts ---------------------------------------------------------------------------------------------


def gather_facts(conn: sqlite3.Connection, label: str, settings: Settings | None = None) -> list[rag.Hit]:
    """The closest profile, project and resume chunks for ``label`` (already scrubbed of private data)."""
    return rag.retrieve(conn, label, FACT_COUNT, sources=rag.FACT_SOURCES, settings=settings)


def format_facts(hits: list[rag.Hit]) -> str:
    """One line per fact: ``[project:EconLens PH] Project: EconLens PH. ...`` (each cut at MAX_FACT_CHARS)."""
    return "\n".join(f"[{h.source}:{h.ref}] {h.text[:MAX_FACT_CHARS]}" for h in hits)


def _project_name(ref: str) -> str:
    """``'CheatNoNo (story)'`` -> ``'CheatNoNo'``."""
    return re.sub(r"\s*\(story\)$", "", ref).strip()


_STORY = re.compile(r"Project: (?P<name>.*?)\. Problem: (?P<problem>.*?) Solution: (?P<solution>.*?) Hardest part: (?P<hard>.*)", re.DOTALL)


def _origin_only(hit: rag.Hit) -> rag.Hit:
    """Rewrite a project story as ``What started it`` + ``What was hard`` (the Solution is dropped).

    If the story is not in the expected shape (a project saved without all three parts), it is kept as is.
    """
    match = _STORY.match(hit.text)
    if match is None:
        return hit
    text = f"Project: {match['name']}. What started it: {match['problem'].strip()} What was hard: {match['hard'].strip()}"
    return rag.Hit(hit.id, hit.source, hit.ref, text, hit.score)


_PROJECT_FIELDS = (
    ("problem", "What started it"),
    ("why_i_built_it", "Why I built it"),
    ("my_part", "My part"),
    ("key_decision", "Key decision"),
    ("hardest_part", "What was hard"),
    ("what_i_learned", "What I learned"),
    ("would_change", "What I would change"),
    ("proud_of", "Proud of"),
)


def _stored_projects(conn: sqlite3.Connection | None) -> dict[str, dict]:
    """Your projects as saved from ``profile.json``, by name (empty when there is no database)."""
    if conn is None:
        return {}
    try:
        row = conn.execute("SELECT projects FROM profile WHERE id = 1").fetchone()
        return {p["name"]: p for p in json.loads(row[0])} if row else {}
    except (sqlite3.Error, ValueError, KeyError):
        return {}


def _project_text(project: dict, include_result: bool) -> str:
    """One project as ``What started it: ... Why I built it: ...`` from YOUR words. No Solution, no tech list."""
    parts = [f"Project: {project['name']}."]
    for key, label in _PROJECT_FIELDS:
        value = str(project.get(key) or "").strip()
        if value:
            parts.append(f"{label}: {value if value[-1] in '.!?' else value + '.'}")
    result = str(project.get("result") or "").strip()
    if include_result and result:
        parts.append(f"Result: {result}")
    return " ".join(parts)


def _voice_notes(conn: sqlite3.Connection | None) -> str:
    """How you want to sound (``about_me.voice_notes``), or an empty string."""
    if conn is None:
        return ""
    try:
        row = conn.execute("SELECT about_me FROM profile WHERE id = 1").fetchone()
        return str(json.loads(row[0] or "{}").get("voice_notes", "")).strip() if row else ""
    except (sqlite3.Error, ValueError, AttributeError):
        return ""


def gather_reflective_facts(
    conn: sqlite3.Connection,
    label: str,
    settings: Settings | None = None,
    *,
    count: int = REFLECT_PROJECTS,
    include_result: bool = False,
) -> list[rag.Hit]:
    """Facts for a reflective question: the best ``count`` projects, plus your summary, skills, goals and own words.

    Every project is considered (so the best ones for THIS question are chosen), but only ``count`` are sent, so
    the prompt fits the model's context on this PC. Each project is shown as what started it, why you built it, your
    part, a key decision, what was hard and what you learned (whatever you filled in), never the Solution or the tech
    overview: with those in view a small model copies them into resume-style bullets. ``include_result`` adds the
    measurable result (used for long answers). From the profile come the summary, skills, target roles, and the 3
    ``about_me`` lines closest to the question.
    """
    hits = rag.retrieve(conn, label, 64, sources=("project",), settings=settings)
    by_project: dict[str, dict[str, rag.Hit]] = {}
    best: dict[str, float] = {}
    for hit in hits:
        name = _project_name(hit.ref)
        kind = "story" if hit.ref.endswith("(story)") else "overview"
        by_project.setdefault(name, {})[kind] = hit
        best[name] = max(best.get(name, 0.0), hit.score)
    chosen = sorted(best, key=lambda n: -best[n])[:count]
    stored = _stored_projects(conn)
    facts: list[rag.Hit] = []
    for name in chosen:
        story = by_project[name].get("story")
        detail = stored.get(name)
        if detail and any(str(detail.get(key) or "").strip() for key, _ in _PROJECT_FIELDS):
            score = best[name]
            facts.append(rag.Hit(story.id if story else 0, "project", f"{name} (story)", _project_text(detail, include_result), score))
        elif story is not None:
            facts.append(_origin_only(story))
        else:
            facts.append(by_project[name]["overview"])
    if not facts:
        return []
    profile = rag.retrieve(conn, label, 40, sources=("profile",), settings=settings)
    about = [h for h in profile if h.ref.startswith("about:")][:3]  # the 3 closest of your own-words lines
    return facts + [h for h in profile if h.ref in ("summary", "skills", "preferences")] + about


# ---- checking a reply -------------------------------------------------------------------------------------

_AI_TALK = re.compile(r"\bas an ai\b|language model|\bi(?:'m| am) sorry\b|\bi (?:cannot|can't|can not)\b|\bas a (?:large|text)\b", re.I)
_FIRST_PERSON = re.compile(r"\bI\b|\b[Mm]y\b|\b[Mm]e\b|\b[Mm]yself\b")
_THIRD_PERSON = re.compile(r"\b(?:the applicant|the candidate|this applicant|he|she)\b", re.I)
# "I think ..." / "I believe ..." at the start of a sentence: removed from reflective answers (see _drop_hedge_openers).
_HEDGE_OPENER = re.compile(r"^(?:I think|I believe|I feel|I guess|I'd say|I would say)(?: that)?,?\s+", re.I)
_OVERCLAIM = re.compile(
    r"\b(?:always|never|every time|everyone|definitely|obviously|passionate|passion|obsessed|expert|world-class|best)\b", re.I
)
# Self-praise ("demonstrates my ability", "capable") is a CV line, not a reflection. Checked on the closing only.
_PRAISE = re.compile(
    r"\bdemonstrat\w*|\bmy ability\b|\bcapable\b|\bcapability\b|\bproficien\w*|\bskilled\b|\bexpertise\b|"
    r"\bshine\w*|\bexcel\w*|\bskills and experience\b",
    re.I,
)
# The labels the facts are written with ("What started it: ..."). They must never appear in an answer.
_FACT_LABEL = re.compile(
    r"\b(?:what started it|what was hard|why i built it|my part|key decision|what i learned|what i would change|proud of):", re.I
)
_NUMBER = re.compile(r"\d[\d,.]*\d|\d")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]*")


def _norm(text: str) -> str:
    return " ".join(text.lower().split()).rstrip(".?! ")


def _contains(haystack: str, needle: str) -> bool:
    """Whole-token containment, case-insensitive: 'react' is in 'I used React.' but not in 'reactive'."""
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(needle)}(?![A-Za-z0-9])", haystack, re.IGNORECASE) is not None


def _ungrounded_number(text: str, allowed: str) -> str | None:
    for number in _NUMBER.findall(text):
        if not re.search(rf"(?<![\d.]){re.escape(number)}(?!\d)", allowed):
            return number
    return None


# Ordinary words that may start a clause after a colon. Any other capitalised word there is still checked.
_STARTERS = frozenset(
    "this that these those it its we our us my i the a an for when after before since because with in on at as and but so "
    "now then here there what how why who which while during once if although though however".split()
)


def _ungrounded_name(text: str, allowed: str) -> str | None:
    """A capitalised word (not the first of its sentence, not "I") that is nowhere in the allowed text."""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        for position, match in enumerate(_WORD.finditer(sentence)):
            word = match.group(0).rstrip(".-")
            if position == 0 or word == "I" or not word[:1].isupper():
                continue
            after_colon = sentence[: match.start()].rstrip().endswith(":")
            if after_colon and word.lower() in _STARTERS:
                continue  # "CheatNoNo: This began..." is a new clause; "CheatNoNo: Kubernetes began..." is still checked
            if not _contains(allowed, word):
                return word
    return None


COPY_RUN_WORDS = 7  # this many words in a row, shared with the prompt, count as copying it


def _word_runs(text: str, size: int) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {tuple(words[i : i + size]) for i in range(len(words) - size + 1)}


def _copies_prompt(text: str, section: str) -> bool:
    """True if the answer repeats a run of words from the prompt's own text (not from the facts).

    A small model will parrot a worked example if it is given one (it did, word for word), and what it
    parrots is not about you. The raw prompt section is compared, before the question and facts are filled in.
    """
    try:
        template = PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        return False
    match = re.search(rf"^## {section}\s*\n(.*?)(?=^## |\Z)", template, flags=re.MULTILINE | re.DOTALL)
    return bool(match) and bool(_word_runs(text, COPY_RUN_WORDS) & _word_runs(match.group(1), COPY_RUN_WORDS))


def _repeated_opener(sentences: list[str]) -> str:
    """The first two words that start three or more sentences ("i build"), or "" if the openers vary."""
    openers = [" ".join(re.findall(r"[a-z']+", s.lower())[:2]) for s in sentences]
    for opener in dict.fromkeys(o for o in openers if o):
        if openers.count(opener) >= 3:
            return opener
    return ""


def _first_sentences(text: str, limit: int) -> str:
    """The first ``limit`` sentences of ``text``: a model ignores a sentence count, so the code enforces it."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(sentences[:limit])


def _drop_hedge_openers(text: str) -> str:
    """Remove a leading "I think / I believe / I feel (that)" from every sentence, then capitalise.

    The model overuses these ("I think... I think..."), and you wanted a confident, direct voice.
    """
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        sentence = _HEDGE_OPENER.sub("", sentence, count=1)
        out.append(sentence[:1].upper() + sentence[1:])
    return " ".join(s for s in out if s.strip())


_COLON_EXAMPLE = re.compile(r"^(?P<name>[^:]{3,90}):\s+(?P<rest>(?:I|I'm|I'd|I've|We|My|Our|For|When|After|Before|Since|This|That|It|The)\b.*)$", re.DOTALL)


def _natural_example(text: str, project_names: list[str]) -> str:
    """``'MJ Cinema: I had just learned Spring Boot.'`` -> ``'With MJ Cinema, I had just learned Spring Boot.'``

    Models like to write "Project name: description", which reads like a list. It is only rewritten when the
    part after the colon already starts with a person ("I", "we", "my"...), so the new sentence stays grammatical.
    """
    match = _COLON_EXAMPLE.match(text)
    if match is None or not any(_mentions_project(match["name"], n) for n in project_names):
        return text
    rest = match["rest"]
    first_word = rest.split(" ", 1)[0]
    if first_word not in ("I", "I'm", "I'd", "I've"):
        rest = rest[:1].lower() + rest[1:]
    return f"With {match['name'].strip()}, {rest}"


def _mentions_project(text: str, name: str) -> bool:
    """Does the answer name this project? Accepts the full name, the part before a comma, or its first words."""
    first_part = re.split(r"[,:]", name)[0].strip()
    words = first_part.split()
    aliases = {name, first_part, " ".join(words[:2])}
    if words and len(words[0]) >= 5:
        aliases.add(words[0])
    return any(alias and _contains(text, alias) for alias in aliases)


def _source_ok(source: str, facts: list[rag.Hit], allow_saved: bool) -> bool:
    """The cited source must be one of the facts we sent (or 'saved answer' for a rewrite)."""
    low = source.lower()
    if allow_saved and "saved" in low:
        return True
    for hit in facts:
        names = {hit.ref.lower(), re.sub(r"\s*\(story\)|#\d+$", "", hit.ref).strip().lower()}
        if any(name and name in low for name in names):
            return True
    return False


def check_reply(
    reply: dict,
    label: str,
    facts: list[rag.Hit],
    *,
    field: FormField,
    saved: str = "",
    allow_saved: bool = False,
    reflective: bool = False,
) -> DraftResult:
    """Accept the model's reply only if it passes every check. Returns an empty result with the reason otherwise.

    ``reflective`` adds three checks: a humble reflective voice ("I think..."), no overclaiming words,
    and evidence (the answer names enough of the projects it was given).
    """
    answers = reply.get("answers", [])
    chosen = next((a for a in answers if _norm(a["field"]) == _norm(label)), None)
    if chosen is None and len(answers) == 1:
        chosen = answers[0]  # we asked one question, so one answer is that answer
    if chosen is None:
        return _rejected("the AI answered a different question")
    text = " ".join(chosen["answer"].split())
    if not text or chosen["confidence"] <= 0:
        return _rejected("the AI says your facts do not cover this question")

    _, default_chars = (_REFLECT_LIMITS if reflective else _LIMITS).get(field.type, _LIMITS["text"])
    max_chars = field.max_length or default_chars
    if len(text) > max_chars and (field.max_length or not reflective):
        return _rejected(f"the AI wrote {len(text)} characters but the box allows {max_chars}")
    if rag.scrub(text) != text:
        return _rejected("the AI included an email, phone or ID number")
    if _AI_TALK.search(text):
        return _rejected("the AI answered like an assistant, not an applicant")
    if not _FIRST_PERSON.search(text) or _THIRD_PERSON.search(text):
        return _rejected("not written in the first person")
    if not _source_ok(chosen["source"], facts, allow_saved):
        return _rejected(f"its source {chosen['source']!r} is not one of the facts it was given")
    if reflective:
        if _copies_prompt(text, "REFLECT"):
            return _rejected("the answer repeats wording from the prompt instead of your projects")
        leaked = _FACT_LABEL.search(text)
        if leaked:
            return _rejected(f"the answer repeats an internal label ({leaked.group(0)!r}) instead of speaking naturally")
        overclaim = _OVERCLAIM.search(text)
        if overclaim:
            return _rejected(f"overclaims with {overclaim.group(0)!r}")
        sentences = re.split(r"(?<=[.!?])\s+", text)
        allowed_sentences = int(_limits_for(field, reflective=True)[0])
        if len(sentences) > allowed_sentences:
            return _rejected(f"{len(sentences)} sentences but at most {allowed_sentences} (too much fact, too little view)")
        same = _repeated_opener(sentences)
        if same:
            return _rejected(f"three or more sentences start the same way ({same!r})")

    allowed = " ".join([label, saved, *(h.text for h in facts)])
    number = _ungrounded_number(text, allowed)
    if number:
        return _rejected(f"the number {number} is not in your facts")
    name = _ungrounded_name(text, allowed)
    if name:
        return _rejected(f"{name!r} is not in your facts")
    source = chosen["source"]
    if reflective:
        given = sorted({_project_name(h.ref) for h in facts if h.source == "project"})
        used = [n for n in given if _mentions_project(text, n)]
        needed = min(2, len(given)) if max_chars >= MIN_CHARS_FOR_TWO_EXAMPLES else 1
        if len(used) < needed:
            return _rejected(f"it names {len(used)} of your projects as evidence but {needed} are needed")
        source = "; ".join(used)  # the projects the answer really uses, found by code, not claimed by the AI
    return DraftResult(text, float(chosen["confidence"]), source, "")


# ---- the two jobs -------------------------------------------------------------------------------------------


def _sentence_budget(max_chars: int) -> int:
    """How many sentences a box of this size can hold: small boxes stay tight, big ones get room to explain."""
    for limit, sentences in ((150, 1), (400, 2), (800, 4), (1200, 6)):
        if max_chars < limit:
            return sentences
    return 8


def _limits_for(field: FormField, reflective: bool = False) -> tuple[str, str]:
    """``(max sentences, max characters)`` for this field, as the strings the prompt needs."""
    sentences, chars = (_REFLECT_LIMITS if reflective else _LIMITS).get(field.type, _LIMITS["text"])
    max_chars = field.max_length or chars
    if reflective:
        sentences = _sentence_budget(max_chars)
    elif max_chars < 150:
        sentences = 1
    return str(sentences), str(max_chars)


def _end_sentence(text: str) -> str:
    """Trim and make sure the part ends with a full stop, so the joined answer reads as sentences (and counts as them)."""
    text = " ".join(text.split())
    return text if not text or text[-1] in ".!?" else text + "."


def _refuse_if_sensitive(label: str) -> None:
    from engine.forms.answers import is_sensitive  # imported here: answers.py imports this file

    if is_sensitive(label):
        raise DraftError(f"Refusing to use the AI for a sensitive question: {label!r}")


def _run(section: str, conn: sqlite3.Connection, field: FormField, saved: str, settings: Settings | None) -> DraftResult:
    facts = gather_facts(conn, field.label, settings)
    if not facts:
        return _rejected("no facts found in your profile, projects or resumes")
    sentences, chars = _limits_for(field)
    prompt = load_prompt(
        section,
        question=" ".join(field.label.split()).replace('"', "'"),
        saved=" ".join(saved.split()).replace('"', "'"),
        facts=format_facts(facts),
        max_sentences=sentences,
        max_chars=chars,
    )
    try:
        reply = ai.ask_ai("form_answer", prompt, settings=settings)
    except (ai.AIError, NotImplementedError) as exc:
        return _rejected(f"AI unavailable: {exc}")
    return check_reply(reply, field.label, facts, field=field, saved=saved, allow_saved=section == "REWRITE")


def draft_answer(conn: sqlite3.Connection, field: FormField, *, settings: Settings | None = None) -> DraftResult:
    """Draft an answer to a NEW, non-sensitive question from your facts. Returns an empty result if unsafe.

    Raises:
        DraftError: the question is sensitive or the field is not a text box (the caller must not ask).
    """
    _refuse_if_sensitive(field.label)
    if field.type not in DRAFTABLE_TYPES:
        raise DraftError(f"The AI only writes into text boxes, not {field.type!r} fields")
    return _run("DRAFT", conn, field, "", settings)


def rewrite_open(
    conn: sqlite3.Connection, field: FormField, saved: str, kind: str, *, settings: Settings | None = None
) -> DraftResult:
    """Adapt a saved ``open`` answer to this form's wording. Returns an empty result if unsafe.

    Raises:
        DraftError: the answer is not ``open`` (fixed and protected are never rewritten), the question
            is sensitive, or the field is not a text box.
    """
    if kind != "open":
        raise DraftError(f"Only 'open' answers may be rewritten, not {kind!r}")
    _refuse_if_sensitive(field.label)
    if field.type not in DRAFTABLE_TYPES:
        raise DraftError(f"The AI only writes into text boxes, not {field.type!r} fields")
    return _run("REWRITE", conn, field, saved, settings)


def reflect_answer(
    conn: sqlite3.Connection,
    field: FormField,
    saved: str = "",
    kind: str = "open",
    *,
    settings: Settings | None = None,
    single_project: bool = False,
) -> DraftResult:
    """Answer a REFLECTIVE question ("what are your strengths", "how do you decide what to build").

    The AI reads the story of your 3 best-matching projects and may state an OPINION about the pattern it
    sees, in a humble first-person voice. New conclusions are allowed, new facts are not: the usual checks
    still apply, plus the voice, overclaiming and evidence checks of :func:`check_reply`. ``saved`` is an
    optional ``open`` answer, treated as one more fact about you. ``single_project`` is for story questions
    ("describe a project / a challenge"): only the best project is sent and only one example is allowed.

    Raises:
        DraftError: the question is sensitive, a saved answer is not ``open``, or the field is not a text box.
    """
    if saved and kind != "open":
        raise DraftError(f"Only 'open' answers may be used here, not {kind!r}")
    _refuse_if_sensitive(field.label)
    if field.type not in DRAFTABLE_TYPES:
        raise DraftError(f"The AI only writes into text boxes, not {field.type!r} fields")
    max_examples = 1 if single_project else MAX_EXAMPLES
    sentences, chars = _limits_for(field, reflective=True)
    full = int(sentences) >= 6  # a big box: room to explain properly, with the measurable result as a fact
    facts = gather_reflective_facts(conn, field.label, settings, count=max_examples, include_result=full)
    if not any(h.source == "project" for h in facts):
        return _rejected("no projects found to draw a pattern from")
    prompt = load_prompt(
        "REFLECT",
        question=" ".join(field.label.split()).replace('"', "'"),
        saved=" ".join(saved.split()).replace('"', "'"),
        facts=format_facts(facts),
        max_sentences=sentences,
        max_chars=chars,
        max_examples=str(max_examples),
        example_length=_EXAMPLE_LENGTH_FULL if full else _EXAMPLE_LENGTH_SHORT,
        depth=_DEPTH_FULL if full else _DEPTH_SHORT,
        voice=_voice_notes(conn) or "(none given)",
    )
    try:
        reply = ai.ask_ai("reflect_answer", prompt, settings=settings)
    except (ai.AIError, NotImplementedError) as exc:
        return _rejected(f"AI unavailable: {exc}")

    clean = lambda text: _end_sentence(_drop_hedge_openers(text))  # noqa: E731  ("I think..." openers removed, full stops added)
    stance, closing = clean(reply["stance"]), clean(reply["closing"])
    examples = [clean(e) for e in reply["examples"] if e.strip()]
    # Cut to the box instead of rejecting: stance 1 sentence, each example 1 (small box) or 2 (big box), closing the rest.
    budget = int(sentences)
    per_example = 2 if budget >= 8 else 1
    keep = min(len(examples), max_examples, max(0, (budget - 2) // per_example))  # leave room for a stance and a closing
    stance = _first_sentences(stance, 1)
    examples = [_first_sentences(e, per_example) for e in examples[:keep]]
    closing = _first_sentences(closing, max(1, budget - 1 - per_example * len(examples)))
    if reply["confidence"] <= 0 or not (stance or closing):
        return _rejected("the AI says your projects do not support an answer to this question")
    if not stance or not closing:
        return _rejected("the answer is missing its stance or its closing (the part that answers the question)")
    examples = examples[:max_examples]  # the model lists its best fit first, so extra examples are simply dropped
    names = sorted({_project_name(h.ref) for h in facts if h.source == "project"})
    examples = [_natural_example(e, names) for e in examples]
    if _PRAISE.search(closing):
        return _rejected("the closing praises you instead of saying how you choose and what you do")
    # Join the three parts and run the same checks as every other answer (grounding, voice, length, evidence).
    joined = {"answers": [{
        "field": field.label, "answer": " ".join([stance, *examples, closing]),
        "confidence": reply["confidence"], "source": "project:" + ";".join(_project_name(h.ref) for h in facts if h.source == "project"),
    }]}
    return check_reply(joined, field.label, facts, field=field, saved=saved, allow_saved=bool(saved), reflective=True)
