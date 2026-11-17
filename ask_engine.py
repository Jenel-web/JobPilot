"""Try ONE question on the answer engine, using your real profile, answers and search index.

Safe to run: it works on a COPY of data/jobpilot.db, so the unknown-questions list, suggested
wordings and everything else in your real database stay untouched. Nothing is typed into a
browser. In dry_run mode the question and 4 facts go to your LOCAL Ollama only.

Usage (from the project folder):
    python ask_engine.py "Describe a project you are proud of"
    python ask_engine.py "Tell us about your strengths" --type text
    python ask_engine.py "Are you open to relocating?" --scope remote
    python ask_engine.py "Are you open to relocating?" --job "Software Intern, Makati City, hybrid"
    python ask_engine.py "Are you open to relocating?" --job "On-site in Cebu City"
    python ask_engine.py "Are you open to relocating?" --job-file data/job.txt   (paste a job post into it)
    python ask_engine.py "Are you open to relocating?" --job ""                  (a post with no location)

--job / --job-file stand in for the job post text the page will give later. Without them the saved
answers (with their location scope) are used exactly as before.
"""
import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from engine.db import DB_PATH, connect
from engine.forms.answers import answer_field, profile_values
from engine.forms.reader import FormField
from engine.settings import load_settings

parser = argparse.ArgumentParser()
parser.add_argument("question")
parser.add_argument("--type", default="textarea", help="text, textarea, select, radio... (default textarea)")
parser.add_argument("--options", nargs="*", default=[], help="for select/radio fields")
parser.add_argument("--scope", default="any", choices=["any", "city", "remote", "abroad"])
parser.add_argument("--city", default="")
parser.add_argument("--job", default=None, help="job post text (where the job is); '' = a post with no location")
parser.add_argument("--job-file", default=None, help="a text file holding the job post")
args = parser.parse_args()

job_text = Path(args.job_file).read_text(encoding="utf-8") if args.job_file else args.job

settings = load_settings()
print(f"run_mode={settings.run_mode}  model={settings.ollama_model}")
if settings.run_mode == "mock":
    print("NOTE: mock mode. Search uses fake vectors and the AI gives a canned reply, so this only\n"
          "checks the wiring. For real answers: set run_mode to dry_run in settings.json, start\n"
          "Ollama, run `python -m engine.cli rag reindex`, then run this again.\n")

if not DB_PATH.exists():
    sys.exit("No database yet. Run: python -m engine.cli load")
copy = Path(tempfile.mkdtemp()) / "copy.db"
shutil.copy2(DB_PATH, copy)
conn = connect(copy)

field = FormField(label=args.question, type=args.type, options=args.options)
result = answer_field(conn, field, profile_values(conn), job_scope=args.scope, job_city=args.city, settings=settings,
                      job_text=job_text)

if job_text is not None:
    from engine.forms.jobpost import read_job_location
    where = read_job_location(job_text, scope=args.scope, city=args.city)
    print(f"JOB LOCATION: {where.kind}" + (f"  (found {where.evidence!r})" if where.evidence else ""))
print(f"QUESTION   : {result.label}")
print(f"ANSWER     : {result.value or '(empty: you fill this yourself)'}")
print(f"SOURCE     : {result.source}" + (f"  (kind: {result.kind})" if result.kind else ""))
print(f"FLAGGED    : {'YES, review it' if result.flagged else 'no'}"
      + ("" if result.recommended else "   NOT RECOMMENDED"))
print(f"CONFIDENCE : {result.confidence:.2f}")
print(f"NOTE       : {result.note}")
if result.matched_question:
    print(f"MATCHED    : {result.matched_question!r}")
conn.close()
