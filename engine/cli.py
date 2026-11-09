"""Command line for JobPilot. Run from the project folder, with the venv active:

    python -m engine.cli load              copy profile.json, resumes and answers.json into the database
    python -m engine.cli profile show      print your profile (email and phone masked)
    python -m engine.cli answers list      print the answer bank (optionally --kind fixed|open|protected)
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
    browser = sub.add_parser("browser", help="the bot's browser").add_subparsers(dest="action", required=True)
    opener = browser.add_parser("open", help="open the bot's browser window")
    opener.add_argument("--url", help="optional page to start on")
    args = parser.parse_args(argv)

    if args.command == "browser":
        return _open_browser(args.url)

    conn = connect()
    init_db(conn)
    try:
        if args.command == "load":
            counts = load_all(conn)
            print(f"Loaded profile, {counts['resumes']} resumes and {counts['answers']} answers.")
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
