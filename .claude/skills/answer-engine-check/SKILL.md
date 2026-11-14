---
name: answer-engine-check
description: Regression check for the JobPilot answer engine. Run after changing engine/forms/answers.py, drafting.py, learning.py, rag.py or prompts/*.md. Runs the answer tests, then pushes a fixed set of sample questions through every path (personal, protected, fixed, sensitive, open, reflective, company) and compares to expected behaviour. Run it with /answer-engine-check.
disable-model-invocation: true
---

# answer-engine-check

The answer engine has strict rules. This skill checks them without the user re-testing by hand.

## 1. Unit tests first

```
.venv\Scripts\python.exe -m pytest tests/test_answers.py tests/test_answer_engine.py tests/test_drafting.py tests/test_reflective.py tests/test_sensitive.py tests/test_learning.py tests/test_about_me.py tests/test_project_selection.py -q
```

If any fail, report them and stop.

## 2. Sample questions through the real engine

Use `ask_engine.py` in the project root. It works on a COPY of the database, so the real unknown-questions list is untouched. Check `settings.json` first:

- `run_mode: mock` → only the wiring is checked (fake vectors, canned AI). Say so in the report.
- `run_mode: dry_run` → real Ollama. This needs Ollama running and `python -m engine.cli rag reindex` done. If Ollama is not reachable, say so and skip the AI cases. Never switch the mode yourself and never use `live`.

Run each question in [questions.md](questions.md) like:

```
.venv\Scripts\python.exe ask_engine.py "<question>" --type <type> [--options ...] [--scope ...]
```

## 3. Compare to the expected behaviour in questions.md

Each case lists the path it must take and the rules it must not break. Report a table: question, path taken, pass/fail, and a one-line reason for any fail.

Hard rules (any break is a FAIL, call it out first):

- Personal fields (name, email, phone, address, links) come from code, never from the AI.
- Protected answers are exact and flagged; never rewritten.
- Sensitive questions (legal, eligibility, identity) never get an AI answer; weak match = closest saved, marked NOT RECOMMENDED.
- Company questions ("Why do you want to work here?") are NOT answered by the AI until a job post exists.
- Drafts contain no email or phone, are first person, and every number or name appears in the facts given.
- Reflective answers: the closing is a humble opinion (I think / What I do is), no self-praise, at most 2 examples.
- Nothing is typed into a browser and nothing is submitted.

## 4. Report

Summarise: tests result, table of cases, and any regression compared with the expected behaviour. Do not "fix" the expected behaviour to make a case pass. If the expectation itself seems wrong, ask the user.

If the user adds a new kind of question that went wrong in real use, offer to add it to questions.md.
