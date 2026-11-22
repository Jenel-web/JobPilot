"""Throwaway viewer: what did "Fill this page" save? Read-only. Delete when done (don't commit it).

Usage:
    python -m scripts.show_fills          # the last 5 fills, the open unknown questions, the last 12 log rows
    python -m scripts.show_fills 12       # the last 12 fills
"""

import json
import sys

from engine.db import connect, init_db

count = int(sys.argv[1]) if len(sys.argv) > 1 else 5
conn = connect()
init_db(conn)

print("=" * 70, "\nFILLED PAGES (newest first)")
rows = conn.execute("SELECT * FROM fills ORDER BY id DESC LIMIT ?", (count,)).fetchall()
if not rows:
    print("  (no fills saved yet)")
for r in rows:
    linked = conn.execute("SELECT count(*) FROM action_log WHERE fill_id = ?", (r["id"],)).fetchone()[0]
    print(f"\n#{r['id']}  {r['filled_at']}  status={r['status']}")
    print(f"  url        : {r['url'][:90]}")
    print(f"  job title  : {r['job_title'] or '(none: no job post was found)'}")
    print(f"  resume     : {r['resume_id'] or '(none uploaded)'}")
    print(f"  counts     : filled={r['filled_count']}  flagged={r['flagged_count']}  log rows linked={linked}")
    print(f"  screenshot : {r['screenshot_path']}")
    for item in json.loads(r["flagged_fields"]):
        print(f"    ▲ {item['outcome']:<9} {item['label'][:45]:<45} {item['note'][:60]}")

print("\n" + "=" * 70, "\nUNKNOWN QUESTIONS (open)")
unknown = conn.execute(
    "SELECT id, question_text, times_seen, page_url FROM unknown_questions WHERE status = 'open' ORDER BY id DESC LIMIT 10"
).fetchall()
if not unknown:
    print("  (none)")
for u in unknown:
    print(f"  #{u['id']}  seen {u['times_seen']}x  {u['question_text'][:60]}")

print("\n" + "=" * 70, "\nLAST 12 LOG ROWS (action_log)")
for log in reversed(conn.execute("SELECT * FROM action_log ORDER BY id DESC LIMIT 12").fetchall()):
    print(f"  {log['id']:>4} {log['kind']:<10} fill#{log['fill_id'] or '-':<4} {str(log['target'])[:40]:<40} {str(log['details'])[:50]}")
