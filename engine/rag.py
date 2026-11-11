"""RAG: split your data into chunks, embed them, and find the chunks closest to a question.

How it works, in four steps
---------------------------
1. **Chunk.** ``build_chunks()`` cuts your profile, projects, resumes and answer
   bank into small pieces of text, each tagged with where it came from.
2. **Embed.** ``reindex()`` turns every chunk into a vector with ``ai.embed()``
   (``nomic-embed-text`` through Ollama) and stores it with ``sqlite-vec``.
3. **Retrieve.** ``retrieve(question)`` embeds the question and asks ``sqlite-vec``
   for the chunks whose vectors are nearest (cosine similarity).
4. The *answer engine* (Phase 3, next step) decides what to do with the hits.

Privacy by design (CLAUDE.md rules 3, 4 and 5b)
-----------------------------------------------
* Phone, email, address and ID numbers never become chunks: the profile chunks
  leave them out, and resume text is scrubbed before it is cut.
* The GPA is never a chunk (it is answered only from the answer bank).
* An **answer chunk holds only a QUESTION wording**, never the answer. The answer
  stays in the ``answers`` table and is looked up by question text, so even a
  ``protected`` answer is never embedded or placed in a prompt.
* Each saved question gets one chunk for itself and one per alternate wording
  (``also_asked_as`` in answers.json). Search returns each saved question at
  most once (its best wording), and answers that differ only by location
  (Metro Manila vs remote) share those chunks. The caller picks the right
  variant with ``profile.lookup_answer(question, job_scope=..., job_city=...)``.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass

from engine import ai
from engine.settings import Settings, load_settings

SOURCES = ("profile", "project", "resume", "answer")

FACT_SOURCES = ("profile", "project", "resume")

# nomic-embed-text works best when the text says what role it plays:
# * question vs saved question is a SYMMETRIC comparison (two texts of the same
#   kind), so both sides get "clustering: ". Tested on the eval set: 10/11 saved
#   questions ranked first, against 7/11 with the search prefixes.
# * question vs facts (projects, resumes) is a SEARCH (short query, longer
#   documents), so those use "search_query: " and "search_document: ".
_ANSWER_PREFIX = "clustering: "
_DOC_PREFIX = "search_document: "
_QUERY_PREFIX = "search_query: "

# Bump when the way chunks are embedded changes, so an old index is rebuilt.
INDEX_VERSION = 2


def _doc_prefix(source: str) -> str:
    return _ANSWER_PREFIX if source == "answer" else _DOC_PREFIX


def _query_prefix(source: str) -> str:
    return _ANSWER_PREFIX if source == "answer" else _QUERY_PREFIX

# A saved question counts as "the same question" only at or above this similarity.
# Below it the question is flagged NO MATCH and goes to the unknown questions list.
# Was 0.7 with the old search prefixes. The symmetric "clustering:" prefix shifts every
# score up (unrelated questions now land around 0.72-0.80), so 0.7 would accept everything.
# 0.85 on the Nov 10 eval: 29/34 real matches accepted, 9/10 non-matches rejected.
MATCH_THRESHOLD = 0.85

MAX_CHUNK_CHARS = 700  # a resume chunk is cut before it grows past this
MIN_CHUNK_CHARS = 25  # shorter pieces (page numbers, stray bullets) are dropped
_BATCH = 32  # texts sent to the embedding model per call

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<![\w])\+?\d[\d\s().-]{7,}\d(?![\w])")  # 9+ chars of digits and separators
_LONG_DIGITS = re.compile(r"\b\d{6,}\b")  # ID-style numbers


class RagError(Exception):
    """The index cannot be built or searched (message says why and what to do)."""


@dataclass(frozen=True)
class Chunk:
    """One piece of text to embed. ``ref`` says exactly where it came from."""

    source: str  # one of SOURCES
    ref: str  # profile section, project name, resume id (+ part number) or answer question
    text: str


@dataclass(frozen=True)
class SavedMatch:
    """Does a form question match one of your saved answers well enough to trust?

    ``matched`` is False when the best saved question scored under the threshold
    (or there is none). Then the question belongs on the unknown questions list
    (``add_to_unknown``). It may still be filled, but only as a flagged,
    NOT recommended guess (``recommended`` is False), and only if ``fill_allowed``.
    """

    hit: Hit | None  # the closest saved question, even when it is too weak
    matched: bool
    kinds: tuple[str, ...]  # kind(s) of the closest saved question: fixed / open / protected
    threshold: float

    @property
    def recommended(self) -> bool:
        """True only for a real match; a weak one must be shown as 'not recommended'."""
        return self.matched

    @property
    def add_to_unknown(self) -> bool:
        return not self.matched

    @property
    def fill_allowed(self) -> bool:
        """May the closest saved answer be filled in anyway (flagged)?

        Yes for every kind, protected included (your decision). The answer still
        comes only from your answer bank, never from the AI, and a weak match must
        always be shown as NOT recommended so you check it before you submit.
        """
        return self.hit is not None


@dataclass(frozen=True)
class Hit:
    """One search result. ``score`` is cosine similarity: 1.0 identical, 0 unrelated."""

    id: int
    source: str
    ref: str
    text: str
    score: float


# ---- storage ------------------------------------------------------------------


def init_rag(conn: sqlite3.Connection) -> None:
    """Load the ``sqlite-vec`` extension and create the two RAG tables if missing.

    ``chunks`` holds the text; ``chunks_vec`` is a ``vec0`` virtual table holding
    one vector per chunk under the SAME row id. Safe to call many times.
    """
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except (ImportError, AttributeError, sqlite3.Error) as exc:
        raise RagError(f"Cannot load sqlite-vec ({type(exc).__name__}). "
                       "Wrong Python? Activate the project venv first: .venv\\Scripts\\Activate.ps1 "
                       "(or run: pip install -r requirements.txt)") from exc
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS chunks (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL CHECK (source IN {SOURCES!r}),
            ref    TEXT NOT NULL,
            text   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rag_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
            embedding float[{ai.EMBED_DIM}] distance_metric=cosine
        );
        """
    )
    conn.commit()


