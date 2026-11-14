---
name: finish-step
description: Close out a working step in JobPilot. Runs the tests, updates ROADMAP.md (checkboxes, "Where the project is today" table, "Current position", Progress log) and suggests a commit message. Run it by hand with /finish-step after a step works.
disable-model-invocation: true
---

# finish-step

CLAUDE.md requires every working step to end the same way. Do these in order and stop at the first failure.

## 1. Run the tests

```
.venv\Scripts\python.exe -m pytest -q
```

If anything fails, report the failing test names and output, and stop. Do not update ROADMAP.md for a step that is not green.

## 2. Work out what the step was

Run `git status` and `git diff --stat`. Summarise the step in one sentence in plain words. If the diff mixes two unrelated changes, say so and suggest two commits.

## 3. Update ROADMAP.md (same commit as the work)

Read only the parts you need: section 1 ("Where the project is today"), the current phase's checklist and the end of the Progress log.

- Tick the checkboxes in the current phase that this step finished. Do not tick anything that is not done.
- Update the row(s) in the "Where the project is today" table that this step changed, including the test count from step 1.
- Rewrite the "Current position" line so it says what is built and what is next.
- Add ONE line at the end of the Progress log: `- YYYY-MM-DD: <what changed> (<N> tests pass).` Use today's date.
- If the phase is now fully done, also update the "Current stage" line in CLAUDE.md.

## 4. Hand back to the user

Show: tests result, what you changed in ROADMAP.md (short), and a suggested commit message in the style of the repo (`feat: ...`, `fix: ...`, `docs: ...`). Tell the user to commit. Do not commit yourself unless asked.

## Rules

- Never add dependencies here. If the step added one that is not in requirements.txt, flag it and ask.
- Never put real personal data in ROADMAP.md.
