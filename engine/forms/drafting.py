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

Reflective and story answers (:func:`reflect_answer`) are one free-written answer. A few things are HARD BLOCKS
(private data, a number or name not in your notes, assistant talk, an empty reply); everything else (stock phrases,
praise, long technology lists, ...) is a WARNING in the note and the answer is still given, flagged for your review.

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
from engine.profile import project_short_name
from engine.forms.reader import FormField
from engine.settings import ROOT, Settings

PROMPT_PATH = ROOT / "prompts" / "form.md"
DRAFTABLE_TYPES = frozenset({"text", "textarea"})  # the AI only writes into text boxes
FACT_COUNT = 4  # facts sent with each question
# (sentences, characters) when the page gives no limit of its own
_LIMITS = {"textarea": (4, 1200), "text": (1, 250)}
_REFLECT_LIMITS = {"textarea": (8, 1500), "text": (2, 300)}  # default box sizes; the sentence budget comes from the size
REFLECT_PROJECTS = 2  # the best-matching projects sent for a reflective question: two are enough, and fewer notes
# keep the answer focused
ABOUT_FIRST_LINES = 6  # about_me lines sent for a question about you (3 for other reflective questions)
SAME_RUN_WORDS = 6  # this many words in a row shared with an earlier answer on the form = "repeats wording"
EARLIER_CHARS = 350 # each earlier answer on the form is shown to the model cut at this length
MAX_FACT_CHARS = 1600  # one fact is cut here before it goes in a prompt

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
    hits = rag.retrieve(conn, label, FACT_COUNT * 4, sources=rag.FACT_SOURCES, settings=settings)
    return [h for h in hits if not rag.is_field_ref(h.ref)][:FACT_COUNT]  # the per-field pieces are for reflective answers


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


_PROJECT_FIELDS = rag.PROJECT_FIELDS  # (key, label) in the order an answer reads best
FIELDS_PER_PROJECT = 6  # the details of a project that match the question best (plus what started it)
SECOND_FIELD_WEIGHT = 0.3  # a project ranks by its best detail, plus this share of its second best
# Similarity cannot tell a one-line mistake from a real story ("A mistake is when..." echoes the question). Among the
# projects with a detail this close to the best match, the one with the richest (longest) close detail goes first.
RICHNESS_MARGIN = 0.08


def _stored_projects(conn: sqlite3.Connection | None) -> dict[str, dict]:
    """Your projects as saved from ``profile.json``, by name (empty when there is no database)."""
    if conn is None:
        return {}
    try:
        row = conn.execute("SELECT projects FROM profile WHERE id = 1").fetchone()
        return {p["name"]: p for p in json.loads(row[0])} if row else {}
    except (sqlite3.Error, ValueError, KeyError):
        return {}


def _project_text(project: dict, include_result: bool, keys: set[str] | None = None) -> str:
    """One project as ``What started it: ... Why I built it: ...`` from YOUR words, called by its SHORT name.

    ``keys`` limits it to those details (the ones closest to the question). No Solution, no tech list.
    """
    parts = [f"Project: {project_short_name(project)}."]
    tech = ", ".join(str(t) for t in project.get("tech", []) if str(t).strip())
    if tech:
        parts.append(f"Built with: {tech}.")  # so a reflection may name a tool you really used, and no other
    for key, label in _PROJECT_FIELDS:
        value = str(project.get(key) or "").strip()
        if value and (keys is None or key in keys):
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


def _shorten_hit(hit: rag.Hit, name: str, short: str) -> rag.Hit:
    """The same fact with the project called by its short name."""
    ref = short + (" (story)" if hit.ref.endswith("(story)") else "")
    return rag.Hit(hit.id, hit.source, ref, hit.text.replace(name, short), hit.score)


