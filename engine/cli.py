"""Command line for JobPilot. Run from the project folder, with the venv active:

    python -m engine.cli load              copy profile.json, resumes and answers.json into the database
    python -m engine.cli profile show      print your profile (email and phone masked)
    python -m engine.cli answers list      print the answer bank (optionally --kind fixed|open|protected)
    python -m engine.cli rag reindex       rebuild the search index (run after `load` or any data change)
    python -m engine.cli rag ask "..."     show the 5 chunks closest to a question (--source, -k)
    python -m engine.cli rag eval          top 5 chunks for every question in tests/fixtures/eval_questions.json
    python -m engine.cli forms read       list the fields of the page open in the bot's browser (read-only)
    python -m engine.cli forms capture N   save the open page as fixtures/forms/N.html (personal data removed)
    python -m engine.cli browser open      open the bot's browser (log in by hand; close the window to stop)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from engine.db import ANSWER_KINDS, connect, init_db
from engine.profile import ProfileError, load_all, profile_summary


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command; returns the exit code (0 = success)."""
    if hasattr(sys.stdout, "reconfigure"):  # Windows consoles default to a legacy encoding
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    parser = argparse.ArgumentParser(prog="python -m engine.cli", description="JobPilot")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("load", help="load profile, resumes and answers into the database")
    profile = sub.add_parser("profile", help="profile commands").add_subparsers(dest="action", required=True)
    profile.add_parser("show", help="print the profile (private fields masked)")
    answers = sub.add_parser("answers", help="answer bank commands").add_subparsers(dest="action", required=True)
    listing = answers.add_parser("list", help="print the answer bank")
    listing.add_argument("--kind", choices=ANSWER_KINDS, help="only this kind")
    rag = sub.add_parser("rag", help="search index commands").add_subparsers(dest="action", required=True)
    rag.add_parser("reindex", help="rebuild the index from the database")
    asking = rag.add_parser("ask", help="show the chunks closest to a question")
    asking.add_argument("question")
    asking.add_argument("-k", type=int, default=5, help="how many chunks (default 5)")
    asking.add_argument("--source", choices=("profile", "project", "resume", "answer"), action="append")
    evaluating = rag.add_parser("eval", help="run every eval question and show the top chunks")
    evaluating.add_argument("--file", default="tests/fixtures/eval_questions.json")
    browser = sub.add_parser("browser", help="the bot's browser").add_subparsers(dest="action", required=True)
    opener = browser.add_parser("open", help="open the bot's browser window")
    opener.add_argument("--url", help="optional page to start on")
    forms = sub.add_parser("forms", help="form commands").add_subparsers(dest="action", required=True)
    reading = forms.add_parser("read", help="list the fields of the open page")
    reading.add_argument("--json", action="store_true", help="print JSON instead of a table")
    capturing = forms.add_parser("capture", help="save the open page as an offline test file")
    capturing.add_argument("name", help="file name, e.g. angkas_workable")
    args = parser.parse_args(argv)

    if args.command == "browser":
        return _open_browser(args.url)

    conn = connect()
    init_db(conn)
    try:
        if args.command == "load":
            counts = load_all(conn)
            print(f"Loaded profile, {counts['resumes']} resumes and {counts['answers']} answers.")
        elif args.command == "rag":
            return _rag(conn, args)
        elif args.command == "forms":
            return _capture_form(conn, args.name) if args.action == "capture" else _read_forms(conn, args.json)
        elif args.command == "profile":
            print(json.dumps(profile_summary(conn), indent=2, ensure_ascii=False))
        else:
            _print_answers(conn, args.kind)
    except ProfileError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


