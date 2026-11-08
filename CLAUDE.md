# CLAUDE.md — JobPilot

JobPilot is a personal job-application copilot that runs locally on Windows. **Its core feature is RAG + AI form filling:** I open any application page in the bot's browser, press "Fill this page", and JobPilot fills it from my profile, resumes, projects and answer bank. I review and click Submit myself. Later versions add batch mode with Prosple job discovery (v1), cold emails through Gmail (v2) and hands-off scheduling (v3). **Nothing is ever submitted without my approval.**

The full spec is in SPEC.md (Part 1: spec, Part 2: UI screens, Part 3: roadmap). Before starting work, read only the sections you need: the current phase in Part 3, plus the Part 1 or Part 2 sections it refers to. Don't load the whole file every session.

## Who I am and how to work with me

- I'm a CS student. This is my first large project, and I'm building it to learn as well as to use it.
- **Explain before you write.** For any new concept (Playwright selectors, embeddings, OAuth, etc.), give me a short explanation and a plan, and wait for my OK before writing code.
- Work on **one stage at a time** (see "Current stage" below). Don't build features from later stages.
- Keep changes small. After each working step, tell me to commit and suggest a commit message.
- Don't add a new dependency without asking me first and saying why.
- **Keep ROADMAP.md current so we never lose our place.** At the end of every working step: tick the finished checkboxes in the current phase of `ROADMAP.md`, update its "Where the project is today" table and "Current position" line, and add a line to its Progress log. Do this in the same commit as the work. When a phase is done, also update "Current stage" below. Dependencies still go in `requirements.txt` (after I approve them).
- If something in this file or the spec seems wrong or unclear, ask. Don't guess.

## Current stage

> Update this line at the end of every stage.

**v0 · Phase 0: setup and foundations** (see Part 3 of the spec: v0 = Phases 0–4, the form filler; then v1 batch mode, v2 cold email, v3 hands-off).

v0 scope only (the form filler): profile + 2 resumes (A and B; the picker judges by what each resume actually contains, never by its file name or label), answer bank with location scope and a `kind` per answer (fixed / open / legal / consent / personal), RAG (Ollama `nomic-embed-text` + `sqlite-vec`), form reader (Playwright), answer engine, resume picker, fill + review (stops before Submit), unknown questions list, filled pages history (`filled` → `submitted` / `abandoned`, with passive submit detection in Phase 4), a small local controls page in the existing dashboard (Fill this page, unknown questions, answer bank editor, filled pages history), mock mode and action log. **Not in v0:** job discovery, ranking, batch mode, emails, scheduling, kill switch, encryption. Rules below that mention later features apply once we reach them.

## Stack

- Python 3.13 engine: Playwright (Python), FastAPI, SQLite, `cryptography` (Fernet), `keyring`, `google-genai` (Gemini free tier), `ollama` (local models; provider chosen per task in settings, with fallback from Gemini to Ollama), `sqlite-vec`, pytest. **Later versions only:** `google-api-python-client` (Gmail, v2), APScheduler and `win11toast` (v3), Gemini and Fernet (v3). In v0 all AI is Ollama.
- Dashboard: Next.js + TypeScript + Tailwind in `dashboard/`
- Runs on Windows. Use `pathlib` for every path; never hardcode `C:\...`.

## Folder layout

```
jobpilot/
  engine/
    ai.py            # ask_ai(task, prompt) — the ONLY place that calls Gemini
    db.py            # SQLite connection, schema, encryption helpers
    secrets.py       # keyring wrapper — the ONLY place that reads secrets
    profile.py       # profile, resumes, answer bank
    rag.py           # chunking, embeddings (nomic-embed-text), sqlite-vec retrieval
    matcher.py       # (v1) BM25 pre-filter + AI scoring; resume pick logic
    forms/
      reader.py      # reads every field's label, type and options on the open page
      filler.py      # fills fields, uploads resume, highlights guesses, stops before Submit
      answers.py     # answer engine: code / answer bank / Ollama draft rules
    sites/prosple.py # (v1) job discovery + apply flow for Prosple
    contacts.py      # (v2) search API + Hunter
    mailer.py        # (v2) Gmail send
    safety.py        # safety.check(), action log; later kill switch, blocklist, caps
    api.py           # FastAPI app (binds 127.0.0.1 only)
  dashboard/         # Next.js app (imports design/tokens.css)
  design/
    DESIGN.md        # design rules, type scale, component specs
    tokens.css       # all colours, fonts, sizes as CSS variables
    screens/         # HTML mockups of every screen (source of truth for layout)
  prompts/           # prompt templates (match.md, email.md, form.md)
  fixtures/
    ai/              # canned AI responses for mock mode
    forms/           # saved form HTML (Prosple form, Google Form, career page) for offline tests
    prosple/         # (v1) saved Prosple pages for offline tests
  tests/
  data/              # git-ignored: database, resumes, screenshots, browser profile
```

## Commands