def gather_reflective_facts(
    conn: sqlite3.Connection,
    label: str,
    settings: Settings | None = None,
    *,
    count: int = REFLECT_PROJECTS,
    include_result: bool = False,
    about_first: bool = False,
) -> list[rag.Hit]:
    """Facts for a reflective question: the best ``count`` projects, plus your summary, skills, goals and own words.

    EVERY detail of EVERY project is scored against the question (each is its own chunk), so "tell me about a
    mistake" finds the project with the best mistake, not the one with the best summary. A project ranks by its best
    detail plus a share of its second best. Only ``count`` projects are sent, each with the details closest to the
    question (and what started it), never the Solution or the tech overview: with those in view a small model copies
    them into resume-style bullets. Projects are called by their SHORT name. ``include_result`` adds the measurable
    result (used for long answers). From the profile come the summary, skills, target roles, and the 3 ``about_me``
    lines closest to the question.

    ``about_first`` is for a question about YOU ("what makes you unique", "your strengths"): the answer should be
    about how you work, so the ``about_me`` lines come FIRST and there are more of them (:data:`ABOUT_FIRST_LINES`
    instead of 3). Projects are then only passing evidence.
    """
    hits = rag.retrieve(conn, label, 4096, sources=("project",), settings=settings)
    stored = _stored_projects(conn)
    by_short = {project_short_name(p): name for name, p in stored.items()}
    detail_scores: dict[str, dict[str, float]] = {}  # project -> {field key: similarity}
    detail_words: dict[str, dict[str, int]] = {}  # project -> {field key: words}
    scores: dict[str, list[float]] = {}
    pieces: dict[str, dict[str, rag.Hit]] = {}  # the old-style story / overview chunks, used when no details are indexed
    for hit in hits:
        if rag.is_field_ref(hit.ref):
            short, key = hit.ref.split(rag.FIELD_SEP, 1)
            name = by_short.get(short, short)
            detail_scores.setdefault(name, {})[key] = hit.score
            detail_words.setdefault(name, {})[key] = len(hit.text.split())
        else:
            name = _project_name(hit.ref)
            pieces.setdefault(name, {})["story" if hit.ref.endswith("(story)") else "overview"] = hit
        scores.setdefault(name, []).append(hit.score)

    def rank(name: str) -> float:
        ordered = sorted(scores[name], reverse=True)
        return ordered[0] + (SECOND_FIELD_WEIGHT * ordered[1] if len(ordered) > 1 else 0.0)

    top = max(max(values) for values in scores.values()) if scores else 0.0

    def richness(name: str) -> int:
        """Words in this project's longest detail that is about as close to the question as the best match."""
        close = [key for key, score in detail_scores.get(name, {}).items() if score >= top - RICHNESS_MARGIN]
        return max((detail_words[name][key] for key in close), default=0)

    near = [n for n in scores if max(scores[n]) >= top - RICHNESS_MARGIN]
    rest = [n for n in scores if n not in near]
    chosen = (sorted(near, key=lambda n: (-richness(n), -rank(n))) + sorted(rest, key=lambda n: -rank(n)))[:count]
    facts: list[rag.Hit] = []
    for name in chosen:
        detail = stored.get(name)
        short = project_short_name(detail) if detail else project_short_name(name)
        story = pieces.get(name, {}).get("story")
        filled = bool(detail) and any(str(detail.get(key) or "").strip() for key, _ in _PROJECT_FIELDS)
        if filled and name in detail_scores:
            ranked = sorted(detail_scores[name], key=lambda k: -detail_scores[name][k])
            keep = set(ranked[:FIELDS_PER_PROJECT]) | {"problem"}
            facts.append(rag.Hit(0, "project", f"{short} (story)", _project_text(detail, include_result, keep), rank(name)))
        elif filled:
            facts.append(rag.Hit(story.id if story else 0, "project", f"{short} (story)", _project_text(detail, include_result), rank(name)))
        elif story is not None:
            facts.append(_shorten_hit(_origin_only(story), name, short))
        elif "overview" in pieces.get(name, {}):
            facts.append(_shorten_hit(pieces[name]["overview"], name, short))
    if not facts:
        return []
    profile = rag.retrieve(conn, label, 40, sources=("profile",), settings=settings)
    about = [h for h in profile if h.ref.startswith("about:")][: ABOUT_FIRST_LINES if about_first else 3]
    basics = [h for h in profile if h.ref in ("summary", "skills", "preferences")]
    if about_first:
        return about + basics + facts  # how you work first, the projects last
    return facts + basics + about


# ---- checking a reply -------------------------------------------------------------------------------------

_AI_TALK = re.compile(r"\bas an ai\b|language model|\bi(?:'m| am) sorry\b|\bi (?:cannot|can't|can not)\b|\bas a (?:large|text)\b", re.I)
_FIRST_PERSON = re.compile(r"\bI\b|\b[Mm]y\b|\b[Mm]e\b|\b[Mm]yself\b")
_THIRD_PERSON = re.compile(r"\b(?:the applicant|the candidate|this applicant|he|she)\b", re.I)
# "I think ..." / "I believe ..." at the start of a sentence: a warning on reflective answers.
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
    r"\b(?:what started it|what was hard|why i built it|my part|key decision|what i learned|what i would change|proud of|how i got through it|a mistake and the fix|teamwork|timeline):", re.I
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
) -> DraftResult:
    """Accept the model's reply only if it passes every check. Returns an empty result with the reason otherwise."""
    answers = reply.get("answers", [])
    chosen = next((a for a in answers if _norm(a["field"]) == _norm(label)), None)
    if chosen is None and len(answers) == 1:
        chosen = answers[0]  # we asked one question, so one answer is that answer
    if chosen is None:
        return _rejected("the AI answered a different question")
    text = " ".join(chosen["answer"].split())
    if not text or chosen["confidence"] <= 0:
        return _rejected("the AI says your facts do not cover this question")

    _, default_chars = _LIMITS.get(field.type, _LIMITS["text"])
    max_chars = field.max_length or default_chars
    if len(text) > max_chars:
        return _rejected(f"the AI wrote {len(text)} characters but the box allows {max_chars}")
    if rag.scrub(text) != text:
        return _rejected("the AI included an email, phone or ID number")
    if _AI_TALK.search(text):
        return _rejected("the AI answered like an assistant, not an applicant")
    if not _FIRST_PERSON.search(text) or _THIRD_PERSON.search(text):
        return _rejected("not written in the first person")
    if not _source_ok(chosen["source"], facts, allow_saved):
        return _rejected(f"its source {chosen['source']!r} is not one of the facts it was given")
    allowed = " ".join([label, saved, *(h.text for h in facts)])
    number = _ungrounded_number(text, allowed)
    if number:
        return _rejected(f"the number {number} is not in your facts")
    name = _ungrounded_name(text, allowed)
    if name:
        return _rejected(f"{name!r} is not in your facts")
    return DraftResult(text, float(chosen["confidence"]), chosen["source"], "")


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


