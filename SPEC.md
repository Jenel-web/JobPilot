# JobPilot MVP Spec

Exported from the "JobPilot MVP Spec" doc (Nov 4, 2026), updated Nov 9, 2026 when the plan changed to put RAG + AI form filling first. Three parts:

- **Part 1: Spec** — what JobPilot is, features by version, architecture, stack, data model, security, run modes, risks
- **Part 2: UI screens** — every dashboard screen in detail (with the version that builds each), the v0 controls page, plus user scenarios
- **Part 3: Roadmap** — the build order (v0 form filler in 5 phases, then v1 batch mode, v2 cold email, v3 hands-off), with checklists, prompts and commands

> **For AI assistants:** the current build scope is set by "Current stage" in `CLAUDE.md`. **The core feature of JobPilot is RAG + AI form filling.** Job discovery, batch mode, cold email and scheduling are later versions built on top of it. Part 1 describes the full plan; build only what the current phase in Part 3 asks for. Read only the section you need.

---

# Part 1: Spec

## Overview

JobPilot is a job-application copilot that runs on your Windows PC. Its core is a form filler: you open any job application page in the bot's browser, press **Fill this page**, and JobPilot reads the form and fills it from your profile, resumes, projects and a saved answer bank (found with RAG, so differently worded questions still find the right answer). It highlights anything it guessed, then stops. **You review and click Submit yourself.** Later versions add job discovery, batch mode, cold emails and scheduling around that same filler.

**Goals**

