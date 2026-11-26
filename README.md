<div align="center">

# 🧭 JobPilot

### A local-first, AI-assisted job-application copilot.
**Open any application form. Press one button. Review. Submit it yourself.**

![Status](https://img.shields.io/badge/status-v0%20in%20development-1F6B4F)
![Python](https://img.shields.io/badge/python-3.13-3776AB?logo=python&logoColor=white)
![Playwright](https://img.shields.io/badge/browser-Playwright-2EAD33?logo=playwright&logoColor=white)
![Ollama](https://img.shields.io/badge/AI-Ollama%20(local)-000000)
![SQLite](https://img.shields.io/badge/storage-SQLite%20%2B%20sqlite--vec-003B57?logo=sqlite&logoColor=white)
![Next.js](https://img.shields.io/badge/dashboard-Next.js%20%2B%20TypeScript-000000?logo=nextdotjs&logoColor=white)
![Tests](https://img.shields.io/badge/tests-875%20passing-1F6B4F)
![Privacy](https://img.shields.io/badge/data-never%20leaves%20your%20PC-1F6B4F)

</div>

---

## Why JobPilot exists

Applying for internships and graduate roles means typing the same things into a different form every time: *why do you want this role, when can you start, are you authorized to work here, tell us about a project you're proud of.* Every company words these questions differently, and a tired copy-paste at question 14 is how typos and wrong answers slip in.

JobPilot reads the form in front of you, works out what each question is really asking, and answers it **from your own saved facts**: your profile, your resumes, your project write-ups and a bank of answers you wrote once. It fills the page and highlights anything it is unsure about. **Then it stops. You read it and click Submit.**

> **The one rule that shapes the whole design:** JobPilot never submits anything on its own. A test exists to prove that no code path clicks Submit.

---

## How it works

```mermaid
flowchart LR
    A["🌐 You open an application<br/>in the bot's browser"] --> B["📖 Form reader<br/>label · type · options · required"]
    B --> C{"Personal field?<br/>name, email, phone, city, links"}
    C -- yes --> D["⚙️ Filled by plain code<br/>(AI never sees it)"]
    C -- no --> E["🔎 RAG search<br/>nearest saved question"]
    B --> P["📰 Job post finder<br/>form page → opener tab → same site → ask you"]
    P --> R["📄 Resume picker<br/>A or B, by content"]
    R --> J
    E --> F{"Confident match?"}
    F -- "yes · fixed / protected" --> G["✅ Your saved answer,<br/>used as written"]
    F -- "yes · open" --> H["✍️ Local LLM rewrites it<br/>from retrieved facts only"]
    F -- no --> I["❓ Unknown questions list<br/>+ filled, flagged 'not recommended'"]
    D --> J["🖍️ Fill page + highlight guesses"]
    G --> J
    H --> J
    I --> J
    J --> K["🛑 STOP.<br/>You review and click Submit"]
```

### 1. Reads the page like a person would
Playwright reads every field's label, type, options, placeholder, `autocomplete` hint, length limit and pattern. It copes with the awkward real-world cases: forms inside **iframes** (Greenhouse), **custom `<div>` dropdowns** that aren't `<select>` elements (read as one field with their options), labels that sit in the field's block instead of a `<label for>`, red-star "required" markers, and radio buttons that need merging into a single question.

### 2. Answers from the right source, in a fixed order

| Order | Field type | Who answers | AI involved? |
| :-: | --- | --- | :-: |
| 1 | Name, email, phone, address, city, links, school, degree, year level, graduation year, skills | **Plain code** reading your profile. Phone numbers are reformatted to whatever the field expects (`+63…`, `09…`, bare digits), and a country-code dropdown is set from your number. | ❌ Never |
| 2 | `protected` answers: visa, work authorization, "have you ever…", GPA, consent | Your saved wording, **exactly as written** | ❌ Never |
| 3 | `fixed` answers: availability, salary, relocation | Your saved wording, scoped by location (a *Makati* answer beats the *any* answer) | ❌ Never |
| 4 | `open` answers and brand-new questions: strengths, "tell me about a time…" | A local LLM drafts from **retrieved facts only** (the best 1–2 projects, scored against the question), then it's flagged for your review | ✅ Local only |
| 5 | Company questions: "Why do you want to work here?" | A short brief is copied out of the **job post** (code drops any note the post doesn't back up), and the answer is written from that brief + your notes. No post = a role-focused answer or your saved text | ✅ Local only |
| 6 | Short fact boxes with no saved answer ("Current company") | Left empty for you. Facts are **never** AI-drafted | ❌ Never |
| 7 | No confident match | Added to the **unknown questions list**; filled if possible and flagged **not recommended** | — |

Every AI reply is checked in code before it's used: a number or name that isn't in your notes, any private data, assistant talk ("Sure! Here's…") or an empty reply gets the answer rejected.

### 3. RAG: finding the right saved answer even when it's worded differently
"When can you start?", "Earliest available start date" and "Availability" are one question. JobPilot embeds your saved questions and the incoming one with `nomic-embed-text` (running locally in Ollama), stores the vectors in **`sqlite-vec`**, and ranks by cosine similarity.

- Resumes, projects and answers are chunked separately. Email addresses, phone numbers and ID numbers are **scrubbed before anything is indexed**.
- The index records which embedding model built it and **refuses to search with a different one**, so you can never get silently wrong scores.
- Each saved answer can carry `also_asked_as` wordings modelled on real Greenhouse, Lever, Workday and other forms.

### 4. It learns, but only with your approval
When a question matches a saved one but in *new words*, JobPilot does not quietly remember it. The wording waits in a queue; you run `questions approve ID`, a timestamped backup of `answers.json` is made, and only then is it saved. Protected answers need an extra `--yes-protected` flag, and rejected wordings never come back. One bad match can never become a permanent one.

### 5. Picks the right resume by *content*, never by file name
You keep two resumes (A and B). The picker retrieves the most relevant chunks from each against the job post and returns the choice **with evidence**. Naming a file `backend.pdf` doesn't influence it.

### 6. Finds the job post across your tabs
The resume pick and company answers need the job post. JobPilot looks in a fixed order: the form page itself, then **the tab that opened it** (read from Chrome's own record), then other tabs on the same site, and otherwise it asks you to pick a tab or paste the text. It is read-only, never reads LinkedIn tabs, and rejects search-result lists. Your name, email, phone and address are scrubbed from the post before anything uses it. **No post means no resume upload**, and that's flagged.

### 7. Fills the page, then stops
The filler types text, picks dropdown and radio options, ticks checkboxes, sets dates and uploads the chosen resume under a formal file name, with a random 1–4 s pause between fields. Guesses get a **solid amber outline** and fields that need you get a **dashed** one, drawn in an overlay that doesn't block clicks. Then it takes a screenshot, saves a row to the **filled pages history** (labels and notes only, never the values typed in) and stops.

---

## Safety and privacy by design

| Guarantee | How it is enforced |
| --- | --- |
| **Never auto-submits** | The filler never clicks a button or link. The only clicks allowed are a custom dropdown's box and its options (three helpers, checked by a source-code test), and an in-page click recorder fails the tests if anything else is clicked on the saved pages. |
| **Legal questions are never invented** | Visa, eligibility, GPA, "have you ever" answers come only from the answer bank. Questions with sensitive words are treated as protected even with no saved match. |
| **Least data to the AI** | Phone, address, email and ID numbers never appear in a prompt. A test checks this. |
| **Runs on your machine** | All AI is local Ollama. The engine API refuses to start on any host but `127.0.0.1`, checks the `Host` header on every request (stops DNS rebinding) and only accepts changes from the dashboard's origin. |
| **No invented facts** | Prompts instruct the model to use only the retrieved chunks. Answers it writes are always highlighted. |
| **Own browser, no passwords** | JobPilot launches its own browser profile, never your everyday one. It never automates logins or stores passwords. You sign in by hand. |
| **Every action gated and logged** | `safety.check()` runs before each action; everything goes to an `action_log`. |
| **Three run modes** | `mock` (default: saved HTML, canned AI, offline), `dry_run`, `live`. Only you change the mode; the API shows it but can't change it. In `mock`, filling a real `http(s)` page is refused. |
| **Changes to your answers are reversible** | Every write to `answers.json` (from the CLI or the API) makes a timestamped backup first. |
| **Secrets in the OS keyring** | Windows Credential Manager via `keyring`. Nothing in code, logs or git. Real data lives in a git-ignored `data/` folder. |

---

## Architecture

```text
engine/
  ai.py            the ONLY place that talks to a model (mock / Ollama), Pydantic-validated JSON, one retry
  rag.py           chunking, scrubbing, embeddings, sqlite-vec retrieval
  learning.py      unknown-questions list and approval-gated wording learning
  answers_file.py  reads and writes answers.json, always with a backup first
  profile.py       profile, resumes (pdfplumber), answer bank with location scope
  matcher.py       resume picker (A or B, with evidence)
  safety.py        safety.check() before every action, action log
  secrets.py       the ONLY place that reads secrets (keyring)
  settings.py      run mode and AI provider from settings.json
  db.py            SQLite schema and migrations
  cli.py           every command listed below
  api.py           FastAPI app on 127.0.0.1: guards and read endpoints
  api_write.py     answer, approve, reject, edit and mark-status endpoints
  api_fill.py      the fill job (POST /fill, GET /fill/{id})
  forms/
    browser.py       launches the bot's own Chrome profile
    reader.py        reads every field on the page, including iframes and custom dropdowns
    capture.py       saves a page as an offline test fixture, personal data removed
    answers.py       personal fields by code, sensitive-question detector, the answer rules
    drafting.py      AI drafts, rewrites and the company brief, with code checks on every reply
    jobpost.py       job location and relocation logic
    jobfinder.py     finds the job post across your tabs (read-only)
    filler.py        fills fields, uploads the resume, outlines guesses, never clicks Submit
    orchestrator.py  "Fill this page": reader → job post → resume → answers → filler → history
    history.py       filled pages history (filled → submitted / abandoned)
prompts/           form.md and resume.md prompt templates
dashboard/         Next.js + TypeScript + Tailwind, driven by design/tokens.css
design/            design system, tokens and HTML mockups of every screen
fixtures/          saved forms and canned AI responses for offline tests
scripts/           api_sandbox.py: runs the API on a COPY of your data, in mock mode
tests/             875 tests, no network required
```

**Design-system-first dashboard.** The UI is built from 25 shared components that follow a written design system (`design/DESIGN.md`) with every colour, font and size defined once in `design/tokens.css`. No raw hex values appear in components.

---

## Quick start (Windows)

**Prerequisites:** Python 3.13, Node.js, Google Chrome, and [Ollama](https://ollama.com) with the models pulled:

```powershell
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

**Set up**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

**Add your data** (this folder is git-ignored, so it stays on your machine)

1. Copy `data/profile.example.json` to `data/profile.json` and fill it in.
2. Put your resume PDFs in `data/resumes/`.
3. Write your answers in `data/answers.json`, using `data/answers.example.json` as a guide.

**Run**

```powershell
python -m engine.cli load              # profile, resumes and answers into SQLite
python -m engine.cli profile show      # sanity check (email and phone are masked)
python -m engine.cli rag reindex       # build the search index
python -m engine.cli rag ask "When can you start?"
python -m engine.cli browser open      # open the bot's browser and log in by hand
python -m engine.cli forms read        # list the fields of the open page
python -m engine.cli forms fill --mode dry_run   # fill the open page, then stop before Submit
python -m engine.api                   # start the engine API on 127.0.0.1
python -m pytest -q                    # run the test suite (offline)
```

The default run mode is `mock`: fake vectors, saved pages, nothing real touched. For real similarity scores, start Ollama and set `run_mode` to `dry_run` in `settings.json`.

<details>
<summary><b>All CLI commands</b></summary>

| Command | What it does |
| --- | --- |
| `load` | Copy profile, resumes and answers into the database |
| `profile show` | Print the profile with email and phone masked |
| `answers list [--kind fixed\|open\|protected]` | Print the answer bank |
| `rag reindex` | Rebuild the search index |
| `rag ask "..."` | Show the 5 chunks closest to a question |
| `rag eval` | Run every question in the eval set |
| `resume pick --post FILE` | Pick resume A or B for a saved job post, with evidence |
| `questions list` | Show unknown questions and wordings waiting for approval |
| `questions approve ID [--yes-protected]` | Save a new wording (backup first) |
| `questions reject ID` | Discard a wording for good |
| `browser open` | Open the bot's browser |
| `forms read` | List the fields of the open page (read-only) |
| `forms capture NAME` | Save the page as a sanitised offline fixture |
| `forms answer --fixture NAME [--record]` | Show the answer engine's decision for each field of a saved page (preview) |
| `forms elaborate --fixture NAME` or `--question "..."` | Preview how short yes/no answers are expanded |
| `forms why-company [--tab TEXT] [--post FILE]` | Preview the "Why do you want to work here?" answer for a job post |
| `forms fill [--tab TEXT] [--post FILE] [--resume A\|B] [--mode mock\|dry_run] [--fixture NAME] [--fast]` | Fill the open page (or a saved one) and stop before Submit. `--mode` applies to this run only; `live` is never allowed |

</details>

<details>
<summary><b>Engine API</b> (127.0.0.1 only; the controls page uses it)</summary>

| Endpoint | What it does |
| --- | --- |
| `GET /health` | Status and the current run mode (read-only) |
| `GET /unknown`, `/wordings`, `/answers`, `/fills?status=&limit=` | Read the unknown questions, suggested wordings, answer bank and filled pages history |
| `POST /unknown/{id}/answer` | Answer an unknown question (backup, save, re-index) |
| `POST /wordings/{id}/approve` · `/reject` | Approve a wording (protected answers need `confirm_protected`) or reject it |
| `POST /answers` · `PUT` / `DELETE /answers/{id}` | Add, edit or delete a saved answer |
| `POST /fills/{id}/status` | Mark a filled page `submitted` or `abandoned` |
| `POST /fill` · `GET /fill/{job_id}` | Start "Fill this page" in the background and poll for the result (one fill at a time). Optional body: `post_text`, `post_tab_url`, `no_resume`, `resume` |
| `GET /status` | Run mode, whether the bot's Chrome is open, the page you are looking at, and the running fill (read-only) |
| `GET /jobpost` | The job post a fill would use for the current page, plus your other tabs for Change (read-only) |
| `GET /fills/{id}/screenshot` | The screenshot taken after that fill (only PNGs inside `data/screenshots/`) |

To try it without touching your real files: `python scripts\api_sandbox.py` (a copy of your data, mock mode, port 8001).

</details>

---

## What is built and what is not (honest status)

JobPilot is built in stages, and each stage must work in mock mode with tests before it is trusted on a real site.

| Stage | Scope | State |
| --- | --- | :-: |
| **v0 · Phase 0** | Repo, design system, AI layer with mock + Ollama | ✅ Done |
| **v0 · Phase 1** | Profile, resumes, answer bank in SQLite, safety gate, keyring | ✅ Done |
| **v0 · Phase 2** | Form reader: iframes, custom dropdowns, offline fixtures | ✅ Done |
| **v0 · Phase 3** | RAG, unknown-question learning, personal-field detector, answer rules for fixed / open / protected, resume picker | ✅ Done |
| **v0 · Phase 4** | Filler ✅ · job post finder ✅ · "Fill this page" orchestrator + filled pages history ✅ · company answers from the job post ✅ · engine API ✅ · controls page ✅ · on-page Fill panel 🚧 · passive submit detection 🚧 · audit fixes (4 bugs) 🚧 · a week of real use 🚧 | 🚧 In progress |
| **v1** | Prosple job discovery and batch mode with approval | 📋 Planned |
| **v2** | Cold email through Gmail (`gmail.send` only) | 📋 Planned |
| **v3** | Scheduling, kill switch, encryption at rest | 📋 Planned |

Today you fill a page from the command line (`forms fill`) or through the API (`POST /fill`). The dashboard shell, 25 shared components and the Home, Applications and Review screens exist but still run on mock data. The v0 controls page that calls the API is the next step; mockups for its Wordings tab and for the on-page Fill panel are drawn.

Full plan: [ROADMAP.md](ROADMAP.md) · full specification: [SPEC.md](SPEC.md).

---

## Limits (please read)

Stating these plainly is part of the design.

**Not built yet**
- **No button to press yet.** Filling works from the command line and the API; the controls page and the on-page Fill panel aren't built.
- **No passive submit detection yet.** You mark a filled page `submitted` or `abandoned` yourself (through the API for now).
- **Some fields are left to you:** date pickers built as custom widgets, and terms-and-conditions checkboxes (on purpose).
- **No job discovery, ranking, batch mode, emails or scheduling** in v0.
- **No kill switch or encryption at rest** until v3. Data sits in a local SQLite file.

**By design**
- **It will never click Submit in v0.** That is the product, not a missing feature.
- **No LinkedIn automation, and no logging in for you.** You sign in by hand.
- **Windows-first.** Paths, keyring and Chrome launch are tested on Windows only.

**Honest AI limits**
- **A small local model is a small local model.** `llama3.1:8b` on a CPU-only laptop takes seconds per answer, and a cold start takes about 20 s. It was tested as a "same question?" judge and **rejected as unreliable** (it confused *visa sponsorship* with *work authorization*). That is exactly why legal answers never go through it.
- **Matching isn't magic.** On a small held-out set, `nomic-embed-text` found the right saved question for 6 of 6, but two of those scored just under the 0.85 cutoff and were flagged rather than trusted. The sample is small, and the alternate wordings were written after seeing the first eval set, so treat early accuracy as optimistic.
- **Questions nobody answered before get flagged, not trusted.** Open answers are drafts for you to read, not finished work.
- **The resume picker is only so-so.** It chose correctly on 3 of 5 sample job posts (the target was 4 of 5), and its evidence lines sometimes repeat the job post. Check its choice.
- **Odd forms will break it.** Heavily custom widgets, CAPTCHAs and bot checks need you. A custom dropdown value that isn't in the visible list is searched for and flagged, and left empty if it can't be found.
- **Only tested on a few real forms** (Workable, Greenhouse-in-iframe, a careers-page.com form, Shopee careers, plus synthetic forms). The full fill hasn't had its week of real use yet. Treat every new site as unproven until you've reviewed its fill.
- **Single user, single machine.** This is a personal tool, not a hosted service.

---

## Engineering decisions worth noting

| Decision | Why |
| --- | --- |
| Personal fields by code, never by AI | Faster, exact, and keeps private data out of prompts |
| Protected answers are never sent to the model | A wrong visa answer is worse than a slow form |
| Measured, then rejected, a bigger embedding model | `mxbai-embed-large` scored 4–5/6 vs `nomic-embed-text` at 6/6 and ran 2–3× slower |
| Learned wordings need approval | One wrong match must not become a permanent one |
| `mock` is the default mode | Every feature is tested offline before it touches a real site |
| Own browser profile | Your everyday Chrome and logins stay untouched |
| One `ask_ai()` entry point | Swapping models or providers is a settings change, not a refactor |
| Facts are never AI-drafted | "Current company" with no saved answer stays empty; a confident wrong fact is worse than a blank |
| AI replies are checked in code | Names and numbers must appear in your notes, or the answer is rejected |
| The fill job is polled, not streamed | Simpler, and one fill at a time is all a single user needs |

---

## Roadmap

- [x] Reader that survives iframes and custom widgets
- [x] RAG with scrubbed chunks and a model-aware index
- [x] Approval-gated learning of new question wordings
- [x] Answer engine for fixed / open / protected answers
- [x] Resume picker with evidence
- [x] Filler that stops before Submit, with a test proving it
- [x] Job post finder and company answers from the post
- [x] "Fill this page" orchestrator, filled pages history and engine API
- [ ] Controls page: Fill this page, unknown questions, answer bank editor, history
- [ ] On-page Fill panel and passive submit detection
- [ ] A week of real applications, then tag `v0.1`
- [ ] v1 batch mode · v2 cold email · v3 hands-off

---

## Built to learn

JobPilot is a student project, built to be used and to be understood. Each stage is explained before it is coded, kept small, and committed in working steps.

<div align="center">

*Nothing is ever submitted without your approval.Project will take about a month. *

</div>