# ---- reflective and story answers ---------------------------------------------------------------------------
#
# The model writes ONE free answer from your notes. A few things are HARD BLOCKS (the answer is rejected): private
# data, a number or a name that is not in your notes, assistant talk, an empty reply. Everything else is only a
# WARNING shown in the note: you review every AI answer anyway, so the code does not delete or rewrite its sentences.

# Stock phrases an AI falls back on. A warning only.
_STOCK = re.compile(
    r"\bexcit\w*|\bthrill\w*|\beager\w*|\bpositive impact\b|\bmake a (?:real |positive )?(?:difference|impact)\b|"
    r"\bimpact on (?:people|users|others|lives)|\bpeople's lives\b|"
    r"\bthrough these projects\b|\bin today's\b|\bever-?changing\b|\bcutting-edge\b|"
    r"\bhigh-quality\b|\b(?:committed|dedicated) to\b|\btangible\b|\bwilling to take risks\b|"
    r"\bbring this mindset\b|\bcontinue to (?:learn|grow)\b|\blearn and grow\b|\bgrow as a\b|"
    r"\bmy examples\b|\bthese examples\b|\bthe examples (?:show|above)\b|\bthis project (?:started|began) with\b",
    re.I,
)
TECH_LIST_SIZE = 3  # a sentence naming this many of YOUR technologies reads like a resume line

# What the answer looks like. XYZ for a story or achievement question, reflection first for a question about you.
_SHAPE_STORY = (
    "Write it as one short paragraph about ONE project, in this order. (1) The impact: what you achieved or what "
    "happened, and the measurable result only if the notes give a number. (2) What you did to get there, or how you "
    "handled it when it went wrong. (3) One reflective sentence about what this shows about how you think, work or decide."
)
_SHAPE_ABOUT = (
    "This question is about YOU, not about a project. Write one short paragraph about how you work: how you think, "
    "decide and approach problems, using the notes about you first. Start by answering the question directly in one "
    "sentence. Then explain it from your way of working. A project may appear only as a short piece of evidence "
    "(one clause), never retold as a story. End with a reflective sentence about how you work or decide."
)


def _length_hint(budget: int) -> str:
    """How long to write, from the sentence budget of the box (a request: the code only warns when it is ignored)."""
    if budget >= 6:
        return f"Aim for about {budget - 3} to {budget} sentences. This box has room, so explain properly."
    if budget >= 3:
        return f"Aim for {budget - 1} to {budget} sentences."
    return f"Write {budget} sentence{'s' if budget > 1 else ''}. This box is small."


def _tech_terms(conn: sqlite3.Connection | None) -> set[str]:
    """The technologies named in your profile (project tech lists and skills), lower case."""
    if conn is None:
        return set()
    terms: set[str] = set()
    try:
        row = conn.execute("SELECT skills, projects FROM profile WHERE id = 1").fetchone()
        if row:
            terms.update(str(t) for t in json.loads(row[0] or "[]"))
            for project in json.loads(row[1] or "[]"):
                terms.update(str(t) for t in project.get("tech", []))
    except (sqlite3.Error, ValueError, TypeError, AttributeError):
        return set()
    return {t.lower().strip() for t in terms if len(t.strip()) >= 3}


def _shorten_names(text: str, shorten: dict[str, str]) -> str:
    """Call each project by its short name, whatever the model wrote ('CheatNoNo, Exam Integrity Platform' -> 'CheatNoNo')."""
    for full in sorted(shorten, key=len, reverse=True):
        text = re.sub(re.escape(full), shorten[full], text, flags=re.I)
    return text


def _fit_to_box(text: str, max_chars: int) -> tuple[str, bool]:
    """``text`` cut after the last whole sentence that fits ``max_chars``, and whether anything was cut."""
    if len(text) <= max_chars:
        return text, False
    kept = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        candidate = f"{kept} {sentence}".strip()
        if len(candidate) > max_chars:
            break
        kept = candidate
    return kept, True


