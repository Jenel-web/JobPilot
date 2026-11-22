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
    python -m engine.cli forms elaborate --question "Do you know Docker?" [--saved Yes] [--min-score 0.7]   try one question, no page needed
    python -m engine.cli forms elaborate --fixture F [--as-text]   show which short yes/no answers get elaborated, the notes used (with scores) and the result
    python -m engine.cli forms fill [--resume A|B] [--post FILE] [--fixture NAME] [--fast]   fill the open page, outline what needs you, stop before Submit
    python -m engine.cli forms fill [--tab TEXT] [--post FILE] [--resume A|B] [--mode mock|dry_run] [--fast]   fill the form tab, then STOP (never submits)
    python -m engine.cli forms fill --fixture F   try it on a saved page in a test window (saves nothing)
    python -m engine.cli forms why-company [--tab TEXT | --post FILE] [--question TEXT] [--mode dry_run]   preview the company answer for a job post (types nothing)
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
    elaborating = forms.add_parser("elaborate", help="show how short saved yes/no answers are elaborated on a saved page")
    elaborating.add_argument("--fixture", help="saved page: a path, or a name in fixtures/forms/")
    elaborating.add_argument("--question", help="instead of a page: type ONE question (as a free-text box)")
    elaborating.add_argument("--min-score", type=float, help="try another notes cutoff for this run (default: ELABORATE_MIN_SCORE)")
    elaborating.add_argument("--saved", default="Yes", help="with --question: the saved answer to elaborate (default Yes)")
    elaborating.add_argument(
        "--as-text", action="store_true", help="treat yes/no radios, dropdowns and checkboxes as text boxes (a what-if)"
    )
    filling = forms.add_parser("fill", help="fill the open page (or a saved page with --fixture), then stop before Submit")
    filling.add_argument("--resume", choices=("A", "B", "a", "b"), help="resume to upload (without it, resume fields stay empty; or use --post)")
    filling.add_argument("--post", help="text file with the job post, used instead of looking through your tabs (picks the resume if --resume is missing)")
    filling.add_argument("--fixture", help="fill a saved page in a visible test browser instead of the bot's browser (a path, or a name in fixtures/forms/)")
    filling.add_argument("--fast", action="store_true", help="skip the 1-4 s pauses (for a quick look at a saved page)")
    filling.add_argument("--tab", help="fill the first tab whose address contains this text (default: the tab you are looking at)")
    filling.add_argument(
        "--mode", choices=("mock", "dry_run"), help="run mode for THIS command only (settings.json is not changed; live is never allowed here)"
    )
    company = forms.add_parser("why-company", help="preview the answer to \"Why do you want to work here?\" for a job post")
    company.add_argument("--tab", help="read the job post from the first tab whose address contains this text (default: the tab you are looking at)")
    company.add_argument("--post", help="text file with the job post, instead of reading a tab")
    company.add_argument("--question", default="Why do you want to work here?", help="the question to answer")
    company.add_argument("--max-length", type=int, help="pretend the box holds this many characters")
    company.add_argument("--mode", choices=("mock", "dry_run"), help="run mode for THIS command only (live is never allowed here)")
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
            if args.action == "fill":
                return _fill_form(conn, args)
            if args.action == "why-company":
                return _why_company(conn, args)
            if args.action == "elaborate":
                if args.min_score is not None:
                    from engine.forms import drafting

                    drafting.ELABORATE_MIN_SCORE = args.min_score  # this run only
                if args.question:
                    return _elaborate_question(conn, args.question, args.saved)
                if not args.fixture:
                    print("Error: give --fixture NAME or --question TEXT", file=sys.stderr)
                    return 1
                return _elaborate_fixture(conn, args.fixture, args.as_text)
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