```bash
python -m pytest -q                      # run tests (must pass before every commit)
python -m engine.api                     # start the engine API on 127.0.0.1
cd dashboard && npm run dev              # start the dashboard
playwright codegen https://prosple.com   # record selectors
```

## Run modes (a setting, default = mock)

| Mode      | Site                              | AI                              | Submit / send                                          |
| --------- | --------------------------------- | ------------------------------- | ------------------------------------------------------ |
| `mock`    | saved HTML in `fixtures/forms/` (later `fixtures/prosple/`) | canned JSON from `fixtures/ai/` | never                                                  |
| `dry_run` | real                              | real                            | never: screenshot instead of submit, email only logged |
| `live`    | real                              | real                            | v0: never (I click Submit myself); v1+: after batch approval |

- Every new feature must work in `mock` mode, with a test, before it is tried in `dry_run`.
- Never switch to `live` in code or tests. Only I change the mode, from the dashboard.

## Hard rules (never break these)

1. **No secrets in code, tests, logs or git.** API keys, OAuth tokens and the DB key come from `engine/secrets.py` (keyring). Never create `.env` files with real values.
2. **All AI calls go through `ask_ai(task, prompt)`.** No direct Gemini or Ollama calls anywhere else. `ask_ai` picks the provider (mock / Gemini / Ollama) from settings, so features never care which model answers.
3. **Least data to the AI.** Never put phone, address, email or ID numbers in a prompt. Code fills those fields directly.
4. **No invented facts.** Prompts must tell the AI to use only the provided profile/resume/answer chunks. Legal, eligibility, GPA and "have you ever" questions come only from the answer bank, never from the AI.
5. **Never auto-submit without approval.** The apply flow always stops before Submit. In v0 the form filler **never clicks Submit**: I review and submit myself, and a test must prove no code path clicks it. From v1, applications are queued for batch approval.
5b. **Legal and eligibility questions are answered only from the answer bank.** Work authorization, visa, "have you ever", GPA and similar are never drafted or guessed by the AI; if there's no saved answer, add the question to the unknown questions list.
6. **Check safety before every action.** Before each navigate, fill, submit or send, call `safety.check()` (kill switch, blocklist, daily caps).
7. **Log every action** to `action_log`, with a screenshot for submits and errors.
8. **Never resubmit automatically.** If a submit isn't confirmed, mark it `failed` for me to check.
9. **No LinkedIn automation** in the MVP. The bot never automates logins and never stores passwords: I sign in by hand in the bot's browser profile (Prosple, Google Forms, company career pages).
10. **Gmail uses the `gmail.send` scope only.** Only send to verified email addresses, within the daily cap.
11. Engine and dashboard bind to `127.0.0.1` only.

## Design system (dashboard UI)

The dashboard must follow the design system in `design/`. Don't invent a new look.

- **In v0 the dashboard is only the small controls page** (Fill this page, unknown questions, answer bank editor, filled pages history). Other screens come in v1–v3.
- **Read `design/DESIGN.md` before any UI work.** It holds the rules, the type scale and the component specs.
- **Values come only from `design/tokens.css`.** It's imported in `dashboard/app/globals.css` and mapped into the Tailwind theme (`colors.jp.*`, `fontFamily.sans/serif`, `borderRadius.control/card`). No raw hex values or arbitrary Tailwind colours (`bg-blue-500`, `#1D4ED8`) in components.
- **Layout and copy come from `design/screens/<Screen>.html`.** When building a screen, open its mockup and match its structure, spacing and wording. Placeholder numbers in the mockups are sample data; real values come from the API.
- **Build shared components first** (in `dashboard/components/ui/`), matching `design/screens/Components.html`: StatusChip, ScoreBadge, ModeBadge, FlagMarker, Button (primary/secondary/danger/link), FilterChip, NavItem, Toast, Banner, StatCard, EmptyState, ConfirmDialog, DataTable, Drawer. Screens compose these; they never restyle them inline.
- Status colours are fixed: always use the status token for that status, and always show the status as text too.
- Newsreader font only for page titles and big numbers; Geist for everything else.
- If a screen needs something the design system doesn't define (for example a dark-mode tint or an icon), **ask me**, don't make it up.
- After building a screen, compare it side by side with its mockup and list any differences before calling it done.

## Code style

- Type hints everywhere. Small functions. Docstrings on public functions, written so I can learn from them.
- AI responses are JSON validated with Pydantic models. On invalid JSON, retry once, then log and skip.
- Playwright: prefer role/label/text selectors over CSS classes, use explicit waits, and add random human-like delays between actions (1–4 s).
- Errors are caught per job, so one bad job never stops the run.
- Tests use fixtures and mock mode. They must never touch the real Prosple site, Gemini, Hunter or Gmail.

## Definition of done for a stage

- It works in mock mode and has passing tests.
- I can explain how it works.
- The "Current stage" line above and ROADMAP.md (checkboxes, current position, progress log) have been updated, and the work is committed.