def _answer_warnings(text: str, tech: set[str], allowed_sentences: int, section: str = "WRITE") -> list[str]:
    """Everything about a reflective answer that you may want to fix. None of these rejects the answer."""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s]
    found: list[str] = []
    stock = sorted({m.group(0).lower() for s in sentences if (m := _STOCK.search(s))})
    if stock:
        found.append("stock phrases (" + ", ".join(repr(s) for s in stock) + ")")
    praise = _PRAISE.search(text)
    if praise:
        found.append(f"praises you ({praise.group(0)!r})")
    overclaim = _OVERCLAIM.search(text)
    if overclaim:
        found.append(f"inflated word {overclaim.group(0)!r}")
    if any(sum(1 for term in tech if _contains(s, term)) >= TECH_LIST_SIZE for s in sentences):
        found.append("a list of technologies in one sentence")
    same = _repeated_opener(sentences)
    if same:
        found.append(f"three sentences start with {same!r}")
    hedges = sum(1 for s in sentences if _HEDGE_OPENER.match(s))
    if hedges:
        found.append(f"{hedges} sentence(s) start with 'I think' or 'I believe'")
    if len(sentences) > allowed_sentences:
        found.append(f"{len(sentences)} sentences, more than the {allowed_sentences} this box suggests")
    if not _FIRST_PERSON.search(text) or _THIRD_PERSON.search(text):
        found.append("not clearly in the first person")
    leaked = _FACT_LABEL.search(text)
    if leaked:
        found.append(f"repeats a note label ({leaked.group(0)!r})")
    if _copies_prompt(text, section):
        found.append("repeats wording from the prompt")
    return found


def _format_earlier(earlier: list[str]) -> str:
    """The answers already written on this form, one per line, each cut short, for the prompt."""
    lines = [f'- "{" ".join(text.split())[:EARLIER_CHARS]}"'.replace("\n", " ") for text in earlier if text.strip()]
    return "\n".join(lines) if lines else "(none yet)"


def _earlier_warnings(text: str, earlier: list[str], given: list[str]) -> list[str]:
    """Warnings when this answer sounds like one already on the form (never a rejection: you review every answer)."""
    found: list[str] = []
    runs = _word_runs(text, SAME_RUN_WORDS)
    if any(runs & _word_runs(other, SAME_RUN_WORDS) for other in earlier):
        found.append("repeats wording from another answer on this form")
    shared = [name for name in given if _mentions_project(text, name) and any(_mentions_project(o, name) for o in earlier)]
    if shared:
        found.append("uses the same project as another answer on this form (" + ", ".join(shared) + ")")
    return found


def reflect_answer(
    conn: sqlite3.Connection,
    field: FormField,
    saved: str = "",
    kind: str = "open",
    *,
    settings: Settings | None = None,
    single_project: bool = False,
    earlier: list[str] | None = None,
) -> DraftResult:
    """Answer a REFLECTIVE or STORY question ("what are your strengths", "tell me about a mistake").

    The best project(s) for the question are picked from ALL of them (:func:`gather_reflective_facts`) and the model
    writes one first-person answer from their notes: shaped as impact, what you did, then a reflection for a story
    question (``single_project``), or a direct answer, one or two real moments and a reflection for a question about
    you. It may reword the notes and add a reflective sentence, but no new fact: a number or a name that is not in
    the notes rejects the answer. ``saved`` is an optional ``open`` answer, treated as one more fact about you.
    ``DraftResult.note`` lists warnings (stock phrases, praise, ...) that do NOT reject the answer.

    A question about you (not ``single_project``) puts your ``about_me`` notes first: it should describe how you work.
    ``earlier`` is the open answers already written on the same form. They go into the prompt so the model avoids
    their wording and main project, and a repeat is only a warning.

    Raises:
        DraftError: the question is sensitive, a saved answer is not ``open``, or the field is not a text box.
    """
    if saved and kind != "open":
        raise DraftError(f"Only 'open' answers may be used here, not {kind!r}")
    _refuse_if_sensitive(field.label)
    if field.type not in DRAFTABLE_TYPES:
        raise DraftError(f"The AI only writes into text boxes, not {field.type!r} fields")
    sentences, chars = _limits_for(field, reflective=True)
    budget = int(sentences)
    earlier = earlier or []
    facts = gather_reflective_facts(
        conn, field.label, settings,
        count=1 if single_project else REFLECT_PROJECTS, include_result=True, about_first=not single_project,
    )
    if not any(h.source == "project" for h in facts):
        return _rejected("no projects found to draw from")
    prompt = load_prompt(
        "WRITE",
        question=" ".join(field.label.split()).replace('"', "'"),
        saved=" ".join(saved.split()).replace('"', "'"),
        facts=format_facts(facts),
        shape=_SHAPE_STORY if single_project else _SHAPE_ABOUT,
        length=_length_hint(budget),
        max_sentences=sentences,
        max_chars=chars,
        voice=_voice_notes(conn) or "(none given)",
        earlier=_format_earlier(earlier),
    )
    try:
        reply = ai.ask_ai("reflect_text", prompt, settings=settings)
    except (ai.AIError, NotImplementedError) as exc:
        return _rejected(f"AI unavailable: {exc}")

    stored = _stored_projects(conn)
    shorten = {name: project_short_name(p) for name, p in stored.items() if project_short_name(p) != name}
    text = _shorten_names(" ".join(reply["answer"].split()), shorten)
    if not text or reply["confidence"] <= 0:
        return _rejected("the AI says your projects do not support an answer to this question")
    text, cut = _fit_to_box(text, int(chars))
    if not text:
        return _rejected(f"even the first sentence is longer than the box ({chars} characters)")
    # Hard blocks.
    if rag.scrub(text) != text:
        return _rejected("the AI included an email, phone or ID number")
    if _AI_TALK.search(text):
        return _rejected("the AI answered like an assistant, not an applicant")
    allowed = " ".join([field.label, saved, *(h.text for h in facts)])
    number = _ungrounded_number(text, allowed)
    if number:
        return _rejected(f"the number {number} is not in your facts")
    name = _ungrounded_name(text, allowed)
    if name:
        return _rejected(f"{name!r} is not in your facts")
    # Warnings only.
    warnings = _answer_warnings(text, _tech_terms(conn), budget)
    if cut:
        warnings.append(f"cut after the last whole sentence that fits the {chars}-character box")
    given = sorted({_project_name(h.ref) for h in facts if h.source == "project"})
    warnings += _earlier_warnings(text, earlier, given)
    used =[n for n in given if _mentions_project(text, n)] or given
    return DraftResult(text, float(reply["confidence"]), "; ".join(used), "; ".join(warnings))