def _fill_form(conn, args) -> int:  # type: ignore[no-untyped-def]
    """Fill the open page and STOP before Submit. Never submits.

    Without ``--fixture`` it works on the form tab in the bot's browser (real pages need run_mode = dry_run).
    With ``--fixture`` it opens a saved page in a visible test browser, and saves nothing to the database.
    The job post comes from ``--post FILE`` if given, else from the finder (form page, opener tab, same-site tab).
    """
    import dataclasses
    import time
    from datetime import datetime
    from pathlib import Path

    from playwright.sync_api import sync_playwright

    from engine import rag, safety
    from engine.ai import AIError
    from engine.forms.jobfinder import post_from_pasted
    from engine.forms.orchestrator import fill_current_page
    from engine.forms.reader import connect_to_bot_browser, find_current_page
    from engine.matcher import PickError
    from engine.settings import ROOT, load_settings

    settings = load_settings()
    if args.mode:  # this command only: settings.json is never written, and `live` is not offered
        settings = dataclasses.replace(settings, run_mode=args.mode)
    path = None  # the saved page to open, when --fixture is used (checked first: a typo should not need a database)
    if args.fixture:
        path = Path(args.fixture)
        if not path.is_absolute() and not path.exists():
            path = ROOT / "fixtures" / "forms" / (args.fixture if args.fixture.endswith(".html") else f"{args.fixture}.html")
        if not path.is_file():
            print(f"Error: fixture not found: {path}", file=sys.stderr)
            return 1
    try:
        post = post_from_pasted(Path(args.post).read_text(encoding="utf-8")) if args.post else None
        try:  # a search index that does not match the run mode would leave most fields empty: stop with a clear message
            rag.retrieve(conn, "ready check", 1, settings=settings)
        except rag.RagError as exc:
            print(f"Error: {exc}\nNothing was filled. Run mode is {settings.run_mode!r}: the index must be built in the same mode.", file=sys.stderr)
            return 1
        shot = ROOT / "data" / "screenshots" / f"fill-{datetime.now():%Y%m%d-%H%M%S}.png"
        with sync_playwright() as p:
            owned = None
            if path is not None:
                owned = p.chromium.launch(headless=False)  # a throwaway test window, not the bot's profile
                page = owned.new_page()
                safety.check("navigate", path.resolve().as_uri(), settings=settings)
                page.goto(path.resolve().as_uri())
                page.wait_for_timeout(500)
            else:
                browser = connect_to_bot_browser(p)
                if args.tab:
                    matches = [pg for ctx in browser.contexts for pg in ctx.pages if args.tab in pg.url]
                    if not matches:
                        print(f"Error: no open tab has {args.tab!r} in its address.", file=sys.stderr)
                        return 1
                    page = matches[0]
                else:
                    page = find_current_page(browser)
            print(f"{page.url}\nFilling (random 1-4 s pauses; it never clicks Submit)...")
            outcome = fill_current_page(
                conn, page, settings=settings, post=post, resume_id=args.resume.upper() if args.resume else None,
                save=path is None, sleep=(lambda seconds: None) if args.fast else time.sleep, screenshot_path=shot,
            )
            _print_outcome(outcome, saved=path is None)
            if owned is not None:
                try:
                    input("\nLook at the page, then press Enter here to close the test window... ")
                except EOFError:
                    pass
                owned.close()
    except (RuntimeError, ValueError, OSError, safety.SafetyError, PickError, AIError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def _why_company(conn, args) -> int:  # type: ignore[no-untyped-def]
    """Preview the company answer for a job post. Read-only: it reads one page (or a file), types and saves nothing."""
    import dataclasses
    from pathlib import Path

    from playwright.sync_api import sync_playwright

    from engine import rag, safety
    from engine.ai import AIError
    from engine.forms.answers import preview_company_answer
    from engine.forms.history import private_values
    from engine.forms.jobfinder import tab_text
    from engine.forms.reader import connect_to_bot_browser, find_current_page
    from engine.settings import load_settings

    settings = load_settings()
    if args.mode:  # this command only: settings.json is never written, and `live` is not offered
        settings = dataclasses.replace(settings, run_mode=args.mode)
    try:
        if args.post:
            text, source = Path(args.post).read_text(encoding="utf-8"), args.post
        else:
            with sync_playwright() as p:
                browser = connect_to_bot_browser(p)
                if args.tab:
                    matches = [pg for ctx in browser.contexts for pg in ctx.pages if args.tab in pg.url]
                    if not matches:
                        print(f"Error: no open tab has {args.tab!r} in its address.", file=sys.stderr)
                        return 1
                    page = matches[0]
                else:
                    page = find_current_page(browser)
                safety.check("read", page.url, settings=settings)
                text, source = tab_text(page), page.url
                safety.log_action(conn, "read", page.url, "why-company preview: job post read")
        text = rag.scrub(text, private_values(conn)).strip()  # rule 3: nothing personal goes to the AI
        if not text:
            print("Error: the job post is empty (nothing could be read).", file=sys.stderr)
            return 1
        print(f"Job post: {source}  ({len(text)} characters, your details removed)\nRun mode: {settings.run_mode}\n")
        brief, answer = preview_company_answer(conn, text, args.question, settings=settings, max_length=args.max_length)
    except (RuntimeError, ValueError, OSError, safety.SafetyError, AIError, rag.RagError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print("COMPANY BRIEF (what the job post says; the code removed anything it does not back up)")
    if brief is None:
        print("  (no brief: the AI failed or there was no text)")
    else:
        for label, value in (("Company", brief.company), ("Role", brief.role), ("What they do", brief.what_they_do),
                             ("Mission", brief.mission), ("Values", "; ".join(brief.values)),
                             ("Duties", "; ".join(brief.duties))):
            print(f"  {label:<13}: {value or '-'}")
        for quote in brief.quotes:
            print(f"  quote        : \"{quote}\"")
        print(f"  style        : {'ROLE ONLY (the post says little about the company)' if brief.thin else 'COMPANY + WHY YOU'}")
        for item in brief.dropped:
            print(f"  DROPPED (not in the post): {item}")
    print(f"\nQUESTION: {args.question}")
    print(f"ANSWER ({answer.source}, flagged={answer.flagged}):\n  {answer.value or '(empty: you answer this one)'}")
    print(f"NOTE: {answer.note}")
    print("\nNothing was typed into any page and nothing was saved.")
    return 0


def _print_outcome(outcome, saved: bool) -> None:  # type: ignore[no-untyped-def]
    """Say which job post and resume were used, what was skipped, then the fill report."""
    if outcome.post is not None:
        print(f"Job post used: {outcome.post.label}")
    else:
        others = "; ".join(f"[{t.index}] {t.title[:40] or t.url[:40]}" for t in outcome.tabs)
        print("Job post used: NONE found." + (f" Your other tabs: {others}" if others else ""))
    if outcome.resume_id:
        print(f"Resume: {outcome.resume_id}" + (f"  ({outcome.resume_reason})" if outcome.resume_reason else ""))
    for message in outcome.messages:
        print(f"  ! {message}")
    if outcome.report is None:
        return
    _print_fill_report(outcome.report)
    if outcome.unknown_ids:
        print(f"{len(outcome.unknown_ids)} question(s) have no saved answer: see `python -m engine.cli questions list`.")
    if outcome.fill_id is not None:
        print(f"Saved to the filled pages history as #{outcome.fill_id} (status: filled).")
    elif not saved:
        print("Preview run on a saved page: nothing was saved to the database.")


def _print_fill_report(report) -> None:  # type: ignore[no-untyped-def]
    """Print the result of a fill: the counts, each field that needs a look, and the screenshot."""
    print(f"\n{report.summary()}")
    for r in report.results:
        if r.flagged:
            kind = "NEEDS YOU" if r.outcome != "filled" else "CHECK"
            print(f"  ▲ {kind:<9} {_shorten(r.label or '(no label)', 50)}  {_shorten(r.note, 80)}")
    if report.screenshot_path:
        print(f"Screenshot: {report.screenshot_path}")
    print("Stopped before Submit. Nothing was sent. Review the page, fix the outlined fields, then submit yourself.")


def _elaborate_question(conn, question: str, saved: str) -> int:  # type: ignore[no-untyped-def]
    """Try ONE question as a free-text box with a given saved answer: the checks, the notes (with scores) and the result.

    It skips the saved-question search: you say what the saved answer is. Nothing is typed or saved.
    """
    from engine.forms import drafting
    from engine.forms.answers import is_experience_question, is_sensitive
    from engine.forms.reader import FormField

    field = FormField(label=question, type="textarea")
    stance = drafting.short_yes_no(saved)
    checks = [
        ("saved answer is a short yes/no (3 words or fewer)", stance is not None),
        ("question is about experience or knowledge", is_experience_question(question)),
        ("question is not sensitive", not is_sensitive(question)),
    ]
    for text, ok in checks:
        print(f"  [{'ok' if ok else 'NO'}] {text}")
    try:
        notes = drafting.gather_facts(conn, question)
    except Exception as exc:  # a missing index must not hide the checks
        notes = []
        print(f"  notes unavailable: {exc}")
    for h in notes:
        used = "used" if h.score >= drafting.ELABORATE_MIN_SCORE else "below cutoff"
        print(f"  note {h.score:.2f} [{used}] {h.source}:{h.ref}  {_shorten(' '.join(h.text.split()), 90)}")
    if not all(ok for _, ok in checks):
        print(f"\nResult: NOT elaborated. The engine would use the plain saved answer: {saved!r}")
        return 0
    result = drafting.elaborate_short(conn, field, saved)
    if result.source == "rules":
        print(f"\nResult: NOT elaborated ({result.note}). Plain saved answer: {saved!r}")
    else:
        print(f"\nResult (ELABORATED, would be flagged): {result.text}\n  used: {result.source}  {result.note}")
    return 0


def _elaborate_fixture(conn, fixture: str, as_text: bool = False) -> int:  # type: ignore[no-untyped-def]
    """Show, per field of a saved page, whether a short saved yes/no is elaborated, and why. Types nothing, saves nothing.

    For every field whose saved answer is a short yes/no it prints the notes the search found (with scores; those under
    the cutoff are not used) and what the engine would put in the box. ``as_text`` pretends yes/no radios, dropdowns
    and checkboxes are free-text boxes, so you can try the feature on a form that has none.
    """
    from pathlib import Path

    from engine.forms import drafting
    from engine.forms.answers import answer_form
    from engine.forms.reader import read_fixture
    from engine.settings import ROOT

    path = Path(fixture)
    if not path.is_absolute() and not path.exists():
        path = ROOT / "fixtures" / "forms" / (fixture if fixture.endswith(".html") else f"{fixture}.html")
    if not path.is_file():
        print(f"Error: fixture not found: {path}", file=sys.stderr)
        return 1
    path = path.resolve()
    try:
        fields = read_fixture(path)
        if as_text:
            fields = [
                f.model_copy(update={"type": "textarea", "options": []}) if f.type in ("radio", "select", "checkbox") else f
                for f in fields
            ]
        answers = answer_form(conn, fields, page_url=path.as_uri(), record=False)
    except (OSError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    shown = 0
    for field, a in zip(fields, answers):
        elaborated = a.note.startswith("saved ") and "elaborated from your notes" in a.note
        if not (elaborated or a.note.startswith("not elaborated")):
            continue
        shown += 1
        print(f"\n[{shown}] {a.label}\n    matched saved question: {a.matched_question}  (score {a.confidence:.2f})")
        try:
            notes = drafting.gather_facts(conn, field.label)
        except Exception as exc:  # a missing index must not hide the result
            notes = []
            print(f"    notes: unavailable ({exc})")
        for h in notes:
            used = "used" if h.score >= drafting.ELABORATE_MIN_SCORE else "below cutoff"
            print(f"    note {h.score:.2f} [{used}] {h.source}:{h.ref}  {_shorten(' '.join(h.text.split()), 90)}")
        print(f"    result ({'ELABORATED, flagged' if elaborated else 'plain saved answer'}): {a.value}\n    why: {a.note}")
    if not shown:
        print(f"{path.name}: no field has a short saved yes/no answer in a text box." + ("" if as_text else " Try --as-text."))
    else:
        print(f"\n{path.name}: {shown} field(s) considered. Preview only: nothing typed, nothing saved. Cutoff {drafting.ELABORATE_MIN_SCORE}.")
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