def _rag(conn, args) -> int:  # type: ignore[no-untyped-def]
    """Run a ``rag`` command. Errors are printed, not raised."""
    from pathlib import Path

    from engine import rag
    from engine.ai import AIError
    from engine.settings import ROOT

    try:
        mode = rag.embedder_label()
        if args.action == "reindex":
            counts = rag.reindex(conn)
            print(f"Embedder: {mode}" + ("  (FAKE vectors: set run_mode to dry_run for real ones)" if mode == "mock" else ""))
            print("Indexed " + ", ".join(f"{n} {source}" for source, n in counts.items()) + " chunks.")
        elif args.action == "ask":
            print(f"Embedder: {mode}\n")
            _print_hits(conn, rag.retrieve(conn, args.question, args.k, sources=tuple(args.source or ()) or None))
        else:
            path = Path(args.file) if Path(args.file).is_absolute() else ROOT / args.file
            _run_eval(conn, path, rag, mode)
    except (rag.RagError, AIError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def _print_hits(conn, hits) -> None:  # type: ignore[no-untyped-def]
    """Print search results. A saved answer is shown unless it is protected (then only its kind)."""
    for rank, hit in enumerate(hits, start=1):
        text = _shorten(hit.text, 150)
        if hit.source == "answer":
            rows = conn.execute("SELECT kind FROM answers WHERE question = ?", (hit.ref,)).fetchall()
            kinds = sorted({r["kind"] for r in rows})
            text = f"{text}   [saved: {'/'.join(kinds)}, {len(rows)} variant(s)]"
        print(f"{rank}. {hit.score:.3f}  {hit.source}:{_shorten(hit.ref, 30)}\n      {text}")


def _run_eval(conn, path, rag, mode: str) -> None:  # type: ignore[no-untyped-def]
    """Print the top 5 chunks for every eval question, and where the expected saved question ranked."""
    questions = json.loads(path.read_text(encoding="utf-8-sig"))["questions"]
    print(f"Embedder: {mode}   {len(questions)} questions from {path.name}\n")
    ranks: list[int | None] = []
    for q in questions:
        hits = rag.retrieve(conn, q["form_question"], 5)
        print(f"[{q['id']}] {q['form_question']}   (expects: {q['expect_source']})")
        _print_hits(conn, hits)
        expected = q.get("expect_saved_question")
        if expected and not expected.startswith("<"):
            rank = next((i for i, h in enumerate(hits, 1) if h.source == "answer" and h.ref == expected), None)
            ranks.append(rank)
            print(f"   expected saved question: {'rank ' + str(rank) if rank else 'NOT in top 5'}")
        print()
    if ranks:
        print(f"Saved question found: first {sum(r == 1 for r in ranks)}/{len(ranks)}, "
              f"top 5 {sum(r is not None for r in ranks)}/{len(ranks)}")


def _shorten(text: str, limit: int = 110) -> str:
    """Long labels (legal notices) are cut for display only; the full text is kept."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _read_forms(conn, as_json: bool) -> int:  # type: ignore[no-untyped-def]
    """Print the fields of the page open in the bot's browser. Changes nothing on the page."""
    from engine.forms.reader import read_current_page
    from engine.safety import SafetyError

    try:
        url, fields = read_current_page(conn=conn)
    except (RuntimeError, SafetyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if as_json:
        print(json.dumps([f.model_dump() for f in fields], indent=2, ensure_ascii=False))
        return 0
    print(f"{url}\n{len(fields)} fields\n")
    for number, f in enumerate(fields, start=1):
        flags = ("required " if f.required else "") + ("NEEDS YOU" if f.needs_you else "")
        options = f"  options: {', '.join(f.options)}" if f.options else ""
        where = f"  (in frame: {f.frame.split('/')[2]})" if f.frame.startswith("http") else ""
        print(f"{number:>2}. [{f.type:<8}] {_shorten(f.label) or '(no label)'} {flags}{options}{where}")
    return 0


def _capture_form(conn, name: str) -> int:  # type: ignore[no-untyped-def]
    """Save the open page as an offline test file (personal data removed)."""
    from engine.forms.capture import capture_current_page
    from engine.safety import SafetyError

    try:
        path = capture_current_page(name, conn=conn)
    except (RuntimeError, ValueError, SafetyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Saved {path}\nOpen it in an editor and check it has no personal data before committing.")
    return 0


def _open_browser(url: str | None) -> int:
    """Open the bot's browser (needs no database)."""
    from engine.forms.browser import open_browser
    from engine.safety import SafetyError

    try:
        open_browser(url)
    except SafetyError as exc:
        print(f"Blocked: {exc}", file=sys.stderr)
        return 1
    return 0


def _print_answers(conn, kind: str | None) -> None:  # type: ignore[no-untyped-def]
    sql = "SELECT id, kind, location_scope, city, question, answer FROM answers"
    rows = conn.execute(sql + (" WHERE kind = ?" if kind else "") + " ORDER BY id", (kind,) if kind else ()).fetchall()
    for r in rows:
        scope = r["location_scope"] + (f":{r['city']}" if r["city"] else "")
        answer = r["answer"] if r["kind"] != "protected" else "(protected, hidden)"
        print(f"{r['id']:>3} [{r['kind']:<9}] [{scope}] {r['question']}\n      -> {answer[:90]}")
    print(f"\n{len(rows)} answers")


if __name__ == "__main__":
    raise SystemExit(main())