# ---- company answers ---------------------------------------------------------------------------------------
#
# "Why do you want to work here?" needs facts about the company, and the AI has none: a local model asked what it
# knows about a company will invent things. So the answer is built in two steps, and the AI only READS:
#
#   1. build_company_brief: the model copies notes (what they do, mission, values, duties) out of the job post.
#      Code then drops every note the post does not support, so the brief holds only what the post says.
#   2. company_answer: the model writes ONE first-person answer from the brief + your own notes. Code rejects a
#      reply that invents a fact, claims experience with the company ("I heard...") or carries private data.
#
# A post that says nothing about the company gives a "thin" brief, and the answer is about the ROLE instead.

BRIEF_POST_CHARS = 6000  # how much of the job post the brief step reads
BRIEF_MIN_SUPPORT = 0.6  # a note is kept when at least this share of its words appear in the post
BRIEF_QUOTE_CHARS = 200
_STEM = re.compile(r"[a-z0-9]{4,}")
# Claims of experience with the company. The AI cannot have any, so a reply with one is rejected.
_EXPERIENCE_CLAIM = re.compile(
    r"\bi(?:'ve| have)?\s+(?:heard|read|followed|seen|been following|used|tried|visited|looked at)\b|"
    r"\bfrom what i(?:'ve| have)?\s+(?:heard|know|read|saw|seen|gathered|understand)\b|"
    r"\bi(?:'ve| have)? (?:always )?(?:admired|known|loved|followed)\b|\bi know (?:that )?(?:you|your|they)\b|"
    r"\bi(?:'ve| have)? learned (?:about|that) (?:you|your)\b|\bi came across\b|\bi (?:read|saw|noticed) (?:that|your|about)\b",
    re.I,
)

_COMPANY_SHAPE_FULL = (
    "Write it as one short paragraph, in this order. (1) Start with the company: say what it does, in plain words, "
    "using COMPANY NOTES. (2) Say what about that appeals to you, as a short honest reaction to that specific thing "
    "(the mission, the initiative, the way they work), not as praise. (3) Connect it to me: one true thing from MY "
    "NOTES, for example that I like building things or a project I made, so the reader sees why I would fit. "
    "(4) Close with one short line that I would like to work with them toward the same goal. Promise no results. "
    "If the box has fewer sentences than steps, merge steps but keep the company first."
)
_COMPANY_SHAPE_ROLE = (
    "The post says little about the company, so write about the ROLE. Write one short paragraph, in this order. "
    "(1) Say what the job involves, using the role and duties in COMPANY NOTES, and why that kind of work interests me. "
    "(2) Connect it to me: one true thing from MY NOTES. (3) Close with one short line that I would like to contribute "
    "and grow in this role. Say nothing about what the company does, its mission, culture, size or reputation, because "
    "the post did not say. If the box has fewer sentences than steps, merge steps."
)


@dataclass(frozen=True)
class CompanyBrief:
    """What a job post says about the company and the role, after code has dropped anything the post does not support.

    ``dropped`` lists the notes the model produced that the post did not back (shown in the preview so you can see
    the model trying to invent something). ``thin`` means the post says nothing about what the company does.
    """

    company: str = ""
    role: str = ""
    what_they_do: str = ""
    mission: str = ""
    values: tuple[str, ...] = ()
    duties: tuple[str, ...] = ()
    quotes: tuple[str, ...] = ()
    dropped: tuple[str, ...] = ()

    @property
    def thin(self) -> bool:
        """True when the post says nothing about what the company does or stands for: answer about the role."""
        return not (self.what_they_do or self.mission or self.values)

    @property
    def usable(self) -> bool:
        """True when there is something to write about: the company, or at least the role."""
        return not self.thin or bool(self.role or self.duties)

    def notes(self) -> str:
        """The brief as the lines put in the answer prompt."""
        lines = [
            f"Company: {self.company}" if self.company else "",
            f"Role: {self.role}" if self.role else "",
            f"What they do: {self.what_they_do}" if self.what_they_do else "",
            f"Mission: {self.mission}" if self.mission else "",
            f"Values: {'; '.join(self.values)}" if self.values else "",
            f"Main duties: {'; '.join(self.duties)}" if self.duties else "",
        ]
        return "\n".join(line for line in lines if line) or "(the post says nothing usable)"


def _stems(text: str) -> set[str]:
    return {w[:5] for w in _STEM.findall(text.lower())}