# ---- chunking -------------------------------------------------------------------


def scrub(text: str, private_values: list[str] | None = None) -> str:
    """Remove emails, phone numbers, long ID numbers and your own private values from ``text``."""
    for value in private_values or []:
        if len(value.strip()) >= 5:
            text = re.sub(re.escape(value.strip()), " ", text, flags=re.IGNORECASE)
    text = _EMAIL.sub(" ", text)
    text = _PHONE.sub(" ", text)
    return _LONG_DIGITS.sub(" ", text)


def _is_heading(line: str) -> bool:
    """A short ALL-CAPS line or one ending in a colon starts a new resume section."""
    stripped = line.strip()
    if not stripped or len(stripped) > 40:
        return False
    return stripped.endswith(":") or (stripped.upper() == stripped and any(c.isalpha() for c in stripped))


def split_resume(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Cut resume text into chunks that follow its sections and never break a line.

    A new chunk starts at each heading, or when adding the next line would pass
    ``max_chars``. A heading stays attached to the lines beneath it.
    """
    chunks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        piece = " ".join(current).strip()
        if len(piece) >= MIN_CHUNK_CHARS:
            chunks.append(piece)
        current.clear()

    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        # A line longer than the limit is cut at sentence ends (never mid-word).
        pieces = re.split(r"(?<=[.!?]) ", line) if len(line) > max_chars else [line]
        for piece in pieces:
            size = sum(len(part) + 1 for part in current)
            only_headings = all(_is_heading(part) for part in current)
            # A heading always stays with the first line beneath it, however long.
            if current and not only_headings and (_is_heading(piece) or size + len(piece) > max_chars):
                flush()
            current.append(piece)
    flush()
    return chunks


def build_chunks(conn: sqlite3.Connection) -> list[Chunk]:
    """Read the database and return every chunk to index (see the module docstring for the rules)."""
    chunks: list[Chunk] = []
    profile = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
    private: list[str] = []

    if profile is not None:
        private = [profile["email"] or "", profile["phone"] or "", profile["address"] or ""]
        chunks += _profile_chunks(profile)
        for project in json.loads(profile["projects"]):
            tech = ", ".join(project.get("tech", []))
            parts = [f"Project: {project['name']}.", f"Technologies: {tech}." if tech else "", project.get("blurb", "")]
            if project.get("status"):
                parts.append(f"Status: {project['status']}.")
            if project.get("result"):
                parts.append(f"Result: {project['result']}")
            chunks.append(Chunk("project", project["name"], " ".join(p for p in parts if p).strip()))
            # The story (problem, solution, hardest part) is its own chunk, so a question about a
            # challenge finds it without the overview text diluting the match.
            story = [
                f"{label}: {project[key]}"
                for key, label in (("problem", "Problem"), ("solution", "Solution"), ("hardest_part", "Hardest part"))
                if project.get(key)
            ]
            if story:
                chunks.append(Chunk("project", f"{project['name']} (story)", " ".join([f"Project: {project['name']}.", *story])))

    for resume in conn.execute("SELECT id, extracted_text FROM resumes ORDER BY id"):
        pieces = split_resume(scrub(resume["extracted_text"], private))
        chunks += [Chunk("resume", f"{resume['id']}#{n}", piece) for n, piece in enumerate(pieces, start=1)]

    # Only QUESTIONS are embedded: each saved question plus its alternate wordings
    # (``also_asked_as``), all pointing (``ref``) at the saved question.
    wordings: dict[str, list[str]] = {}
    for row in conn.execute("SELECT DISTINCT question FROM answers ORDER BY question"):
        wordings[row["question"]] = [row["question"]]
    for row in conn.execute("SELECT question, alias FROM answer_aliases ORDER BY question, alias"):
        if row["question"] in wordings:
            wordings[row["question"]].append(row["alias"])
    for question, texts in wordings.items():
        seen: set[str] = set()
        for text in texts:
            key = " ".join(text.lower().split())
            if key and key not in seen:
                seen.add(key)
                chunks.append(Chunk("answer", question, text.strip()))
    return chunks


def _profile_chunks(profile: sqlite3.Row) -> list[Chunk]:
    """Profile facts that are safe to put in a prompt. No email, phone, address, links or GPA."""
    out: list[Chunk] = []
    if profile["summary"]:
        out.append(Chunk("profile", "summary", f"About me: {profile['summary']}"))
    skills = json.loads(profile["skills"])
    if skills:
        out.append(Chunk("profile", "skills", f"Skills: {', '.join(skills)}."))
    study = [profile["degree"], profile["school"], profile["year_level"]]
    if any(study):
        grad = f", graduating {profile['grad_year']}" if profile["grad_year"] else ""
        out.append(Chunk("profile", "education", f"Education: {', '.join(s for s in study if s)}{grad}."))
    roles = json.loads(profile["target_roles"])
    job_types = json.loads(profile["job_types"])
    places = json.loads(profile["preferred_locations"])
    wants = [
        f"Target roles: {', '.join(roles)}." if roles else "",
        f"Job types: {', '.join(job_types)}." if job_types else "",
        f"Preferred locations: {', '.join(places)}." if places else "",
        "Open to remote work." if profile["open_to_remote"] else "",
    ]
    if any(wants):
        out.append(Chunk("profile", "preferences", " ".join(w for w in wants if w)))
    return out


# ---- indexing and search ----------------------------------------------------------


def embedder_label(settings: Settings | None = None) -> str:
    """Name of what makes the vectors: ``"mock"`` (fake, for tests) or the embedding model.

    Vectors from different embedders cannot be compared, so the index remembers
    its label and refuses to be searched by a different one.
    """
    settings = settings or load_settings()
    model = "mock" if settings.run_mode == "mock" or settings.ai_provider == "mock" else settings.embed_model
    return f"{model}/v{INDEX_VERSION}"


def _unit(vector: list[float]) -> list[float]:
    """Scale a vector to length 1 so cosine distance is always well defined."""
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


def _embed_checked(texts: list[str], settings: Settings | None) -> list[list[float]]:
    """Embed in batches and make sure every vector has the size the table expects."""
    vectors: list[list[float]] = []
    for start in range(0, len(texts), _BATCH):
        vectors += ai.embed(texts[start : start + _BATCH], settings=settings)
    if any(len(v) != ai.EMBED_DIM for v in vectors):
        raise RagError(f"The embedding model must return {ai.EMBED_DIM} numbers per text (check embed_model).")
    return [_unit(v) for v in vectors]


def reindex(conn: sqlite3.Connection, settings: Settings | None = None) -> dict[str, int]:
    """Rebuild the whole index from the database. Returns how many chunks each source made.

    Embedding happens BEFORE anything is deleted, so if Ollama is down the old
    index stays intact. Run it again whenever your profile or answers change.
    """
    init_rag(conn)  # first: gives a clear message if sqlite-vec is missing
    import sqlite_vec

    settings = settings or load_settings()
    chunks = build_chunks(conn)
    vectors = _embed_checked([_doc_prefix(c.source) + c.text for c in chunks], settings)
    with conn:
        conn.execute(
            "INSERT INTO rag_meta (key, value) VALUES ('embedder', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (embedder_label(settings),),
        )
        conn.execute("DELETE FROM chunks_vec")
        conn.execute("DELETE FROM chunks")
        for chunk, vector in zip(chunks, vectors):
            cursor = conn.execute(
                "INSERT INTO chunks (source, ref, text) VALUES (?, ?, ?)", (chunk.source, chunk.ref, chunk.text)
            )
            conn.execute(
                "INSERT INTO chunks_vec (rowid, embedding) VALUES (?, ?)",
                (cursor.lastrowid, sqlite_vec.serialize_float32(vector)),
            )
    counts = {source: 0 for source in SOURCES}
    for chunk in chunks:
        counts[chunk.source] += 1
    return counts


def match_saved_question(
    conn: sqlite3.Connection,
    question: str,
    *,
    threshold: float = MATCH_THRESHOLD,
    settings: Settings | None = None,
) -> SavedMatch:
    """Find the closest saved question and say whether it is a real match (score >= threshold).

    This is the rule the answer engine uses before trusting the answer bank.
    """
    hits = retrieve(conn, question, 1, sources=("answer",), settings=settings)
    if not hits:
        return SavedMatch(None, False, (), threshold)
    best = hits[0]
    rows = conn.execute("SELECT DISTINCT kind FROM answers WHERE question = ?", (best.ref,)).fetchall()
    return SavedMatch(best, best.score >= threshold, tuple(sorted(r["kind"] for r in rows)), threshold)


def retrieve(
    conn: sqlite3.Connection,
    question: str,
    k: int = 5,
    *,
    sources: tuple[str, ...] | None = None,
    settings: Settings | None = None,
) -> list[Hit]:
    """Return the ``k`` chunks most similar to ``question``, best first.

    Args:
        sources: only these kinds of chunk (e.g. ``("answer",)`` to find a saved
            question, or ``("project", "resume", "profile")`` to find facts).
    """
    if not question.strip():
        raise RagError("Cannot search for an empty question.")
    if k < 1:
        raise RagError("k must be at least 1.")
    init_rag(conn)  # first: gives a clear message if sqlite-vec is missing
    import sqlite_vec

    total = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    if total == 0:
        raise RagError("The index is empty. Run: python -m engine.cli rag reindex")
    settings = settings or load_settings()
    built_with = conn.execute("SELECT value FROM rag_meta WHERE key = 'embedder'").fetchone()
    if built_with is None or built_with["value"] != embedder_label(settings):
        raise RagError(
            f"The index was built with {built_with['value'] if built_with else 'unknown'!r} but you are searching "
            f"with {embedder_label(settings)!r}. Run: python -m engine.cli rag reindex"
        )

    wanted = set(sources or SOURCES)
    hits: list[Hit] = []
    # Saved questions and facts were embedded with different prefixes, so each
    # group is searched with a query embedded the matching way.
    for group in (("answer",), FACT_SOURCES):
        if not wanted & set(group):
            continue
        [vector] = _embed_checked([_query_prefix(group[0]) + question.strip()], settings)
        rows = conn.execute(
            "SELECT rowid, distance FROM chunks_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (sqlite_vec.serialize_float32(vector), min(total, 4096)),  # small index: rank all, filter below
        ).fetchall()
        for row in rows:
            chunk = conn.execute("SELECT id, source, ref, text FROM chunks WHERE id = ?", (row["rowid"],)).fetchone()
            if chunk is not None and chunk["source"] in wanted and chunk["source"] in group:
                hits.append(Hit(chunk["id"], chunk["source"], chunk["ref"], chunk["text"], round(1.0 - row["distance"], 4)))

    hits.sort(key=lambda h: -h.score)
    # One saved question may have several wordings; keep only its best-scoring one.
    best: list[Hit] = []
    seen_questions: set[str] = set()
    for hit in hits:
        if hit.source == "answer":
            if hit.ref in seen_questions:
                continue
            seen_questions.add(hit.ref)
        best.append(hit)
        if len(best) == k:
            break
    return best