- v0: fill any application page correctly (Prosple's own form, Google Forms, company career pages) so each application takes minutes of review instead of long typing.
- Never invent facts: personal fields are filled by code, known questions come from the answer bank, new open questions are drafted from your real facts and flagged, legal and eligibility questions are never guessed.
- Keep one place that shows every page JobPilot filled and whether you submitted it.
- Later: apply in batches (v1), send personal cold emails (v2), run hands-off (v3).
- Learn real skills along the way: browser automation, LLM APIs, RAG, OAuth, and a full-stack app.

**Non-goals**

- No resume tailoring. The AI only chooses between your two existing resumes.
- No LinkedIn login or LinkedIn automation of any kind.
- The bot never automates logins and never stores passwords. You sign in by hand in the bot's browser.
- In v0 the bot never clicks Submit.
- No paid AI or paid services. Free tiers only.

## Features by version

| Version | Feature | What it does |
| --- | --- | --- |
| **v0** | Profile + resumes | Personal details, education, links, job preferences, and 2 resumes (A and B) with a label of your choice. The resume picker decides from each resume's actual content, never from its label or file name. |
| v0 | Answer bank with location scope | Saved answers; salary, relocation and similar answers have a scope (any / city / remote / abroad) so they fit the job's location. |
| v0 | RAG | Profile, resumes, projects and answer bank are chunked and embedded (Ollama `nomic-embed-text` + `sqlite-vec`), so a differently worded question finds the right saved answer. |
| v0 | Form reader | Playwright reads every field's label, type and options on the page you opened. |
| v0 | Answer engine | Personal fields (name, phone, address) filled by code and never sent to AI. Known questions come from the answer bank. New open questions are drafted by Ollama from your real facts only and flagged. Legal and eligibility questions are never guessed. |
| v0 | Resume picker | Finds the job post (on the form page, the tab that opened it, a same-site tab, or asks you; see "Finding the job post"), compares it with the content of both resumes (skills, projects, experience) and uploads the better one under a formal file name (e.g. `Your Name.pdf`). No job post found = no resume uploaded, flagged. |
| v0 | Fill + review | Fills everything, highlights guessed answers, stops before Submit, never clicks Submit. |
| v0 | Unknown questions list | Questions with no saved answer are saved so you answer each one once. |
| v0 | Filled pages history | One row per "Fill this page": URL, job and company, resume used, flagged count, screenshot, status `filled` → `submitted` / `abandoned`. You mark it, or (Phase 4) passive detection offers to. |
| v0 | Controls page | A small local dashboard: Fill this page, unknown questions, answer bank editor, filled pages history (see Part 2). |
| v0 | On-page Fill button | A small floating JobPilot panel on every page in the bot's browser: Fill this page, the job post used, progress and result, without switching to the dashboard (Phase 4). |
| v0 | Safety basics | Mock mode, action log, safety check before every action. |
| **v1** | Batch mode | Prosple job discovery with filters and duplicate detection; BM25 pre-filter + Ollama match score; background filling with the v0 filler; Review batch screen; Submit approved with confirmation check (never resubmit); full Applications tracker with manual statuses, notes and a Needs manual apply tab; Home screen; kill switch; daily cap. |
| **v2** | Cold email | Contact finder (search API + Hunter, verified emails, source link saved); email writer using only your real projects with `facts_used`; personal vs short tiers; Gmail API send-only with daily cap and spacing; review for the first 2 weeks, then an auto-send switch; Emails screen; blocklist. |
| **v3** | Hands-off | Scheduler with active hours and class pauses; Windows alerts; CAPTCHA/logout handling; encryption of personal fields; AI provider per task with Gemini → Ollama fallback; Settings, Profile, Activity log, onboarding, empty/error screens; a first week live at a low cap. |

**Not in v0:** job discovery, ranking, batch mode, emails, scheduling.

**Later (optional)**

- More job boards as site adapters (JobStreet, Indeed, Kalibrr).
- Gmail reply tracking that updates statuses automatically (needs read permission).
- Follow-up emails after a few days without a reply.
- LinkedIn note drafting that you send yourself (no LinkedIn automation).
- A Chrome extension for your everyday Chrome (toolbar or side panel "Fill this page"). Not in v0 because it would need the reader and filler rewritten in JavaScript (extensions can't run Playwright), a secret token so websites can't call the `127.0.0.1` engine, and it breaks the Phase 2 decision that the bot never uses your everyday Chrome profile. Revisit after v0's week of real use. The v0 answer is the on-page Fill button in the bot's browser (Part 2, 1b).

## How it works

Code does every action and the AI only answers questions. Playwright drives a browser, SQLite stores everything, and the AI (Ollama locally; Gemini optional from v3) is called at a few points and returns JSON that the code acts on.

**Flow of one page in v0:**

```
You open an application page in the bot's browser and press "Fill this page"
  → Form reader: every field's label, type and options (Playwright)
  → Answer engine, per field:
       personal field (name, phone, address)   → filled by code, never sent to AI
       known question                           → answer bank (found with RAG, scope matches the job's location)
       new open question                        → Ollama drafts from retrieved real facts, flagged
       legal / eligibility question             → answer bank only; otherwise unknown-questions list
  → Job post finder: form page → opener tab → same-site tab → ask you (see below)
  → Resume picker: job post text vs. both resumes, uploads resume A or B (AI, 1 call)
  → Fill + review: fills the form, highlights guesses, STOPS before Submit
  → Filled pages history row + screenshot saved (status: filled)
  → YOU review and click Submit
  → You mark it submitted (or passive detection offers to, Phase 4)
Every step logs to SQLite, and the controls page reads it.
```

**Finding the job post (v0).** The application form is often on a different page or tab from the job description. The bot can see every tab in its own browser profile (never your everyday Chrome), so it looks in this order and stops at the first hit:

1. **The form page itself.** Many sites (Workable, Greenhouse, Prosple) show the description beside or above the form: a long text block with headings like Responsibilities, Requirements or Qualifications.
2. **The tab that opened the form.** Clicking Apply on a job post that opens a new tab makes the job post the form tab's opener (Playwright `page.opener()`).
3. **Another open tab on the same site or company**, for example `careers.acme.com/job/123` next to `careers.acme.com/job/123/apply`.
4. **Ask you.** The controls page lists your open tabs ("Which one is the job post?") and has a box to paste the text.

Rules: the controls page always shows which job post was used (title + tab) with a **Change** button, before the resume is uploaded. If no job post is found, no resume is uploaded; the field is flagged and you are asked. The job post text (never your personal details) is also given to the AI when it drafts open answers such as "Why do you want to join us?".

**Flow later (v1–v2):** find jobs → score + pick resume → fill in the background → Review batch (you approve) → submit approved → find contact → write cold email → send (capped).

A page costs about 1–2 AI calls in v0: one to pick the resume and one to draft open questions (batched).

**Where the AI is used**

- **Form answers:** field labels + retrieved profile and answer-bank snippets in, `{field: answer, confidence, source}` out. Low confidence = flagged; no match = unknown-questions list.
- **Resume pick:** job post text + the most similar chunks of each resume (found with RAG) in, `{resume: "A"|"B", reason, evidence}` out. It judges by resume content, not by file name or label.
- **RAG retrieval:** profile, resumes, projects and answer bank are split into chunks and embedded. Each task pulls only the top matching chunks.
- **Match score (v1) and cold email (v2):** job post + profile summary in, `{score, reasons, missing_skills, resume}` out; job, contact and your matching projects in, subject + body + `facts_used` out.

**What stays out of the AI:** phone number, home address, ID numbers and similar fields are filled by code directly from the database.

**Claude Pro vs the app's AI:** Claude Pro (with Claude Code) is the coding assistant for building JobPilot. It does not give the app an API key. The running app uses Ollama (local) and, from v3, optionally the Gemini API free tier.


## Stack

Python runs the engine, and Next.js runs the dashboard. Everything is free, and everything runs on your Windows PC.

| Part | Choice | Why |
| --- | --- | --- |
| Language | Python 3.13 | Best libraries for automation and AI |
| Browser automation | Playwright for Python, with a dedicated persistent browser profile (you log in by hand to Prosple and other sites) | Real logged-in sessions; `playwright codegen` records selectors |
| Engine API | FastAPI | Dashboard talks to the engine over localhost; used in EconLens |
| Database | SQLite (+ `cryptography` Fernet for sensitive columns from v3) | One file, no server |
| Secrets | `keyring` → Windows Credential Manager | No API keys in `.env` files that could get committed |
| AI | Ollama (local) in v0; Gemini API free tier via `google-genai` optional from v3 | Free; structured JSON output |
| Embeddings + RAG | Ollama `nomic-embed-text` + `sqlite-vec` | Vectors live in the same SQLite file |
| Email | Gmail API via `google-api-python-client`, `gmail.send` scope only | Official OAuth, can only send |
| Contacts | Google Programmable Search or Brave Search API + Hunter API | Names and titles without logging into LinkedIn; verified emails |
| Scheduling | APScheduler | Runs jobs while the PC is on |
| Notifications | `win11toast` | Windows pop-ups |
| Dashboard | Next.js + TypeScript + Tailwind | Used in Countdown Game |
| Tests | pytest + saved HTML fixtures | Test scrapers offline |

Free-tier limits for Gemini, the search API and Hunter change often. Check the current numbers on each provider's site before building those parts.

**Local AI: Ollama.** All AI calls go through one `ask_ai()` function. A setting picks the provider per task:

| Task | Suggested provider | Version | Why |
| --- | --- | --- | --- |
| Form answers | Ollama | v0 | Your personal details never leave the PC |
| Resume pick | Ollama | v0 | Short JSON, private, no quota |
| Embeddings (RAG) | Ollama (`nomic-embed-text`) | v0 | Free and fast locally |
| Match score | Ollama | v1 | Many calls, short JSON, no quota |
| Cold emails | Ollama or Gemini | v2 / v3 | Writing quality matters most here; Gemini needs the v3 provider setting |

Model size depends on the PC: a 7–8B model needs about 8 GB of GPU VRAM; a 3–4B model (e.g. `qwen3:4b`, `gemma3:4b`, `llama3.2:3b`) works on 4–6 GB VRAM or 8–16 GB RAM. Local models follow JSON instructions less reliably, so Pydantic validation and one retry are required. In v0 everything uses Ollama. From v3, if Gemini's quota runs out, the app falls back to Ollama for that task.

## Data model

Eleven SQLite tables hold everything. Columns marked (enc) are encrypted from v3. **v0 uses `profile`, `resumes`, `chunks`, `answers`, `unknown_questions`, `fills` and `action_log`.** `jobs` and `applications` arrive in v1, `contacts` and `emails` in v2.

| Table | Key columns |
| --- | --- |
| `profile` | name, email (enc), phone (enc), address (enc), school, year_level, grad_year, location, links, preferred_locations, job_types |
| `resumes` | id (A/B), label (your own name, display only), file_path, upload_name (the formal name the employer sees, default `<Full Name>.pdf`), extracted_text |
| `chunks` | source (profile/resume/answer), text, embedding |
| `answers` | question, answer, location_scope (any / city / remote / abroad), kind (fixed / open / protected), times_used |
| `unknown_questions` | question_text, job_id, first_seen, status (open/answered) |
| `fills` | url, job_title, company, resume_id, filled_fields, flagged_fields, screenshot_path, status (filled → submitted / abandoned), filled_at, submitted_at (v0 filled pages history; v1 extends it into `applications`) |
| `jobs` | source, url, title, company, location, job_type, posted_at, text, fingerprint (for duplicates), apply_type (native/external) |
| `applications` | job_id, score, reasons, resume_id, status (new → queued → approved → submitted / rejected / failed / manual), filled_fields, flagged_fields, submitted_at, screenshot_path |
| `contacts` | company, name, title, email (enc), email_verified, source_url |
| `emails` | application_id or company, contact_id, tier (personal/short), subject, body, status (draft → queued → sent / failed / bounced), sent_at |
| `action_log` | time, kind (navigate, fill, submit, email, error, captcha), target, details, screenshot_path |

Settings (daily caps, score thresholds, filters, blocklist, run mode, the auto-send switch for emails) live in a `settings` table or a JSON file.

## Security and privacy rules

These rules are requirements, not suggestions. Each one should have a test or a check.

1. **No secrets in the repo.** API keys, the Gmail OAuth token and the database key live in Windows Credential Manager via `keyring`. `.gitignore` covers `data/`, `*.db`, `*.env*`, `profiles/`, `screenshots/`, and the resumes folder.
2. **Encrypt personal fields (v3).** Phone, address, email and contact emails are encrypted with Fernet. The key is stored in Credential Manager.
3. **Least data to the AI.** Each prompt gets only the retrieved chunks it needs. Phone, address and ID numbers are never sent; code fills those fields directly.
4. **No invented facts.** The AI may only use facts from the profile, resumes and answer bank. Legal, eligibility, GPA and "have you ever" questions come only from the answer bank. Otherwise they go to unknown questions.
5. **Least permission.** Gmail uses the `gmail.send` scope only. The bot uses its own Chrome profile, separate from your everyday browser.
6. **Never store site passwords.** The bot never automates logins. You sign in by hand to Prosple or any other site in the bot's browser profile, and the tool reuses that session.
7. **Localhost only.** The FastAPI engine and the dashboard bind to `127.0.0.1`, never `0.0.0.0`.
8. **Never click Submit in v0.** The form filler fills and stops. Legal and eligibility questions are answered only from the answer bank.
9. **Kill switch (v1).** One dashboard button stops all browser actions and emails within a second. The engine checks a stop flag before every action.
10. **Blocklist. (v2)** Companies, domains and people that must never get an application or email. Checked before every submit and send.
11. **Action log.** Every navigate, fill, submit and email is logged, with a screenshot for submits and errors.
12. **Contact data stays local.** Names and emails of other people are never shared or exported. Check the Philippine Data Privacy Act before sharing the tool with others.

## Run modes

Three modes share the same code. Only two switches change: whether the AI is real, and whether submit and send are real. **In v0, no mode ever clicks Submit or sends email**; the filler always stops for you. Live mode only matters from v1.

| Mode | Prosple | AI | Submit | Email | Use it for |
| --- | --- | --- | --- | --- | --- |
| Mock | Saved HTML pages (`fixtures/forms/`, later `fixtures/prosple/`), offline | Fake: canned JSON from `fixtures/ai/` | Never | Never; saved to the log | Building and testing the plumbing, no quota used |
| Dry run | Real site | Real AI calls | Never; screenshot of the filled form instead | Never; shown in the log for reading | Checking quality of matches, answers and emails |
| Live | Real site | Real | After batch approval | Real (reviewed for the first 2 weeks) | Actual applying |

**How the fake AI works.** All AI calls go through one function, `ask_ai(task, prompt)`. In mock mode it skips the model and returns a pre-written answer for that task, such as `{"score": 78, "resume": "A"}`. Tests can also choose the answer, for example a low score, to check that the job gets skipped.

**How saved pages work.** Run once against Prosple in a record mode that saves each page's HTML into `fixtures/prosple/`. Mock mode loads those files instead of the live site, so scraper tests run offline and never touch the real site.

The current mode shows as a coloured badge on every dashboard screen, so live mode is never a surprise.

## Limits, risks and edge cases

Rows marked (v1+) apply once batch mode exists. Each risk has a planned response.

| Situation | What JobPilot does |
| --- | --- |
| Field type the reader doesn't recognise, or a custom widget (v0) | Leaves it empty, adds it to the report as "needs you", logs a screenshot |
| Multi-step form (v0) | Fills the visible step; you press Fill this page again on the next step |
| Form needs a Google sign-in, or a "Sign in with Google" button (v0) | You sign in once by hand in the bot's Chrome; the persistent profile keeps you signed in. The bot never types the password, never signs in or out, and never navigates inside Gmail or Drive. If Google refuses the sign-in ("This browser or app may not be secure"), open the bot's profile on its own without JobPilot attached, sign in, close it, then let JobPilot reopen it. `data/browser_profile/` holds the login, so it stays git-ignored and is never shared or synced |
| Job post is in another tab, or not open at all (v0) | Looks on the form page, then the opener tab, then same-site tabs; if still not found, asks you to pick a tab or paste the text. Never guesses the resume: no job post = no upload, flagged |
| You submit without marking it (v0) | Stays `filled` in the history; passive detection (Phase 4) offers to mark it |
| AI or Hunter free quota used up (v1+) | Spends quota on the best matches first, queues the rest for tomorrow, alerts you |
| CAPTCHA, logout or 2FA on Prosple | Pauses Prosple, Windows alert, logs it; you solve it in the bot's browser and press Resume |
| Page layout changed, field not found | Skips the job as "needs manual apply", logs a screenshot |
| Listing redirects to an employer site | Marked "manual" with the link; no automation in the MVP |
| Same job seen twice | Fingerprint (company + title + location) blocks a second application |
| Already applied to the company recently | Warns in the review batch; never applies twice to the same company + role |
| Required question with no answer | AI suggests one, flags it; legal/eligibility questions are never guessed |
| Location-dependent question | Uses the answer whose location scope matches the job's city, remote or abroad |
| Posting older than the max age | Skipped before any AI call |
| Submit may have failed | Checks for Prosple's confirmation; if none, marks "failed" for you to check, never resubmits automatically |
| Contact email unverified | Not emailed; the job keeps its application only |
| Email bounces | Marked bounced; the contact is never retried |
| Gmail spam risk | Daily cap starting around 10, spaced emails, plain text, no tracking links |
| PC sleeps or shuts down | Run stops; it resumes safely from the database next time |
| Kill switch pressed mid-form | Stops before the next action; the job returns to the queue |
| Company on the blocklist | Never applied to or emailed |

**Risks to keep in mind**

- Prosple's terms may restrict automation. Read them before building the scraper, and keep volume at a human pace.
- Google's free Gemini tier may use your prompts to improve its products. Rule 3 above limits what it sees.
- Wrong contacts happen. Every email shows where the contact came from so you can check it during review.
- Scope is the biggest risk. Finish each phase before starting the next (see Part 3).

---

# Part 2: UI screens

Screen-by-screen detail for the JobPilot dashboard, plus scenarios showing how Jenel uses it. The visual source of truth is `design/` (tokens, rules and HTML mockups); this part describes behaviour and content.

**Which version builds which screen**

| Screen | Version |
| --- | --- |
| v0 controls page: Fill this page, Unknown questions, Answer bank, Filled pages history | **v0** |
| Review batch, Applications tracker, Home | **v1** |
| Emails | **v2** |
| Settings, Profile, Activity log, onboarding, empty and error states | **v3** |

The screens below describe the finished product. In v0 you build only the controls page, reusing the shared components and design tokens. Unknown questions in v0 is a simpler version of Screen 4, and the Answer bank is the "Answered" tab of that screen.

## The v0 controls page

A single small page at `localhost:3000` that you keep open next to the bot's browser window. It uses the existing Next.js dashboard, the design system in `design/`, and the engine API on `127.0.0.1`. It is the remote control for the form filler: it starts a fill and shows what happened. It has four sections (tabs or stacked cards).

**1. Fill this page (the main control)**

- A big **Fill this page** button, a **mode badge** (MOCK / DRY RUN / LIVE) and a status line: "Browser ready · current page: acme.com/careers/apply".
- You log in to sites and open the application page yourself in the bot's browser. When you press the button, the engine reads the page and fills it. The status line then shows progress: "Reading form… 14 fields found → answering → uploading resume A → done".
- A **Job post** line shows which page the resume picker read: "Job post: Junior Java Developer – Acme (tab 2)" with a **Change** button. If none was found, it says "Job post not found" and offers a list of open tabs to pick from, or a box to paste the text; the resume is not uploaded until one is chosen.
- When it finishes, you see a result summary: "12 filled · 2 flagged (guessed) · 1 new question · resume A". Flagged answers are also highlighted in the page itself in the bot's browser, so you can fix them there.
- It never clicks Submit. The page says "Review the form in the browser, then submit it yourself."

**1b. On-page Fill button (in the bot's browser, Phase 4)**

The same Fill control also appears on the job page itself, so you don't have to switch to the dashboard. The engine adds a small floating panel to every page the bot's Chrome window opens (Playwright `add_init_script`), inside a shadow DOM so the site's styles can't break it and it can't break the site:

```
┌───────────────────────────────┐
│ JobPilot  [Fill this page]    │
│ Job post: Java Dev – Acme  ✎  │
│ 12 filled · 2 flagged · res A │
└───────────────────────────────┘
```

- Clicking **Fill this page** calls the Python engine through Playwright `expose_binding`, which runs the same steps as the dashboard button: reader → job post finder → answer engine → resume picker → filler. No HTTP call is made from the page, so websites can never trigger a fill.
- It shows the job post used (✎ = Change), progress, and the result summary. It can be collapsed to a small tab and dragged aside.
- It never clicks Submit, and it is never placed over the site's Submit button.
- It exists only in the bot's browser profile, never in your everyday Chrome. The dashboard keeps Unknown questions, Answer bank and Filled pages history.
- It uses the design tokens (colours, fonts) from `design/tokens.css`; its look is mocked up before it's built.

**2. Unknown questions**

- A list of questions the engine could not answer, each with the page it came from. You type the answer once, pick a location scope (any / city / remote / abroad) and save. Next time that question, even worded differently, is answered from the bank.
- Legal and eligibility questions show "You must answer this yourself" and never get an AI suggestion.

**2b. Suggested wordings (the engine already exists: `engine/learning.py`; this is its screen)**

The engine learns new ways a form asks a saved question, but **only you approve them**. A wrong match saved automatically would become a permanent 1.0 match, so the screen is the safety step. It is a tab or card next to Unknown questions (in the finished product, a third tab on Screen 4: Waiting | Wordings | Answered). Data from `suggested_wordings`; actions are the same as the CLI `questions approve / reject`.

*What each row shows*

- **New wording**, exactly as the form asked it, in bold: "How much pay do you want?"
- **Matches saved question:** "What is your expected monthly salary?" with the saved answer shown (except protected ones, which show only the kind).
- **Match score** (0.91) and **seen N times**, plus the page it came from (link).
- A **kind chip**: fixed / open / protected. Protected rows get an amber **FlagMarker**: "Matches a protected answer. Check the two questions mean the same thing."
- Buttons: **Approve** (primary) and **Reject** (secondary). Sort by most seen first.

*Rules the screen must follow*

- Approving a **protected** row opens a **ConfirmDialog** ("This answer is protected. Do you confirm both questions mean exactly the same?"). Only its confirm button sends `confirm_protected = true`.
- After Approve: a **Toast** "Added to answers.json (backup made)", then the engine runs load and re-index by itself, with a status line "Re-indexing…" (CLI today: you run `load` and `rag reindex` by hand).
- Reject is final: that wording never comes back. Show an "Undo" only if the engine adds one later; do not invent it.
- Errors from the engine (saved question no longer in the file, file unreadable) show in a **Banner** with the engine's message, not a raw error.
- Empty state (**EmptyState**): "No new wordings waiting. When a form words a question in a new way, it appears here."

*Unknown questions additions (section 2)*

- Show **seen N times** and **on N pages** (with links) on each card, most-seen first. This count comes from `unknown_questions.times_seen`.
- Saving an answer adds it to the answer bank and re-indexes, so the same question, worded differently, matches next time.

*Engine API still to write (Phase 4 `engine/api.py`)*

`GET /wordings` (pending), `POST /wordings/{id}/approve` (body: `confirm_protected`), `POST /wordings/{id}/reject`, `GET /unknown`, `POST /unknown/{id}/answer` (answer, kind, scope, city; writes `answers.json` with a backup, then re-indexes). The functions to call already exist in `engine/learning.py`, except `answer` for unknown questions, which is new work.

*Design work still to do:* `design/screens/Questions.html` has no Wordings tab yet. Make that mockup first and compare the built screen with it, as CLAUDE.md requires. Reuse the shared components only: DataTable, StatusChip, FlagMarker, Button, ConfirmDialog, Toast, Banner, EmptyState, Drawer. Anything the design system does not define (for example a "score" bar) must be asked about, not invented.

**3. Answer bank editor**

- A searchable table: question, answer, location scope, times used. Add, edit and delete rows. Changes trigger a quick re-index so RAG can find them.

**4. Filled pages history**

- A table of every "Fill this page": date, job and company, URL, resume used, flagged count, status chip, and a screenshot. Clicking a row opens a drawer with the screenshot and the filled values.
- Statuses: `filled` (default) → `submitted` or `abandoned`. A **Mark as submitted** button and an **Abandoned** button sit on each row. In Phase 4, passive detection watches the page after you submit (read-only, no clicks) and offers "Looks submitted. Mark it?".

**What it does not show in v0:** job lists, scores, batches, emails, a kill switch or settings. Those arrive in v1–v3.

## How v0 works day to day

This is the whole v0 product from your side: what you open, what you press, and what happens behind it. The scenarios after it walk through real cases.

**Two windows side by side**

| Window | What it is | What you do there |
| --- | --- | --- |
| **Bot's Chrome** | Your installed Chrome, started with JobPilot's own profile (`data/browser_profile/`), never your everyday Chrome profile | Browse jobs, sign in to sites, open forms, press **Fill this page** on the floating panel, review, click Submit yourself |
| **Dashboard** (`localhost:3000`) | The v0 controls page | Fill this page (same as the panel), Unknown questions, Suggested wordings, Answer bank editor, Filled pages history |

**What happens when you press Fill this page**

```
You open a job form in the bot's Chrome
        │
        ▼
Press [Fill this page] (floating panel or dashboard)
        │
        ├─ 1. Reader: every field's label, type and options (all frames)
        ├─ 2. Job post finder: this page → opener tab → same-site tab → asks you
        ├─ 3. Answer engine, per field:
        │      personal (name, phone, email)  → code, never sent to AI
        │      protected (visa, legal, GPA)   → saved answer exactly; none saved → empty, flagged, unknown list
        │      fixed (salary, start date)     → saved answer found with RAG, scope matches the job
        │      open ("Why us?")               → Ollama drafts from your facts + the job post, flagged
        │      never seen (score < cutoff)    → unknown questions list, flagged
        ├─ 4. Resume picker: job post vs. what resume A and B actually say → uploads one as `upload_name`
        └─ 5. Filler: fills, highlights guesses, screenshot, saves a `fills` row, STOPS
        │
        ▼
You review the page, fix highlighted fields, click Submit yourself
        │
        ▼
Passive detection sees the confirmation → "Looks submitted. Mark it?" → you confirm → `submitted`
```

**Starting a session (about 2 minutes)**

1. Ollama runs in the background (it starts with Windows).
2. `python -m engine.api` starts the engine on `127.0.0.1` and opens (or attaches to) the bot's Chrome. The exact start-up is settled in Phase 4.
3. `cd dashboard; npm run dev`, then open `localhost:3000`. The mode badge shows MOCK / DRY RUN / LIVE.
4. The first fill is slow (Ollama loads in about 20–50 s); a warm-up call at start-up is planned for Phase 4.
5. You are already signed in to your job sites and Google from earlier sessions; the profile remembers.

**What v0 never does:** click Submit, Next or Apply; find jobs for you (v1); run in your everyday Chrome (an extension is under "Later"); solve CAPTCHAs, logins or 2FA; invent facts. Custom widgets it can't read are left empty and flagged "needs you".

## v0 scenarios

Eight scenarios show a normal day with v0, written as "you". All names and numbers are sample data. (The "User scenarios" section further down describes v1–v3.)

**0. Starting up.** You run the engine and the dashboard as above. The bot's Chrome opens, still signed in to your job sites and Google. The badge says DRY RUN for the first week of tests, LIVE after that (v0 never submits in either mode; you do).

**1. Description and form on the same page (Workable, Greenhouse).** You open "Junior Java Developer – Acme" and click Apply; the form appears under the description. You press **Fill this page** on the floating panel. It shows "Reading form… 14 fields → answering → uploading resume A → done", then "Job post: Junior Java Developer – Acme (this page) ✎ · 12 filled · 2 flagged · 1 new question · resume A". The 2 flagged fields are outlined in the page; one is a drafted "Why Acme?" answer. You edit a sentence, scroll through everything and click Submit yourself. The page says "Application received"; JobPilot offers "Looks submitted. Mark it?" and you confirm.

**2. Job post in another tab.** On a job board, "Apply on company website" opens the form in a new tab without the description. You press Fill. The finder finds nothing on the form page, so it reads the tab that opened it and shows "Job post: Backend Intern – Globex (tab 1)". The picker chooses resume B because the post asks for Node and PostgreSQL, which resume B shows. If the finder had picked the wrong tab, you'd press ✎ Change before anything is uploaded. **Variant:** you opened the form from a bookmark, so there's no job post tab. The panel says "Job post not found", lists open tabs and offers a paste box. The rest of the form fills; the resume waits until you choose.

**3. A question it has never seen.** "How many hours per week can you commit during the semester?" matches nothing above the cutoff, so the field is flagged and the question lands in Unknown questions with a link to the page. You answer "20 hours per week", scope "any", once. The engine re-indexes; you press Fill again and it fills. A month later "Weekly availability during school?" matches it by meaning.

**4. A legal question with no saved answer.** "Have you ever been employed by a government agency?" is a "have you ever" question, so it's protected: the AI never answers it. With no saved answer, the field stays empty and flagged and the dashboard says "You must answer this yourself." You answer it in the page, and in the dashboard so it's saved for next time.

**5. The same question in new words.** A form asks "When could you begin?"; the bank has "When can you start?". The match is strong, so the saved answer fills. The new wording appears on the Wordings tab ("When could you begin?" → "When can you start?", 0.91). Once a week you approve or reject these; protected ones need a second confirmation.

**6. Multi-step form (Workday style) with a Google sign-in.** The site offers "Sign in with Google". You click it, pick your account in the popup and you're in; the bot never touches the sign-in. Step 1: Fill, review, you click Next yourself. Steps 2 and 3: the same. Then you click Submit. Each step is one fill; the bot never clicks Next or Submit.

**7. Changing your mind.** You fill a form, then notice it wants 2 years of experience. You close the tab and press **Abandoned** on that row in Filled pages history.

**8. End-of-week check (5 minutes).** In the dashboard: history (every filled page with screenshot, resume, flagged count, status), the leftover unknown questions (most-seen first), the Wordings tab, and `notes/v0-misses.md` for anything it got wrong, which becomes the fix list after the week of real use.


## Design notes

JobPilot is a desktop web app at `localhost:3000`, used on a laptop or monitor. It doesn't need a mobile layout. It should feel like a calm work tool, like Linear or Notion: dense with information but not crowded.

**Layout (every screen)**

- Left sidebar, about 220 px wide, collapsible to icons.
- Top bar, about 56 px tall, fixed.
- Main content area, full width, with a page title row (title on the left, primary actions on the right).
- Screens with lists use a **list + detail** split: list on the left (about 40%), detail panel on the right (about 60%).
- Light and dark theme.

**Shared components** (build once and reuse)

| Component | Looks like | Used on |
| --- | --- | --- |
| Status chip | Small rounded pill, coloured by status | Tracker, Review batch, Emails |
| Score badge | Number 0–100 in a ring: green 80+, amber 60–79, grey under 60 | Review batch, Tracker, Home |
| Mode badge | Pill in the top bar: grey **MOCK**, blue **DRY RUN**, red **LIVE** | Top bar |
| Flag marker | Amber triangle icon with a count, e.g. ▲ 2 | Review batch, Tracker |
| Data table | Sticky header, sortable columns, row hover, row click opens a drawer | Tracker, Activity log, Answer bank |
| Detail drawer | Slides in from the right, about 520 px, with a close X | Tracker, Activity log |
| Confirm dialog | Centred modal, with a red button for risky actions | Kill switch, Live mode, Submit approved |
| Toast | Small message bottom-right, gone after 4 s | After save, approve, submit |
| Empty state | Icon + one sentence + one button | Every list |

**Status colours** (the same everywhere; exact values in `design/tokens.css`)

| Status | Colour | Meaning |
| --- | --- | --- |
| New | Grey | Found, not scored yet |
| Queued | Blue | Waiting for your review |
| Approved | Indigo | You approved it; waiting to submit |
| Submitted | Green | Sent to the employer |
| Manual | Purple | You need to apply yourself |
| Failed | Red | Something went wrong; check it |
| Rejected | Dark grey | You or the employer said no |
| Interview / Offer | Teal / Gold | Set by you |

## Top bar and side navigation

The top bar answers three questions at a glance: what mode am I in, is it running, and does it need me?

**Top bar, left to right**

1. **JobPilot logo** (click = Home).
2. **Mode badge:** MOCK / DRY RUN / LIVE. Click opens Settings → Run mode.
3. **Engine status** with a dot: ● Running (green, pulsing), ● Paused (amber), ● Waiting for you (amber, e.g. "CAPTCHA on Prosple"), ● Stopped (grey), ● Idle until 2:00 PM (grey).
4. **Today counters:** `Applied 7 / 15` and `Emails 4 / 10`, each with a thin progress bar under it.
5. **Quota meter:** a small gauge icon; hover shows calls and lookups left today per provider (e.g. "Gemini 38 left · Ollama local · Hunter 12 left this month").
6. **Alerts bell** with a red count. Click opens a dropdown of alerts, each with a button: "Batch ready (9) → Review", "3 new questions → Answer", "Prosple CAPTCHA → Open browser".
7. **Pause / Resume** button.
8. **STOP** button: red, always visible. Click opens a confirm dialog ("Stop all browser actions and emails now?"). After stopping, the whole top bar turns red-tinted until you press Resume.

**Side navigation**

- Home
- Review batch, with a blue count badge (e.g. 9)
- Applications
- Questions, with an amber count badge (e.g. 3)
- Emails
- Profile
- Settings
- Activity log

At the bottom of the sidebar: the date, active hours ("Runs 9 AM–11 PM"), and the app version.

## Screen 1: Home

Home is the morning check: what happened, what needs me, and how is the search going overall.

**Row 1: Needs you** (full width, only shown when something is waiting)

- A highlighted card per item, each with one button: "9 applications ready for review → Review", "3 questions need answers → Answer", "Prosple is paused: CAPTCHA → Open browser", "Gemini quota used up, switched to Ollama".

**Row 2: Stat cards** (4 across)

| Card | Big number | Small text under it |
| --- | --- | --- |
| Found today | 42 | 18 matched (score 60+) |
| Waiting for review | 9 | oldest 1 day ago |
| Submitted this week | 31 | +8 vs last week |
| Emails sent this week | 22 | 2 bounced |

**Row 3: Two charts side by side**

- **Applications per day** (left, 60% width): bar chart for the last 30 days, bars split into submitted and manual.
- **Funnel** (right, 40% width): Found → Matched → Submitted → Replied → Interview, horizontal bars with counts and the % between stages.

**Row 4: Two lists side by side**

- **Top matches today:** 5 rows with score badge, role, company, status chip. Click opens it in Review batch.
- **Recent activity:** the last 8 actions from the Activity log ("2:14 PM · Submitted · Junior Dev @ Acme"), with a "See all" link.

**Page actions** (top right): Run once now, Pause.

## Screen 2: Review batch

This is where you spend your 10 minutes a day. It must make approving fast and catching mistakes easy. It uses the list + detail split.

**Page header**

- Title "Review batch" with a summary: "9 applications · 6 emails · 3 flagged".
- Tabs: **Applications (9)** | **Emails (6)**. Emails also appear inside each application; this tab is for emails to companies with no application.
- Filter chips: All, Flagged only, Score 80+, Internship, Full-time.
- Primary buttons, top right: **Approve all unflagged** (secondary) and **Submit approved (5)** (primary, disabled until at least one is approved).

**Left: the queue list**

Each row is a compact card, sorted by score (highest first):

- Checkbox for bulk select
- Score badge (e.g. 86)
- Role in bold, company and location under it ("Junior Full Stack Developer · Acme PH · Makati")
- Small tags: job type (Internship), resume used (Resume A · Web), posted (3 days ago)
- Flag marker if any answer was guessed (▲ 2)
- Status on the right: Queued / Approved ✓ / Rejected

Keyboard shortcuts shown in a hint bar at the bottom: `J/K` next/previous, `A` approve, `R` reject, `E` edit.

**Right: the detail panel** (scrolls; sections in this order)

1. **Header:** role, company, location, a link button "Open on Prosple ↗", and Approve / Reject buttons that stay visible while scrolling.
2. **Why it matched:** the score badge large, 2–3 one-line reasons ("Uses React + Spring Boot, both in your projects"), and a "Missing" line with grey skill chips (Docker, AWS).
3. **Resume:** a toggle with two options, `Resume A · <its label>` and `Resume B · <its label>`, the AI's choice pre-selected with "AI picked this because…". A Preview link opens the PDF.
4. **Filled answers:** a two-column list, question on the left and answer on the right, editable inline.
   - Answers from your profile: normal text with a small "from profile" tag.
   - Answers from the answer bank: "from answer bank" tag.
   - AI-guessed answers: amber background, ▲ icon, "AI guess — check this", and a "Save to answer bank" checkbox.
   - Private fields (phone, address): shown masked (•••• 1234) with a "filled locally" lock tag.
5. **Form screenshot:** a thumbnail of the filled Prosple form; click to enlarge.
6. **Cold email:**
   - Contact card: name, title, company, email with a ✓ Verified tag, and "Found via: Google search → LinkedIn profile title" with the source link.
   - Tier tag: Personal or Short.
   - Subject and body, editable.
   - "Don't send an email for this job" checkbox.
   - If no contact was found: a grey box "No verified contact found" and a field to paste an email manually.
7. **Job post:** the full description, collapsed by default ("Show full post").

**Reject flow:** clicking Reject opens a small menu: Not interested, Bad match, Wrong location, Already applied elsewhere, Block this company. The reason is saved, and "Block" adds the company to the blocklist.

**Submit flow:** clicking "Submit approved (5)" opens a confirm dialog listing the 5 jobs and the emails that will go out. After confirming, each row shows a spinner, then ✓ Submitted or ✕ Failed with a reason.

## Screen 3: Applications tracker

The tracker is the full history of every job JobPilot touched. It is a big table with a detail drawer.

**Page header**

- Title "Applications" with the count ("124 total").
- Tabs: **All** | **Submitted** | **Needs manual apply (8)** | **Failed (2)** | **Interviews**.
- Search box: company or role.
- Filters: status, job type, location, score range, date range, resume used.
- Buttons: Export CSV, Column picker.

**Table columns** (default order)

| Column | Shows |
| --- | --- |
| Date | Date applied or found ("Nov 12") |
| Company | Name, with a small logo if available |
| Role | Job title; click opens the drawer |
| Location | City or Remote |
| Type | Internship / Part-time / Freelance / Full-time |
| Score | Score badge |
| Resume | A or B |
| Status | Status chip; click to change (Interview, Offer, Rejected, Ghosted) |
| Contact | Name + title, or "—" |
| Email | Sent ✓ / Queued / Bounced / None |
| Links | Icons: job post ↗, screenshot icon |

**Needs manual apply tab:** the same table plus a big **Open & apply** button per row, which opens the employer's site in your browser, and a **Mark as applied** button you click after applying yourself. Each row shows why it is manual ("External site", "Field not found", "CAPTCHA").

**Detail drawer** (opens on row click)

- Header: role, company, status chip (changeable), score badge, links.
- **Timeline:** vertical list of events with times, e.g. Found → Scored 86 → Queued → Approved by you → Submitted → Email sent to Maria Santos → (you set) Interview.
- **Answers sent:** read-only question/answer list.
- **Email:** the sent email, with contact details.
- **Notes:** a free text box for your own notes ("HR called, interview Nov 20").
- **Screenshot:** of the submitted form.

## Screen 4: Unanswered questions

This screen grows your answer bank so JobPilot needs you less over time. Every question you answer here is reused on future forms.

**Page header**

- Title "Questions" with "3 waiting · blocking 5 jobs".
- Tabs: **Waiting (3)** | **Answered (41)**.

**Waiting list: one card per question**, grouped under headings: Salary and pay, Location and relocation, Availability and schedule, Legal and eligibility, Experience, Open-ended ("Why do you want to work here?").

Each card shows:

- The question text in bold: "What is your expected monthly salary?"
- Where it came from: "Asked by 3 jobs: Acme PH (Makati), Appify (Taguig), +1", with links.
- AI suggestion, if any, in a grey box with "Use this" (for example "PHP 20,000–25,000 for Metro Manila internships"). Legal/eligibility questions never get a suggestion; they show "You must answer this yourself".
- Answer field: a text box, or Yes/No buttons, or a dropdown when the form had fixed options.
- **Location scope** picker: Any location, A specific city (city picker), Remote, Abroad. A "+ Add another location answer" link lets you give a different answer per scope, e.g. a salary for Makati and another for remote foreign jobs.
- Save button. After saving, the card collapses with ✓ and "5 jobs can continue".

**Answered tab:** a searchable table of the answer bank: question, answer, location scope, times used, last used, with Edit and Delete. This is the same data shown in Profile → Answer bank.

## Screen 5: Emails

The Emails screen is the outbox and sent log for cold emails. It uses the list + detail split, like an email client.

**Page header**

- Title "Emails" with "Today 4 / 10 sent".
- Tabs: **Queued (6)** | **Sent (58)** | **Failed / Bounced (3)**.
- Auto-send switch, top right: "Auto-send: Off · Review period ends Nov 18 (6 days left)". Before the review period ends, turning it on shows a warning dialog.

**Left: email list.** Each row shows:

- Recipient name and title ("Maria Santos · Talent Acquisition Lead")
- Company and related job ("Acme PH · Junior Full Stack Developer")
- Subject, truncated
- Tier tag (Personal / Short), status chip, time ("Queued" or "Sent 2:31 PM")

**Right: email preview**

- From (your Gmail), To (with ✓ Verified), Subject, Body, laid out like a real email.
- While queued: subject and body editable, plus buttons **Approve**, **Regenerate** (asks the AI for a new draft, with an optional instruction such as "make it shorter"), and **Delete**.
- Below the email: "Why this contact" (source link) and "Facts used" (which of your projects and skills the AI mentioned, so you can check nothing was invented).
- When sent: a ✓ Sent time and a "View in Gmail ↗" link.
- When bounced: the bounce reason and "Contact marked invalid".

> In v0 (before sending exists), this screen is "lite": drafts only, with a **Copy** button instead of Approve/send.

## Screen 6: Profile and documents

This screen holds everything the AI knows about you. It uses tabs inside the page.

**Tab: Personal**

- Form fields in two columns: full name, preferred name, email, phone, birthday, address, city, nationality, LinkedIn URL, GitHub URL, portfolio URL.
- Sensitive fields (phone, address, birthday) show masked with an eye icon to reveal, and a lock tag: "Encrypted · never sent to AI".

**Tab: Education**

- School (Polytechnic University of the Philippines), course, year level, expected graduation (month + year), GPA (optional), relevant coursework (chips), OJT hours required (if any).

**Tab: Job preferences**

- Target roles (chips: Junior Developer, Full Stack, Mobile Developer…), job types (checkboxes), preferred locations (chips), remote OK (toggle), expected salary per scope, available start date, hours per week available.

**Tab: Resumes**

- Two cards side by side: **Resume A** and **Resume B**.
- Each card: label (e.g. "Web / Full stack"), file name, upload date, a PDF thumbnail, Replace and Preview buttons, and "Best for" keywords you can edit (the resume picker uses these as a hint).
- Under the cards: "Picked so far: A 64 times, B 37 times".

**Tab: Projects and skills**

- Skills as chips you can add or remove.
- Projects list: name, one-line description, tech chips, link. These are the facts the cold emails can mention.

**Tab: Answer bank**

- Same table as Questions → Answered.

**Bottom bar on every tab:** Save changes, plus **Re-index for AI** with a note "Last indexed 2 days ago · 3 changes since". Re-indexing rebuilds the RAG chunks.

## Screen 7: Settings

Settings controls how aggressive, how private, and how automatic JobPilot is. It has a section list on the left and the section's form on the right.

**Run mode**

- Three large radio cards: **Mock** ("Offline, fake AI, nothing sent"), **Dry run** ("Real sites and AI, nothing submitted or sent"), **Live** ("Submits after your approval").
- Choosing Live opens a confirm dialog where you type LIVE to confirm.

**AI provider**

- A table with one row per task: Match + resume pick, Form answers, Embeddings, Cold emails.
- Each row has a dropdown (Gemini / Ollama), the model name (e.g. `gemini-flash`, `qwen3:4b`), and a "Test" button that runs a sample prompt and shows the time taken.
- Toggle: "If Gemini quota runs out, fall back to Ollama".
- Ollama status line: ● Connected · 2 models installed, or ● Not running, with a help link.

**Search filters**

- Keywords (chips), job types (checkboxes), allowed locations (chips), remote OK (toggle), maximum posting age (slider, 1–60 days, default 30).

**Thresholds and caps**

- Minimum score to queue (slider, default 60).
- Score for a personal email (slider, default 80).
- Daily caps (number inputs): applications, emails, AI calls, contact lookups.
- A live preview line: "With these settings, about 12 applications a day".

**Schedule**

- Active days (Mon–Sun toggles) and active hours (time range).
- "Pause during my class hours" with time blocks you add.

**Blocklist**

- Three lists with add and remove: Companies, Email domains, People (email addresses).

**Connections**

- One row per service with a status dot and a button: Gemini API key (Set / Replace), Search API key, Hunter API key, Gmail (Connect with Google / Disconnect, showing "Send-only permission"), Prosple (Open bot browser to log in · Last check: logged in ✓).
- Keys are never displayed after saving, only "•••• set on Nov 4".

**Notifications**

- Checkboxes for which events give a Windows pop-up: batch ready, CAPTCHA/login needed, quota out, submit failed, daily summary.

## Screen 8: Activity log

The Activity log shows exactly what the bot did and when, so you can trust it and debug it. It is a dense, time-ordered table.

**Page header**

- Filters: type (Navigate, Fill, Submit, Email, Error, CAPTCHA, AI call), site, date range, "Errors only" toggle.
- Search: company, job, or text.
- Live toggle: "Follow new events" (auto-scroll as they happen).

**Table columns:** time (with seconds), type icon + label, site, target ("Junior Dev @ Acme PH → field 'Expected salary'"), result (✓ / ✕ / ⏸), and a screenshot thumbnail when there is one.

**Row click** opens a drawer with full details: the action, the page URL, the error message and stack (for errors), the AI prompt and response (for AI calls, with private fields shown as [hidden]), and a large screenshot. A **Retry** button appears only for safe retries such as a failed page load, never for a submit.

**Grouping:** a toggle groups the log by run ("Run at 2:00 PM · 42 actions · 1 error"), which can be collapsed.

## Onboarding, empty states and error states

**First launch onboarding** is a full-screen stepper with a progress bar (Step 2 of 6) and Back / Next buttons:

1. **Welcome:** what JobPilot does, in 3 lines, plus "Nothing is ever submitted without your approval".
2. **Your details:** personal and education fields (the same form as Profile).
3. **Resumes:** two upload boxes (drag and drop) and a label for each.
4. **Preferences:** roles, job types, locations, salary.
5. **Connections:** AI provider (Gemini key and/or Ollama check), Gmail connect, Prosple login in the bot browser. Each one can be skipped with "Set up later".
6. **First dry run:** a button "Find my first matches (dry run)". It shows a live progress list (Searching Prosple… Found 34 jobs… Scoring…) and ends on Review batch.

**Empty states** (icon + one sentence + one button)

| Where | Message | Button |
| --- | --- | --- |
| Review batch | "Nothing to review. JobPilot will notify you when new matches are ready." | Run once now |
| Applications | "No applications yet." | Find jobs |
| Questions | "All caught up. No questions waiting." | View answer bank |
| Emails, Queued | "No emails waiting for review." | — |
| Home, no matches today | "No new matches today. Try widening your filters." | Open filters |

**Error and blocked states**

| Situation | How it shows |
| --- | --- |
| Kill switch pressed | Red banner across every screen: "Stopped by you at 3:12 PM. Nothing will run." Button: Resume |
| CAPTCHA or Prosple logout | Amber banner: "Prosple needs you: solve the CAPTCHA in the bot browser." Buttons: Open browser, I'm done |
| AI quota used up | Amber banner: "Gemini quota used up. Switched to Ollama" or "Paused until tomorrow 8:00 AM" |
| Engine not running | Grey full-page message: "Can't reach the JobPilot engine. Start it with `python -m engine.api`." Button: Retry |
| Gmail disconnected | Banner on Emails: "Gmail disconnected. Emails are paused." Button: Reconnect |
| Submit failed | Row turns red with the reason; toast "1 submit failed, check Applications → Failed" |

## User scenarios

Ten scenarios show how Jenel, a PUP student looking for internships and junior roles, uses JobPilot. All names and numbers are sample data.

**1. First setup on a Sunday evening** (Onboarding → Review batch)

Jenel opens JobPilot for the first time. The stepper asks for his details, school and expected graduation. He drags in Resume A and Resume B, each with a label and the kind of role it targets. He picks Internship, Part-time and Full-time, with Metro Manila and Remote as locations. He connects Gmail, which says "Send-only permission", and chooses Ollama for matching and Gemini for emails. He logs into Prosple in the bot browser. He clicks "Find my first matches (dry run)", watches the progress list, and lands on Review batch with 14 matches and nothing submitted.

**2. Morning review before class, 10 minutes** (Windows pop-up → Review batch → Submit)

At 7:40 AM a pop-up says "9 applications ready". Jenel opens Review batch. He clicks "Flagged only": 3 jobs. In the first one the AI guessed "Available start date: January 2027". He edits it to "December 2026" and ticks "Save to answer bank". He rejects a data analyst job ("Bad match"). He clicks "Approve all unflagged", then "Submit approved (8)". The confirm dialog lists 8 jobs and 6 emails. He confirms and leaves for class. By lunch the tracker shows 8 green Submitted chips.

**3. A salary question that depends on location** (Questions)

The alerts bell shows "2 new questions". One is "Expected monthly salary?", asked by a Makati internship and a remote US startup. The AI suggests a peso range. Jenel answers PHP 18,000 with scope "Metro Manila", then clicks "+ Add another location answer" and enters USD 600 for scope "Remote, abroad". The card collapses: "2 jobs can continue". Next time either kind of job asks, the right answer is filled automatically.

**4. CAPTCHA while doing homework** (Banner → bot browser)

While Jenel writes an essay, a pop-up says "Prosple needs you". The top bar shows ● Waiting for you. He clicks "Open browser", solves the CAPTCHA, and clicks "I'm done". The engine resumes, and the Activity log shows a ⏸ CAPTCHA row followed by normal rows.

**5. Checking a cold email before it goes out** (Emails → Queued)

It is still the 2-week review period. Jenel opens Emails → Queued. One email to "Maria Santos · Talent Acquisition Lead" mentions his Pag-IBIG project. "Facts used" confirms that this comes from his Projects list. Another email sounds too formal, so he clicks Regenerate with "make it shorter and friendlier". He approves 5 and deletes 1, because the contact was found via a 2021 article and looks outdated.

**6. A recruiter replies** (Gmail → Applications drawer)

Appify's HR replies in Gmail asking for an interview. Jenel opens Applications, searches "Appify", opens the drawer, changes the status to Interview, and writes in Notes: "Interview Nov 20, 10 AM, Google Meet". On Home, the funnel's Interview bar goes from 1 to 2.

**7. Quota runs out in the afternoon** (Top bar → Settings)

At 3 PM an amber banner says "Gemini quota used up. Switched to Ollama". Matching continues locally. Emails pause because they're set to Gemini only. Jenel decides that's fine and lets them wait until tomorrow. On the quota meter he sees the reset time.

**8. Something looks wrong: stop everything** (Kill switch → Activity log)

Jenel notices the bot browser filling a form with the wrong resume. He clicks STOP and confirms. The whole app shows the red "Stopped by you" banner. In the Activity log he filters by that job and sees the AI picked Resume B because the post mentioned "mobile-friendly". He opens Profile → Resumes, adds "responsive web" to Resume A's "Best for" keywords, then presses Resume.

**9. Matches are poor: tuning filters** (Home → Settings)

On Saturday Home shows "Found 60, matched 4". Jenel opens Settings, lowers the minimum score from 60 to 55, adds keywords "React intern" and "Flutter intern", and sets maximum posting age to 21 days. The preview line now says "about 11 applications a day".

**10. Sunday manual applications** (Applications → Needs manual apply)

The tab shows 8 jobs that redirect to company sites. For each one Jenel clicks "Open & apply", applies on the employer's site using the answers in the drawer, and clicks "Mark as applied". The cold emails for those jobs, queued earlier, are now released for review.

---

# Part 3: Roadmap

Build JobPilot in small versions, each one finished and usable on its own: v0 (the form filler) in 5 phases, then v1 (batch mode), v2 (cold email) and v3 (hands-off). Each v0 phase lists what to learn, what to prompt Claude Code, what to run, and how to know it's done.

## At a glance

| Version / phase | What | Time |
| --- | --- | --- |
| **v0** Phase 0 | Setup and foundations | 3–4 days |
| v0 Phase 1 | Profile, resumes and answer bank | 1 week |
| v0 Phase 2 | Form reader | 1–1.5 weeks |
| v0 Phase 3 | RAG + answer engine + resume picker | 1.5 weeks |
| v0 Phase 4 | Fill, upload, review, controls page, a week of real use → **tag v0.1** | 1.5 weeks |
| **v1** | Batch mode | 3–4 weeks |
| **v2** | Cold email | 1–2 weeks |
| **v3** | Hands-off → **JobPilot 1.0** | 1–2 weeks |

v0 takes about 5–6 weeks at 10–15 hours a week and is a complete, resume-ready project on its own. Each later version adds one capability, and you can stop after any of them.

**v0 is done when** it correctly fills Prosple's own form, one Google Form and one company career page, and you've used it for a week of real applications.

## How to use this roadmap

Do one phase at a time, and split each phase into 2–4 Claude Code sessions. Tick the boxes as you go. Every session follows the same routine:

1. **Read first (15–30 min).** Skim the docs listed in the phase's "Learn" box, just enough to know the words.
2. **Open Claude Code in the repo** and start with the session prompt below. Paste in the phase's prompt.
3. **Ask for a plan, approve it, then build in small steps.** Don't accept code you can't explain; ask "explain this line by line".
4. **Run the checks** listed for the phase. If something fails, paste the error and ask for the cause before the fix.
5. **Commit** with a clear message. Update "Current stage" in `CLAUDE.md` when the phase is done.
6. **Explain it out loud** in 2 minutes before moving on. If you can't, you're not done.

**Session start prompt** (use every time):

```text
Read CLAUDE.md and the spec section for the current stage. Summarize in 5 bullets
what we're building in this phase and what is already done. Then propose a plan
for THIS session only (max 3 steps). Wait for my OK before writing code.
```

**When you're stuck:**

```text
This error happened: <paste>. Before fixing anything, explain what it means and the
2 most likely causes. Then suggest the smallest fix.
```

**Session end prompt:**

```text
Summarize what we changed this session, what's left in this phase, and suggest a
commit message. List anything I should understand better before next session.
```

Tip for Pro usage limits: keep each session to one step of one phase, and point Claude at specific files instead of the whole repo.

## Phase 0: Setup and foundations (3–4 days)

Goal: an empty but well-organized repo where tests run and `ask_ai()` answers in mock mode and through Ollama.

**Learn**

- Git basics: commit, branch, `.gitignore` — [Pro Git, chapters 1–2](https://git-scm.com/book/en/v2)
- Python virtual environments — [venv docs](https://docs.python.org/3/library/venv.html)
- pytest basics — [Get started](https://docs.pytest.org/en/stable/getting-started.html)
- Ollama: install, pull a model, call it from Python — [ollama.com](https://ollama.com) and [ollama-python](https://github.com/ollama/ollama-python)
- Claude Code basics — [Claude Code overview](https://docs.claude.com/en/docs/claude-code/overview)

**Checklist**

- [ ] Install Python 3.13, Node.js LTS, Git, VS Code, Ollama
- [ ] Pull a model your PC can run (e.g. `ollama pull qwen3:4b`; `llama3.1:8b` only with ~8 GB VRAM) and test it with `ollama run`
- [ ] Create a private GitHub repo `jobpilot`
- [ ] Copy in `CLAUDE.md`, `docs/` and the `design/` folder
- [ ] Create the folder layout from `CLAUDE.md`
- [ ] `.gitignore` covers `data/`, `*.db`, `.venv/`, `*.env*`, `node_modules/`
- [ ] `engine/ai.py` with `ask_ai(task, prompt)` supporting `mock` and `ollama` providers
- [ ] `fixtures/ai/` with one canned response per task
- [ ] `settings.json` with `run_mode` and `ai_provider`
- [ ] First passing test, first commit

**Prompts for Claude Code**

```text
We're in Phase 0. Set up the Python project structure exactly as in CLAUDE.md's
folder layout, with a .gitignore and a requirements.txt. Explain what each folder
is for. Don't write feature code yet.
```

```text
Create engine/ai.py with ask_ai(task: str, prompt: str) -> dict. It reads the
provider from settings.json: "mock" returns JSON from fixtures/ai/<task>.json,
"ollama" calls my local Ollama model and parses JSON. Validate output with a
Pydantic model per task. Explain how the provider switch works, then write tests
for mock mode only.
```

**Run and check** (Windows PowerShell)

```powershell
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q
python -c "from engine.ai import ask_ai; print(ask_ai('match', 'test'))"
```

**Done when:** tests pass, mock and Ollama both return JSON, and `git log` shows your first commits with no secrets.

## Phase 1: Profile, resumes and answer bank (1 week)

Goal: your details, both resumes and your answer bank live in a local SQLite database, loaded from files and readable by code.

**Learn**

- SQL basics: CREATE, INSERT, SELECT, UPDATE — [SQLBolt lessons 1–12](https://sqlbolt.com/)
- Python `sqlite3` — [docs](https://docs.python.org/3/library/sqlite3.html)
- Pydantic models — [Pydantic docs](https://docs.pydantic.dev/latest/)
- Extracting text from PDFs — [pdfplumber](https://github.com/jsvine/pdfplumber)
- Storing secrets — [keyring](https://pypi.org/project/keyring/)

**Checklist**

- [ ] `engine/db.py`: create tables `profile`, `resumes`, `answers`, `unknown_questions`, `fills` (filled pages history) and `action_log` (from the Data model in Part 1)
- [ ] `data/profile.json` (git-ignored) with your real details, education, links, job preferences and projects; a `profile.example.json` with fake ones is committed
- [ ] Your 2 resume PDFs in `data/resumes/` with a label each (set in `profile.json`)
- [ ] `engine/profile.py`: load the profile and resumes into the DB, extract resume text
- [ ] Answer bank: `answers` table with `location_scope` (any / city / remote / abroad); load a starter `data/answers.json`; lookup by exact question
- [ ] `engine/secrets.py`: get/set secrets through `keyring`
- [ ] CLI commands: `python -m engine.cli profile show` and `python -m engine.cli answers list`
- [ ] Tests with a fake profile, a small sample PDF and a fake answer bank

**Prompts for Claude Code**

```text
Phase 1. Explain the tables we need for profile, resumes, answer bank and filled
pages, and why answers need a location_scope. Show the schema and wait for my OK.
```

```text
Implement engine/db.py and engine/profile.py: create the tables, load
data/profile.json and the two resumes, extract resume text with pdfplumber. Add
the answer bank loader. Tests use a fake profile and a sample PDF only.
```

**Run and check** (Windows PowerShell)

```powershell
python -m engine.cli profile show
python -m engine.cli answers list
python -m pytest -q
```

**Done when:** your profile, both resumes and the answer bank load into SQLite, `profile show` prints them (no secrets in the output), and tests pass.

## Phase 2: Form reader (1–1.5 weeks)

Goal: Playwright opens a persistent bot browser, and for the page you opened it returns every field's label, type and options, tested offline against saved HTML.

**Learn**

- Playwright basics and persistent contexts — [Playwright Python intro](https://playwright.dev/python/docs/intro) and [Persistent context](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context)
- Locators: role, label, text — [Locators](https://playwright.dev/python/docs/locators)
- Auto-waiting — [Actionability](https://playwright.dev/python/docs/actionability)
- Recording selectors — [Codegen](https://playwright.dev/python/docs/codegen)

**Checklist**

- [ ] `engine/forms/reader.py`: connect to the bot browser and read the current page
- [ ] Persistent browser profile in `data/browser_profile/` (you log in to sites by hand; the bot never stores passwords)
- [ ] For each field: label, type (text, textarea, select, radio, checkbox, file, date), required, options
- [ ] Pydantic model `FormField`; output is a list of fields
- [ ] Handles labels via `<label>`, `aria-label`, placeholder and nearby text
- [ ] Save form HTML fixtures to `fixtures/forms/` (Prosple form, a Google Form, one career page)
- [ ] Tests run on the saved HTML only, never on live sites
- [ ] `safety.check()` before every navigate and read; each read logged to `action_log`
- [ ] CLI: `python -m engine.cli forms read` prints the fields of the current page

**Prompts for Claude Code**

```text
Phase 2. Explain how Playwright finds elements and why we prefer role/label/text
selectors. Then explain how a persistent browser profile keeps me logged in. Don't
code yet.
```

```text
Write engine/forms/reader.py: read every field's label, type, required flag and
options from the current page into FormField models. Save the HTML of 3 different
forms into fixtures/forms/ and test the reader on those files offline.
```

**Run and check**

```powershell
playwright install chromium
python -m engine.cli forms read
python -m pytest -q
```

**Done when:** the reader returns correct fields for the Prosple form, a Google Form and a company career page fixture, and tests pass offline.

## Phase 3: RAG + answer engine + resume picker (1.5 weeks)

Goal: for each field, the right source answers it: code, answer bank, or Ollama drafting from real facts. The right resume is picked from the job post.

**Learn**

- Embeddings and similarity search: what a vector is and why cosine similarity works. Any short intro article, then the [Ollama embeddings docs](https://github.com/ollama/ollama/blob/main/docs/api.md)
- Vector storage in SQLite — [sqlite-vec](https://github.com/asg017/sqlite-vec)
- Structured JSON output and validation — [Pydantic](https://docs.pydantic.dev/latest/)
- Prompting for structured output — [Prompt engineering](https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/overview)

**Checklist**

- [ ] `engine/rag.py`: chunk profile, resumes, projects and answer bank; embed with `nomic-embed-text` via Ollama; store in sqlite-vec
- [ ] `retrieve(question, k=5)` returns chunks with a similarity score
- [ ] Re-index command; answer bank edits re-index their rows
- [ ] `engine/forms/answers.py`: the rules per field, in this order:
  - `protected` (name, email, phone, work authorization, visa, "have you ever", convictions, consent to checks or terms, gender, ethnicity, disability) → the answer text is used exactly as saved and the AI never sees or changes it; highlighted for your review. Questions with sensitive words (visa, authorized, convicted, citizen, consent, relative, disability…) are treated as `protected` even if nothing saved matches, and then go to the unknown-questions list. A new answer defaults to `protected`
  - `fixed` → answer bank via RAG, used as written, using the scope that matches the job's location
  - `open` (about you, why this company, strengths, projects) and any new open question → Ollama rewrites the saved answer to fit this job, using only your saved answers, projects and resume facts; always flagged
- [x] **Elaboration:** when a `fixed` answer is a short yes/no to an experience or knowledge question and the field is a free-text box (e.g. "Do you have Docker experience? Please explain"), Ollama expands it into 1–2 sentences using only related facts from your answers, projects and resumes, and flags it. Yes/no radios and dropdowns get the plain answer. `protected` answers are never expanded
- [ ] `prompts/form.md`: field labels + allowed facts → `{field, answer, confidence, source}`; "use only the provided facts"
- [ ] Pydantic validation of Ollama JSON; retry once, then log and skip that field
- [ ] Resume picker: job post **text** (passed in; finding it in the browser is Phase 4) + the most similar chunks of each resume (RAG) → `{resume: "A"|"B", reason, evidence}`. It never decides from the file name or label. Tested on saved job post text files
- [ ] Canned responses in `fixtures/ai/` for mock mode; tests cover each rule
- [ ] A test that no prompt contains phone, address, email or ID numbers

**Prompts for Claude Code**

```text
Phase 3. Teach me RAG with a tiny example first: 5 sentences, embed them with
Ollama, ask a question, show the similarity scores. Then we'll apply it to my
profile and answer bank.
```

```text
Implement engine/rag.py with sqlite-vec and nomic-embed-text. Show me which chunks
are retrieved for 5 real form questions, worded differently from my saved ones, so
I can judge if retrieval works.
```

```text
Write the answer engine: decide per field whether code, the answer bank or Ollama
answers it, following the rules in the spec. Legal and eligibility questions must
never come from the AI. Test every rule in mock mode.
```

**Run and check**

```powershell
python -m engine.cli rag reindex
python -m engine.cli rag ask "What is your expected graduation date?"
python -m engine.cli forms answer --fixture fixtures/forms/prosple.html
python -m pytest -q
```

**Done when:** retrieval returns the right chunks for 5 differently worded questions, the answer engine gives the right source for every field of the 3 form fixtures, legal questions are never guessed, and the resume picker chooses sensibly on 3 sample job posts.

## Phase 4: Fill, upload and review (1.5 weeks, then a week of real use)

Goal: press **Fill this page** and the form gets filled, the resume uploaded and guesses highlighted, then it stops. You submit yourself and track what you filled.

**Learn**

- Playwright forms: fill, select, check, file upload — [Input actions](https://playwright.dev/python/docs/input)
- Screenshots — [Screenshots](https://playwright.dev/python/docs/screenshots)
- Page events and navigation (for passive detection) — [Events](https://playwright.dev/python/docs/events) and [Navigations](https://playwright.dev/python/docs/navigations)
- FastAPI — [Tutorial](https://fastapi.tiangolo.com/tutorial/)
- Next.js + Tailwind (the existing dashboard) — [Next.js docs](https://nextjs.org/docs), [Tailwind](https://tailwindcss.com/docs)

**Checklist**

- [ ] `engine/forms/filler.py`: fill text, select, radio, checkbox and date fields; upload the chosen resume under the formal `upload_name` (Playwright can set the uploaded file's name, so the original file is never renamed); random 1–4 s delays between actions
- [ ] **Job post finder** (see "Finding the job post" in Part 1): form page → opener tab → same-site tab → ask you (pick a tab or paste). Read-only; shows the job post used with a Change button; no job post = no resume upload, flagged. Mock-mode tests with saved pages
- [ ] **On-page Fill button** (Part 2, 1b): floating panel injected into the bot's browser (`add_init_script`, shadow DOM), wired to the engine with `expose_binding`; shows job post (Change), progress and result; never clicks or covers Submit. Mockup first; test on saved HTML in mock mode
- [ ] `safety.check()` before every fill; every fill logged to `action_log`
- [ ] Highlight guessed answers in the page (visible outline + small note); leave known answers plain
- [ ] **Never clicks Submit.** A test proves no Submit/Apply button is ever clicked
- [ ] Screenshot of the filled form; save a row in `fills`: URL, job and company, resume, flagged count, screenshot path, status `filled`
- [ ] Unknown questions saved to `unknown_questions` with their source page
- [ ] `engine/api.py` (FastAPI, `127.0.0.1` only): endpoints for fill, unknown questions, answers, filled pages
- [ ] Controls page in `dashboard/` (existing scaffold, design system, shared components first): Fill this page, Unknown questions, Answer bank editor, Filled pages history (see Part 2)
- [ ] **Suggested wordings screen** (Approve / Reject, protected needs a ConfirmDialog) and the unknown-questions answer form, as described in "2b. Suggested wordings" in Part 2. Needs: the Wordings mockup in `design/screens/Questions.html`, the `/wordings` and `/unknown` endpoints, and re-index after approve or answer
- [ ] **Mark as submitted** and **Abandoned** buttons on the history
- [ ] **Passive submit detection:** after a fill, the engine watches the page read-only (confirmation text such as "thank you / application received", or a URL change after you click Submit) and offers "Looks submitted. Mark it?". It never clicks anything and never marks it without your confirmation
- [ ] Run for a week of real applications; fix what breaks (log each miss in a notes file)
- [ ] README with how to run it and what it does; tag `v0.1`

**Prompts for Claude Code**

```text
Phase 4. Explain how the filler handles each field type and how we highlight
guessed answers. Then explain, step by step, how passive submit detection can work
without ever clicking. Don't code yet.
```

```text
Implement engine/forms/filler.py: fill the fields from the answer engine, upload the
resume, highlight guesses, screenshot, save the fills row, and stop. Write a test
that fails if any code path clicks Submit. Test on saved form HTML.
```

```text
Build the controls page from the design system: Fill this page, Unknown questions,
Answer bank editor and Filled pages history. Build the shared components first,
then compose the page. When done, compare it with the nearest mockups in
design/screens/ and list the differences.
```

**Run and check**

```powershell
python -m engine.api                      # engine API on 127.0.0.1
cd dashboard; npm run dev                 # controls page at localhost:3000
python -m engine.cli forms fill --mode dry_run
python -m pytest -q
```

**Done when:** it correctly fills Prosple's own form, one Google Form and one company career page; it never clicks Submit; flagged answers are highlighted; the history shows each page with its status; and you've used it for a week of real applications. **This is a complete project you can put on your resume.**

## v1: Batch mode (3–4 weeks)

Goal: JobPilot finds Prosple jobs, scores them, fills the good ones in the background with the v0 filler, and waits for your approval before submitting.

**Learn**

- BM25 pre-filtering — [rank-bm25](https://github.com/dorianbrown/rank_bm25)
- Playwright background contexts and screenshots — [Screenshots](https://playwright.dev/python/docs/screenshots)

**Checklist**

- [ ] Prosple job discovery with filters (role type, locations, max posting age) and fingerprint duplicate detection
- [ ] BM25 pre-filter, then an Ollama match score `{score, reasons, missing_skills, resume}`
- [ ] Background filling using the v0 filler, with a screenshot per application
- [ ] Review batch screen (approve/reject, edit answers, switch resume)
- [ ] Submit approved: click Submit, check for the confirmation, screenshot, status `submitted` or `failed`; never resubmit
- [ ] Applications tracker (extends the v0 filled pages history) with manual statuses, notes and a Needs manual apply tab
- [ ] Home screen
- [ ] Kill switch (a stop flag checked before every action) and a daily cap

**Done when:** a dry run fills 5 discovered jobs correctly, you approve 3 in Review batch, they submit for real, and the tracker shows the confirmations.

## v2: Cold email (1–2 weeks)

Goal: JobPilot finds a recruiter or hiring manager for each good match, verifies their email, and sends the approved cold email from your Gmail within a daily cap.

**Learn**

- OAuth 2.0 basics — [Google: Using OAuth 2.0](https://developers.google.com/identity/protocols/oauth2)
- Gmail API Python quickstart — [Quickstart](https://developers.google.com/gmail/api/quickstart/python)
- A search API — [Google Custom Search JSON API](https://developers.google.com/custom-search/v1/overview) or [Brave Search API](https://brave.com/search/api/)
- Hunter API — [Hunter API docs](https://hunter.io/api-documentation)
- Check each service's current free limits

**Checklist**

- [ ] `engine/contacts.py`: search API → names and titles → Hunter finder → verifier; save the source URL with every contact
- [ ] Email writer using only your real projects, returning `facts_used`
- [ ] Tiers: personal for top matches, short for the rest
- [ ] `engine/mailer.py`: Gmail API, `gmail.send` scope only, verified addresses only, daily cap, 2–5 min spacing, plain text
- [ ] Emails go through review for the first 2 weeks, then an auto-send switch
- [ ] Blocklist (companies, domains, people), checked before every send
- [ ] Bounce handling: mark the contact invalid
- [ ] Emails screen (Queued / Sent / Failed tabs, Regenerate)

**Done when:** a test email reaches your inbox, 3 real contacts are found with sources, and a full dry run produces emails ready for review.

## v3: Hands-off (1–2 weeks)

Goal: JobPilot runs on its own while your PC is on, alerts you when it needs you, protects your personal data, and is safe enough to leave in live mode at a low cap.

**Learn**

- Scheduling — [APScheduler user guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html)
- Windows notifications — [win11toast](https://pypi.org/project/win11toast/)
- Symmetric encryption — [cryptography: Fernet](https://cryptography.io/en/latest/fernet/)
- Gemini API (optional provider) — [Gemini API](https://ai.google.dev/gemini-api/docs)

**Checklist**

- [ ] Scheduler with active days and hours, class-hour pauses, "Run once now"
- [ ] Windows alerts: batch ready, CAPTCHA, quota out, submit failed
- [ ] CAPTCHA / logout detection → pause the site, alert, Resume button
- [ ] Fernet encryption for phone, address, email and contact emails; key in keyring; migration for existing rows
- [ ] AI provider per task in settings; Gemini → Ollama fallback when quota runs out; quota counters
- [ ] Settings, Profile, Activity log screens; onboarding; empty and error states
- [ ] A first week live at a low cap (5 a day)
- [ ] README with real results (applications, reply rate, what you changed); tag `v1.0`

**Done when:** a week of live runs at a low cap goes smoothly, the database shows encrypted personal fields, switching a task's provider works, and your README shows real numbers. That's JobPilot 1.0.

## Technologies to learn

Learn each technology right before the phase that needs it, not all at once.

| Technology | What it does in JobPilot | First needed | Docs |
| --- | --- | --- | --- |
| Git + GitHub | Version control, safe experiments | v0 Phase 0 | [Pro Git](https://git-scm.com/book/en/v2) |
| Python venv + pip | Isolated project dependencies | v0 Phase 0 | [venv](https://docs.python.org/3/library/venv.html) |
| pytest | Tests that run offline | v0 Phase 0 | [pytest](https://docs.pytest.org/en/stable/getting-started.html) |
| Ollama | Local AI: form answers, resume pick, embeddings | v0 Phase 0 | [ollama-python](https://github.com/ollama/ollama-python) |
| Pydantic | Validating AI JSON and data rows | v0 Phase 0 | [Pydantic](https://docs.pydantic.dev/latest/) |
| SQL + SQLite | All storage | v0 Phase 1 | [SQLBolt](https://sqlbolt.com/), [sqlite3](https://docs.python.org/3/library/sqlite3.html) |
| keyring | Secrets in Windows Credential Manager | v0 Phase 1 | [keyring](https://pypi.org/project/keyring/) |
| Playwright (Python) | Reading and filling forms | v0 Phase 2 | [Playwright](https://playwright.dev/python/docs/intro) |
| Embeddings + sqlite-vec | RAG retrieval | v0 Phase 3 | [sqlite-vec](https://github.com/asg017/sqlite-vec) |
| LLM prompting + structured output | Form answers, resume pick | v0 Phase 3 | [Prompt engineering](https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/overview) |
| FastAPI | Engine API for the controls page | v0 Phase 4 | [FastAPI tutorial](https://fastapi.tiangolo.com/tutorial/) |
| Next.js + TypeScript | Dashboard / controls page | v0 Phase 4 | [Next.js](https://nextjs.org/docs) |
| Tailwind CSS | Styling from your design tokens | v0 Phase 4 | [Tailwind](https://tailwindcss.com/docs) |
| BM25 (rank-bm25) | Pre-filtering jobs | v1 | [rank-bm25](https://github.com/dorianbrown/rank_bm25) |
| OAuth 2.0 + Gmail API | Sending email safely | v2 | [Gmail quickstart](https://developers.google.com/gmail/api/quickstart/python) |
| cryptography (Fernet) | Encrypting personal fields | v3 | [Fernet](https://cryptography.io/en/latest/fernet/) |
| APScheduler | Running on a schedule | v3 | [APScheduler](https://apscheduler.readthedocs.io/en/3.x/userguide.html) |
| Gemini API | Optional AI provider with fallback | v3 | [Gemini API](https://ai.google.dev/gemini-api/docs) |

The concepts matter more than the libraries: how a browser loads and finds elements, how an LLM turns a prompt into JSON, how embeddings find similar text, and how OAuth grants limited permission. If you can explain those four, you understand the system.