def _supported(note: str, job_text: str, job_stems: set[str]) -> bool:
    """True if a note is backed by the post: most of its words are in the post, and no number or name is new."""
    stems = _stems(note)
    if not stems or len(stems & job_stems) / len(stems) < BRIEF_MIN_SUPPORT:
        return False
    return _ungrounded_number(note, job_text) is None and _ungrounded_name(note, job_text) is None


def _ground_brief(reply: dict, job_text: str) -> CompanyBrief:
    """Keep only the parts of the model's notes that the post backs; list the rest as ``dropped``."""
    job_stems = _stems(job_text)
    flat = _norm(job_text)
    dropped: list[str] = []

    def keep(note: object, label: str) -> str:
        text = " ".join(str(note or "").split())
        if not text:
            return ""
        if _supported(text, job_text, job_stems):
            return text
        dropped.append(f"{label}: {text}")
        return ""

    company = " ".join(str(reply.get("company") or "").split())
    if company and not _contains(job_text, company):
        dropped.append(f"company: {company}")
        company = ""
    quotes = []
    for quote in reply.get("quotes") or []:
        text = " ".join(str(quote).split())
        if text and len(text) <= BRIEF_QUOTE_CHARS and _norm(text) in flat:
            quotes.append(text)
        elif text:
            dropped.append(f"quote: {text}")
    return CompanyBrief(
        company=company,
        role=keep(reply.get("role"), "role"),
        what_they_do=keep(reply.get("what_they_do"), "what they do"),
        mission=keep(reply.get("mission"), "mission"),
        values=tuple(v for v in (keep(x, "value") for x in (reply.get("values") or [])[:3]) if v),
        duties=tuple(d for d in (keep(x, "duty") for x in (reply.get("duties") or [])[:3]) if d),
        quotes=tuple(quotes[:3]),
        dropped=tuple(dropped),
    )


def build_company_brief(job_text: str | None, settings: Settings | None = None) -> CompanyBrief | None:
    """Notes about the company and the role, read from the job post. ``None`` when there is nothing to read or the AI failed.

    The model only copies; :func:`_ground_brief` then removes everything the post does not say. The post must
    already be scrubbed of your private details (the orchestrator does that before any AI sees it, rule 3).
    """
    if not job_text or not job_text.strip():
        return None
    job_text = job_text[:BRIEF_POST_CHARS]
    prompt = load_prompt("BRIEF", post=job_text.strip())
    try:
        reply = ai.ask_ai("company_brief", prompt, settings=settings)
    except (ai.AIError, NotImplementedError):
        return None
    dumped = json.dumps(reply, ensure_ascii=False)
    if rag.scrub(dumped) != dumped:  # an email or phone number in the reply: do not use any of it
        return None
    return _ground_brief(reply, job_text)


def company_answer(
    conn: sqlite3.Connection,
    field: FormField,
    brief: CompanyBrief,
    saved: str = "",
    *,
    job_text: str = "",
    settings: Settings | None = None,
    earlier: list[str] | None = None,
) -> DraftResult:
    """Answer a "why do you want to work here?" question from the company brief and your own notes.

    A full brief gives: what the company does, why that appeals to you, one true thing about you, a shared-goal
    closing. A thin brief gives the same shape about the ROLE. ``saved`` is your saved open answer, used as one more
    note about you and for its voice. HARD BLOCKS (the answer is rejected): private data, a number or name that is in
    none of the notes or the post, assistant talk, a claim like "I heard...", an empty reply. Style problems are
    warnings in ``DraftResult.note``.

    Raises:
        DraftError: the question is sensitive or the field is not a text box.
    """
    _refuse_if_sensitive(field.label)
    if field.type not in DRAFTABLE_TYPES:
        raise DraftError(f"The AI only writes into text boxes, not {field.type!r} fields")
    if not brief.usable:
        return _rejected("the job post says nothing about the company or the role")
    sentences, chars = _limits_for(field, reflective=True)
    budget = int(sentences)
    earlier = earlier or []
    facts = gather_reflective_facts(
        conn, f"{brief.what_they_do} {brief.role} {field.label}".strip(), settings,
        count=1, include_result=False, about_first=True,
    )
    if not facts:
        return _rejected("no notes about you to connect the answer to")
    prompt = load_prompt(
        "COMPANY",
        question=" ".join(field.label.split()).replace('"', "'"),
        saved=" ".join(saved.split()).replace('"', "'"),
        brief=brief.notes(),
        facts=format_facts(facts),
        shape=_COMPANY_SHAPE_ROLE if brief.thin else _COMPANY_SHAPE_FULL,
        length=_length_hint(budget),
        max_sentences=sentences,
        max_chars=chars,
        voice=_voice_notes(conn) or "(none given)",
        earlier=_format_earlier(earlier),
    )
    try:
        reply = ai.ask_ai("reflect_text", prompt, settings=settings)
    except (ai.AIError, NotImplementedError) as exc:
        return _rejected(f"AI unavailable: {exc}")

    stored = _stored_projects(conn)
    shorten = {name: project_short_name(p) for name, p in stored.items() if project_short_name(p) != name}
    text = _shorten_names(" ".join(reply["answer"].split()), shorten)
    if not text or reply["confidence"] <= 0:
        return _rejected("the AI found nothing to say from the job post and your notes")
    text, cut = _fit_to_box(text, int(chars))
    if not text:
        return _rejected(f"even the first sentence is longer than the box ({chars} characters)")
    # Hard blocks.
    if rag.scrub(text) != text:
        return _rejected("the AI included an email, phone or ID number")
    if _AI_TALK.search(text):
        return _rejected("the AI answered like an assistant, not an applicant")
    claim = _EXPERIENCE_CLAIM.search(text)
    if claim:
        return _rejected(f"the AI claimed experience with the company ({claim.group(0)!r}), which it cannot have")
    allowed = " ".join([field.label, saved, brief.notes(), job_text, *(h.text for h in facts)])
    number = _ungrounded_number(text, allowed)
    if number:
        return _rejected(f"the number {number} is not in the job post or your notes")
    name = _ungrounded_name(text, allowed)
    if name:
        return _rejected(f"{name!r} is not in the job post or your notes")
    # Warnings only.
    warnings = _answer_warnings(text, _tech_terms(conn), budget, section="COMPANY")
    if brief.company and not _contains(text, brief.company):
        warnings.append(f"does not name the company ({brief.company})")
    if brief.thin:
        warnings.append("the post said little about the company, so this is about the role")
    if cut:
        warnings.append(f"cut after the last whole sentence that fits the {chars}-character box")
    warnings += _earlier_warnings(text, earlier, [])
    return DraftResult(text, float(reply["confidence"]), "job post + your notes", "; ".join(warnings))


