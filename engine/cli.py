"""Command line for JobPilot.

HOW TO RUN (every time you open a new terminal)
================================================
1. Open a terminal in the project folder (the one that contains `engine/`, `data/`
   and `requirements.txt`). In VS Code: Terminal > New Terminal opens there already.
   Or in PowerShell:

       cd C:\\Users\\Administrator\\Downloads\\LearningOOP\\JobPilot

2. Turn on the project's Python (the "venv"), which has all the libraries installed:

       .venv\\Scripts\\Activate.ps1

   (cmd.exe instead of PowerShell: `.venv\\Scripts\\activate.bat`.)
   If PowerShell says "running scripts is disabled", run this ONCE, then retry:

       Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

3. Check the terminal looks like this. `(.venv)` at the start and the JobPilot
   folder before the `>` means you are set:

       (.venv) PS C:\\Users\\Administrator\\Downloads\\LearningOOP\\JobPilot>

   If `(.venv)` is missing you get "No module named 'sqlite_vec'" or similar.

4. Run the commands below IN THIS ORDER the first time:

       python -m engine.cli load            # 1. read profile.json, resumes, answers.json
       python -m engine.cli profile show    # 2. check your profile looks right
       python -m engine.cli answers list    # 3. check your answers look right
       python -m engine.cli rag reindex     # 4. build the search index
       python -m engine.cli rag ask "What is your expected salary?"   # 5. try a search
       python -m engine.cli rag eval        # 6. run all the test questions

   Run `load` again, then `rag reindex`, after you edit profile.json or answers.json
   (and after `questions approve`).

5. Run the tests before every commit:

       python -m pytest -q

Run mode: the default is `mock`, which uses FAKE search vectors, so scores are only
a rough check. For real scores, start Ollama (with `nomic-embed-text` pulled), set
run_mode to `dry_run` in settings, then run `rag reindex` again.

All commands
============
    python -m engine.cli load            copy profile.json, resumes and answers.json into the database
    python -m engine.cli profile show      print your profile (email and phone masked)
    python -m engine.cli answers list      print the answer bank (optionally --kind fixed|open|protected)
    python -m engine.cli rag reindex       rebuild the search index (run after `load` or any data change)
    python -m engine.cli rag ask "..."     show the 5 chunks closest to a question (--source, -k)
    python -m engine.cli rag eval          top 5 chunks for every question in tests/fixtures/eval_questions.json
    python -m engine.cli questions list    show unknown questions and new wordings waiting for your OK
    python -m engine.cli questions approve ID [--yes-protected]   write a wording into answers.json (backup first)
    python -m engine.cli questions reject ID                      throw a wording away for good
    python -m engine.cli forms read       list the fields of the page open in the bot's browser (read-only)
    python -m engine.cli forms capture N   save the open page as fixtures/forms/N.html (personal data removed)
    python -m engine.cli forms answer --fixture F   read a saved page, print the engine's answer per field (types nothing; add --record to save unknowns)
    python -m engine.cli resume pick --post FILE   pick resume A or B for a saved job post (a .txt file)
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
    resume = sub.add_parser("resume", help="resume commands").add_subparsers(dest="action", required=True)
    picking = resume.add_parser("pick", help="pick resume A or B for a saved job post")
    picking.add_argument("--post", required=True, help="text file with the job post, e.g. data/job_posts/x.txt")
    browser = sub.add_parser("browser", help="the bot's browser").add_subparsers(dest="action", required=True)
    opener = browser.add_parser("open", help="open the bot's browser window")
    opener.add_argument("--url", help="optional page to start on")
    forms = sub.add_parser("forms", help="form commands").add_subparsers(dest="action", required=True)
    reading = forms.add_parser("read", help="list the fields of the open page")
    reading.add_argument("--json", action="store_true", help="print JSON instead of a table")
    capturing = forms.add_parser("capture", help="save the open page as an offline test file")
    capturing.add_argument("name", help="file name, e.g. angkas_workable")
    answering = forms.add_parser("answer", help="read a saved page and show the answer engine's decision per field")
    answering.add_argument("--fixture", required=True, help="saved page: a path, or a name in fixtures/forms/")
    answering.add_argument("--record", action="store_true", help="also save unknown questions and suggested wordings")
    questions = sub.add_parser("questions", help="unknown questions and suggested wordings").add_subparsers(
        dest="action", required=True
    )
    questions.add_parser("list", help="show unknown questions and wordings waiting for your OK")
    approving = questions.add_parser("approve", help="add a suggested wording to answers.json")
    approving.add_argument("id", type=int)
    approving.add_argument("--yes-protected", action="store_true", help="needed when the saved answer is protected")
    rejecting = questions.add_parser("reject", help="throw a suggested wording away for good")
    rejecting.add_argument("id", type=int)
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
        elif args.command == "resume":
            return _pick_resume(conn, args.post)
        elif args.command == "questions":
            return _questions(conn, args)
        elif args.command == "forms":
            if args.action == "capture":
                return _capture_form(conn, args.name)
            if args.action == "answer":
                return _answer_fixture(conn, args.fixture, args.record)
            return _read_forms(conn, args.json)
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


def _pick_resume(conn, post_path: str) -> int:  # type: ignore[no-untyped-def]
    """Read a job post file and print which resume fits it, with the evidence."""
    from pathlib import Path

    from engine.matcher import PickError, pick_resume

    try:
        text = Path(post_path).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Error: cannot read {post_path}: {exc}", file=sys.stderr)
        return 1
    try:
        pick = pick_resume(conn, text)
    except PickError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if pick is None:
        print("No job post, no pick.")
        return 0
    print(f"Pick: resume {pick.resume}")
    print(f"Reason: {pick.reason}")
    print("Evidence:")
    for line in pick.evidence:
        print(f"  - {line}")
    return 0


def _questions(conn, args) -> int:  # type: ignore[no-untyped-def]
    """Run a ``questions`` command: list, approve or reject. Errors are printed, not raised."""
    from engine import learning

    try:
        if args.action == "approve":
            backup = learning.approve_wording(conn, args.id, confirm_protected=args.yes_protected)
            print("Added to answers.json." + (f" Backup: {backup.name}" if backup else " (it was already there)"))
            print("Now run: python -m engine.cli load   then   python -m engine.cli rag reindex")
        elif args.action == "reject":
            learning.reject_wording(conn, args.id)
            print(f"Suggestion {args.id} rejected; it will not be suggested again.")
        else:
            _print_learning(conn)
    except learning.LearningError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def _print_learning(conn) -> None:  # type: ignore[no-untyped-def]
    """Print both waiting lists."""
    from engine import learning

    unknown = learning.open_unknowns(conn)
    print(f"UNKNOWN QUESTIONS ({len(unknown)}): add each to answers.json, then `load` and `rag reindex`")
    for row in unknown:
        print(f"  #{row['id']}  seen {row['times_seen']}x  {_shorten(row['question_text'], 100)}")
    wordings = learning.pending_wordings(conn)
    print(f"\nSUGGESTED WORDINGS ({len(wordings)}): same meaning as a saved question?")
    for row in wordings:
        flag = "  [PROTECTED: needs --yes-protected]" if row["protected"] else ""
        print(f"  #{row['id']}  score {row['score']:.2f}  seen {row['times_seen']}x{flag}")
        print(f"      new:   {_shorten(row['wording'], 100)}\n      saved: {_shorten(row['matched_question'], 100)}")
    if wordings:
        print("\nApprove: python -m engine.cli questions approve ID      Reject: ... questions reject ID")


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
            print(_verdict(rag.match_saved_question(conn, args.question)))
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
            via = f"   (via wording: {_shorten(hit.text, 60)})" if hit.text != hit.ref else ""
            text = f"{_shorten(hit.ref, 150)}   [saved: {'/'.join(kinds)}, {len(rows)} variant(s)]{via}"
        print(f"{rank}. {hit.score:.3f}  {hit.source}:{_shorten(hit.ref, 30)}\n      {text}")


def _verdict(m) -> str:  # type: ignore[no-untyped-def]
    """One line telling you whether the closest saved question is trusted."""
    if m.matched:
        return f"   => MATCH ({m.hit.score:.3f} >= {m.threshold}): recommended"
    best = f"best {m.hit.score:.3f}" if m.hit else "nothing saved"
    action = "fill allowed but NOT recommended" if m.fill_allowed else "nothing to fill"
    return f"   => NO MATCH ({best} < {m.threshold}): goes to unknown questions; {action}"


def _run_eval(conn, path, rag, mode: str) -> None:  # type: ignore[no-untyped-def]
    """Print the top 5 chunks for every eval question, the match verdict, and where the expected question ranked."""
    questions = json.loads(path.read_text(encoding="utf-8-sig"))["questions"]
    for number, q in enumerate(questions, start=1):
        missing = [key for key in ("id", "form_question", "expect_source") if key not in q]
        if missing:
            raise ValueError(f"{path.name}, question #{number} is missing {missing} (a batch pasted inside the list?)")
    print(f"Embedder: {mode}   {len(questions)} questions from {path.name}")
    # An eval question copied word for word into also_asked_as would make the test meaningless.
    stored = {" ".join(r["alias"].lower().split()) for r in conn.execute("SELECT alias FROM answer_aliases")}
    copied = [q["id"] for q in questions if " ".join(q["form_question"].lower().split()) in stored]
    if copied:
        print(f"WARNING: these eval questions are copied into also_asked_as, so they test nothing: {copied}")
    print()
    ranks: list[int | None] = []
    agree: list[bool] = []
    for q in questions:
        hits = rag.retrieve(conn, q["form_question"], 5)
        print(f"[{q['id']}] {q['form_question']}   (expects: {q['expect_source']})")
        _print_hits(conn, hits)
        verdict = rag.match_saved_question(conn, q["form_question"])
        print(_verdict(verdict))
        if q["expect_source"] in ("answer_bank", "ai_draft"):  # profile_code fields never use the bank
            ok = verdict.matched == (q["expect_source"] == "answer_bank")
            agree.append(ok)
            if not ok:
                print("   !! verdict differs from what you expected for this question")
        expected = q.get("expect_saved_question")
        if expected and not expected.startswith("<"):
            rank = next((i for i, h in enumerate(hits, 1) if h.source == "answer" and h.ref == expected), None)
            ranks.append(rank)
            print(f"   expected saved question: {'rank ' + str(rank) if rank else 'NOT in top 5'}")
        print()
    if agree:
        print(f"Match verdict agrees with your expectation: {sum(agree)}/{len(agree)} (threshold {rag.MATCH_THRESHOLD})")
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


def _answer_fixture(conn, fixture: str, record: bool = False) -> int:  # type: ignore[no-untyped-def]
    """Read a saved page and print what the answer engine would put in each field. Types and clicks nothing.

    A preview by default: unknown questions and suggested wordings are NOT saved. ``record=True`` (``--record``) saves them.
    """
    from pathlib import Path

    from engine.forms.answers import answer_form
    from engine.forms.reader import read_fixture
    from engine.settings import ROOT

    path = Path(fixture)
    if not path.is_absolute() and not path.exists():  # a bare name like "angkas_workable" lives in fixtures/forms/
        path = ROOT / "fixtures" / "forms" / (fixture if fixture.endswith(".html") else f"{fixture}.html")
    if not path.is_file():
        print(f"Error: fixture not found: {path}", file=sys.stderr)
        return 1
    path = path.resolve()  # as_uri() below needs an absolute path
    try:
        fields = read_fixture(path)
        answers = answer_form(conn, fields, page_url=path.as_uri(), record=record)
    except (OSError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    rows = []
    for a in answers:
        value = "(protected, hidden)" if a.kind == "protected" and a.value else a.value
        shown = _shorten(" ".join(value.split()), 50)
        if not shown:
            shown = "(resume: picked at fill time)" if a.source == "resume" else "(empty: you fill it)"
        rows.append((
            _shorten(a.label or "(no label)", 40),
            shown,
            a.source,
            f"{a.confidence:.2f}",
            "YES" if a.flagged else "no",
        ))
    header = ("field", "answer", "source", "confidence", "flagged")
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) if rows else len(header[i]) for i in range(5)]
    line = "  ".join(f"{{:<{w}}}" for w in widths)
    saved = "unknown questions and wordings saved" if record else "preview only: nothing saved (use --record to save)"
    print(f"{path.name}: {len(answers)} fields, {sum(a.flagged for a in answers)} flagged   [{saved}]\n")
    print(line.format(*header))
    print(line.format(*("-" * w for w in widths)))
    for row in rows:
        print(line.format(*row))
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
