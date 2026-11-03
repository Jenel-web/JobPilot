# CLAUDE.md — JobPilot

JobPilot is a personal job-application copilot that runs locally on Windows. It finds jobs on Prosple, scores them against my profile, picks one of my two resumes, fills applications with Playwright, writes and sends cold emails through Gmail, and tracks everything on a local dashboard. **I approve every batch before anything is submitted.**

The full spec is in the "JobPilot MVP Spec" doc. Read the section for the current stage before starting work.

## Who I am and how to work with me

- I'm a CS student. This is my first large project, and I'm building it to learn as well as to use it.
- **Explain before you write.** For any new concept (Playwright selectors, embeddings, OAuth, etc.), give me a short explanation and a plan, and wait for my OK before writing code.
- Work on **one stage at a time** (see "Current stage" below). Don't build features from later stages.
- Keep changes small. After each working step, tell me to commit and suggest a commit message.
- Don't add a new dependency without asking me first and saying why.
- If something in this file or the spec seems wrong or unclear, ask. Don't guess.

## Current stage

> Update this line at the end of every stage.

**v0 · Phase 0: setup and foundations** (see the Roadmap tab in the spec: v0 = Phases 0–5, then v1–v4).

v0 scope only: profile + resumes, Prosple scraper, matching + resume picker, dashboard (shell, Home lite, Applications, Emails lite), email *drafts* (no sending, no auto-apply, no contact finder, no RAG yet). Rules below that mention later features apply once we reach them.

## Stack

- Python 3.12 engine: Playwright (Python), FastAPI, SQLite, `cryptography` (Fernet), `keyring`, `google-genai` (Gemini free tier), `ollama` (local models; provider chosen per task in settings, with fallback from Gemini to Ollama), `sqlite-vec`, `google-api-python-client` (Gmail), APScheduler, `win11toast`, pytest
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
    rag.py           # chunking, embeddings, retrieval
    matcher.py       # BM25 pre-filter + AI scoring + resume pick
    sites/prosple.py # scraping + apply flow for Prosple
    contacts.py      # search API + Hunter
    mailer.py        # Gmail send
    safety.py        # kill switch, blocklist, caps, action log
    api.py           # FastAPI app (binds 127.0.0.1 only)
  dashboard/         # Next.js app (imports design/tokens.css)
  design/
    DESIGN.md        # design rules, type scale, component specs
    tokens.css       # all colours, fonts, sizes as CSS variables
    screens/         # HTML mockups of every screen (source of truth for layout)
  prompts/           # prompt templates (match.md, email.md, form.md)
  fixtures/
    ai/              # canned AI responses for mock mode
    prosple/         # saved HTML pages for offline tests
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

| Mode | Site | AI | Submit / send |
|---|---|---|---|
| `mock` | saved HTML in `fixtures/prosple/` | canned JSON from `fixtures/ai/` | never |
| `dry_run` | real | real | never: screenshot instead of submit, email only logged |
| `live` | real | real | only after batch approval |

- Every new feature must work in `mock` mode, with a test, before it is tried in `dry_run`.
- Never switch to `live` in code or tests. Only I change the mode, from the dashboard.

## Hard rules (never break these)

1. **No secrets in code, tests, logs or git.** API keys, OAuth tokens and the DB key come from `engine/secrets.py` (keyring). Never create `.env` files with real values.
2. **All AI calls go through `ask_ai(task, prompt)`.** No direct Gemini or Ollama calls anywhere else. `ask_ai` picks the provider (mock / Gemini / Ollama) from settings, so features never care which model answers.
3. **Least data to the AI.** Never put phone, address, email or ID numbers in a prompt. Code fills those fields directly.
4. **No invented facts.** Prompts must tell the AI to use only the provided profile/resume/answer chunks. Legal, eligibility, GPA and "have you ever" questions come only from the answer bank, never from the AI.
5. **Never auto-submit without approval.** The apply flow always stops before Submit and queues the application.
6. **Check safety before every action.** Before each navigate, fill, submit or send, call `safety.check()` (kill switch, blocklist, daily caps).
7. **Log every action** to `action_log`, with a screenshot for submits and errors.
8. **Never resubmit automatically.** If a submit isn't confirmed, mark it `failed` for me to check.
9. **No LinkedIn automation** in the MVP, and no login to any site other than Prosple.
10. **Gmail uses the `gmail.send` scope only.** Only send to verified email addresses, within the daily cap.
11. Engine and dashboard bind to `127.0.0.1` only.

## Design system (dashboard UI)

The dashboard must follow the design system in `design/`. Don't invent a new look.

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
- The "Current stage" line above has been updated, and the work is committed.