# ---- relocation answers -------------------------------------------------------------------------------------
#
# The YES or NO is decided by code (engine/forms/jobpost.py). The model only words it. Whatever it writes must keep
# the stance, add no new place or number, and carry no private data; otherwise the plain sentence below is used.

_REFUSES = re.compile(
    r"\b(?:not|n't|unable|cannot|can't|unwilling|no)\b|\bnever\b", re.I
)
RELOCATION_SENTENCES = 2
RELOCATION_FALLBACK = {
    True: "Yes, that works for me: {reason}.",
    False: "No, I'm not able to relocate, but I can work remotely or on-site within Metro Manila.",
}


def plain_relocation_answer(yes: bool, reason: str) -> str:
    """The deterministic wording used when the AI is off, fails or breaks a rule."""
    return RELOCATION_FALLBACK[yes].format(reason=reason[:1].upper() + reason[1:])


def _relocation_facts(conn: sqlite3.Connection, label: str, settings: Settings | None) -> list[rag.Hit]:
    """Your preferences and the closest ``about_me`` lines: the only notes a relocation answer may use."""
    profile = rag.retrieve(conn, label, 40, sources=("profile",), settings=settings)
    return [h for h in profile if h.ref == "preferences"] + [h for h in profile if h.ref.startswith("about:")][:3]


def elaborate_relocation(
    conn: sqlite3.Connection,
    field: FormField,
    yes: bool,
    reason: str,
    *,
    settings: Settings | None = None,
) -> DraftResult:
    """Word a relocation answer whose YES/NO is already decided. Never rejects: falls back to a plain sentence.

    The returned ``note`` says why the plain sentence was used, if it was.

    Raises:
        DraftError: the field is not a text box (a radio or dropdown gets the plain Yes/No instead).
    """
    if field.type not in DRAFTABLE_TYPES:
        raise DraftError(f"The AI only writes into text boxes, not {field.type!r} fields")
    plain = plain_relocation_answer(yes, reason)  # YES: 'Yes, that works for me: the job is remote...'; NO: a fixed sentence
    facts = _relocation_facts(conn, field.label, settings)
    _, chars = _limits_for(field, reflective=True)
    prompt = load_prompt(
        "ELABORATE",
        stance="YES: relocating is not a problem for me, because no move is needed" if yes else "NO: I am not willing to relocate",
        reason=reason,
        question=" ".join(field.label.split()).replace('"', "'"),
        facts=format_facts(facts) or "(no notes)",
        max_sentences=str(RELOCATION_SENTENCES),
        max_chars=chars,
    )
    try:
        reply = ai.ask_ai("reflect_text", prompt, settings=settings)
    except (ai.AIError, NotImplementedError) as exc:
        return DraftResult(plain, 1.0, "rules", f"AI unavailable ({exc}): plain wording used")
    text = " ".join(str(reply.get("answer", "")).split())
    text, _ = _fit_to_box(text, int(chars))
    allowed = " ".join([field.label, reason, plain, *(h.text for h in facts)])
    problem = ""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s]
    if not text or float(reply.get("confidence", 0)) <= 0:
        problem = "the AI gave no answer"
    elif rag.scrub(text) != text:
        problem = "the AI included an email, phone or ID number"
    elif _AI_TALK.search(text):
        problem = "the AI answered like an assistant"
    elif _ungrounded_number(text, allowed) or _ungrounded_name(text, allowed):
        problem = f"{_ungrounded_number(text, allowed) or _ungrounded_name(text, allowed)!r} is not in your notes"
    elif yes and _REFUSES.search(sentences[0] if sentences else text) and not re.search(r"\b(?:don't|do not|doesn't|no) (?:need|have) to\b|\bno (?:move|need)\b", text, re.I):
        problem = "the reply sounds unwilling but the stance is yes"
    elif not yes and not _REFUSES.search(sentences[0] if sentences else text):
        problem = "the reply does not say no but the stance is no"
    elif not yes and re.match(r"\s*yes\b", text, re.I):
        problem = "the reply starts with yes but the stance is no"
    if problem:
        return DraftResult(plain, 1.0, "rules", f"{problem}: plain wording used")
    warnings = _STOCK.search(text)
    return DraftResult(text, float(reply["confidence"]), "preferences; about_me", f"stock phrase {warnings.group(0)!r}" if warnings else "")


# ---- short saved yes/no answers in a text box ---------------------------------------------------------------
#
# A saved answer of "Yes" is fine for a radio, but a free-text box ("Do you know Docker? Please explain") wants a
# reason. The YES or NO stays exactly as saved; the model only adds 1-2 sentences taken from your notes. Anything
# doubtful falls back to the saved text, which is what the engine used before elaboration existed.

ELABORATE_MAX_WORDS = 3  # a saved answer longer than this is a real answer, not a bare yes/no
ELABORATE_MIN_SCORE = 0.65  # a note must be at least this close to the question to be used (your choice, Nov 19)
ELABORATE_SENTENCES = 2
_YES_NO = re.compile(r"\s*(yes|no)\b", re.I)


def short_yes_no(saved: str) -> str | None:
    """``"yes"`` or ``"no"`` if the saved answer is a bare yes/no of at most 3 words ("Yes", "No, not yet"); else None."""
    words = saved.split()
    match = _YES_NO.match(saved)
    if not match or not 0 < len(words) <= ELABORATE_MAX_WORDS:
        return None
    return match.group(1).lower()


def _elaboration_problem(text: str, confidence: object, stance: str, allowed: str) -> str:
    """Why a reply cannot be used ("" if it is fine)."""
    if not text or not isinstance(confidence, (int, float)) or confidence <= 0:
        return "the AI gave no answer"
    if rag.scrub(text) != text:
        return "the AI included an email, phone or ID number"
    if _AI_TALK.search(text):
        return "the AI answered like an assistant"
    start = _YES_NO.match(text)
    if not start or start.group(1).lower() != stance:
        return f"the reply does not start with the saved {stance!r}"
    bad = _ungrounded_number(text, allowed) or _ungrounded_name(text, allowed)
    if bad:
        return f"{bad!r} is not in your notes"
    return ""


def elaborate_short(
    conn: sqlite3.Connection, field: FormField, saved: str, *, settings: Settings | None = None
) -> DraftResult:
    """Add 1-2 sentences of real reasons to a short saved yes/no, for a free-text box. Never rejects.

    The result's ``text`` is the elaboration when it is safe; otherwise it is ``saved`` unchanged and ``note``
    says why. ``source`` is ``"rules"`` for the fallback, else the notes used.

    Raises:
        DraftError: the field is not a text box, the question is sensitive, or ``saved`` is not a short yes/no.
    """
    _refuse_if_sensitive(field.label)
    if field.type not in DRAFTABLE_TYPES:
        raise DraftError(f"The AI only writes into text boxes, not {field.type!r} fields")
    stance = short_yes_no(saved)
    if stance is None:
        raise DraftError(f"Only a short yes/no is elaborated, not {saved!r}")

    def fallback(why: str) -> DraftResult:
        return DraftResult(saved, 1.0, "rules", f"{why}: saved answer used")

    try:
        facts = [h for h in gather_facts(conn, field.label, settings) if h.score >= ELABORATE_MIN_SCORE]
    except (rag.RagError, ai.AIError, sqlite3.Error) as exc:  # elaboration is optional: never worse than the saved answer
        return fallback(f"notes unavailable ({exc})")
    if not facts:
        return fallback("no notes close enough to this question")
    _, chars = _limits_for(field, reflective=True)
    prompt = load_prompt(
        "ELABORATE_SHORT",
        saved=" ".join(saved.split()).replace('"', "'"),
        question=" ".join(field.label.split()).replace('"', "'"),
        facts=format_facts(facts),
        max_sentences=str(ELABORATE_SENTENCES),
        max_chars=chars,
    )
    try:
        reply = ai.ask_ai("reflect_text", prompt, settings=settings)
    except (ai.AIError, NotImplementedError) as exc:
        return fallback(f"AI unavailable ({exc})")
    text, _ = _fit_to_box(" ".join(str(reply.get("answer", "")).split()), int(chars))
    problem = _elaboration_problem(text, reply.get("confidence", 0), stance, " ".join([field.label, saved, *(h.text for h in facts)]))
    if problem:
        return fallback(problem)
    used = sorted({_project_name(h.ref) if h.source == "project" else h.ref for h in facts})
    warning = _STOCK.search(text)
    return DraftResult(text, float(reply["confidence"]), "; ".join(used), f"stock phrase {warning.group(0)!r}" if warning else "")
