# JobPilot MVP Spec

Exported from the "JobPilot MVP Spec" doc (Nov 4, 2026). Three parts:

- **Part 1: Spec** — what JobPilot is, features, architecture, stack, data model, security, run modes, risks
- **Part 2: UI screens** — every dashboard screen in detail, plus user scenarios
- **Part 3: Roadmap** — the build order (v0 in 6 phases, then v1–v4), with checklists, prompts and commands

> **For AI assistants:** the current build scope is set by "Current stage" in `CLAUDE.md`. Part 1 describes the full MVP; build only what the current phase in Part 3 asks for. Read only the section you need.

---

# Part 1: Spec

## Overview

JobPilot is a job-application copilot that runs on your Windows PC. It finds jobs on Prosple, picks the better of your two resumes, fills applications, writes and sends cold emails, and tracks everything on a local dashboard. You approve each batch before anything is submitted.

**Goals for the MVP**

- Apply to 10–25 good-match Prosple jobs a day with about 10 minutes of your time for batch review.
- Send a personal cold email to the hiring manager or recruiter for each application, within a safe daily cap.
- Keep one place that shows every application, contact, email and status.
- Learn real skills along the way: browser automation, LLM APIs, RAG, OAuth, and a full-stack app.

**Non-goals for the MVP**

- No resume tailoring. The AI only chooses between your two existing resumes.
- No LinkedIn login or LinkedIn automation of any kind.
- No filling of external employer sites. Those are logged for you to apply manually.
- No paid AI or paid services. Free tiers only.

## Features

The MVP has nine features. Everything else waits for v1.1.

| # | Feature | What it does |
| --- | --- | --- |
| 1 | Profile + RAG | Stores your details (name, school, year level, graduation year, location, links), your two resumes, and an answer bank. The AI retrieves only the pieces each task needs. |
| 2 | Prosple discovery | Searches Prosple with your filters: role type (internship/OJT, part-time, freelance, full-time), allowed locations, and maximum posting age. |
| 3 | AI matching + resume picker | Scores each job 0–100 against your profile, explains the score, and picks resume A or B. |
| 4 | Playwright apply | Fills Prosple's own application forms and uploads the chosen resume. Stops before Submit. |
| 5 | Answer bank + unknown questions | Answers form questions from the bank. Location-dependent answers (salary, relocation, commute, on-site) adapt to the job's city. Guessed answers are flagged, and new questions go to a list for you to answer once. |
| 6 | Batch review | You approve or reject queued applications and emails, then it submits the approved ones. |
| 7 | Contact finder | A web search API finds names and titles of recruiters or hiring managers. Hunter finds and verifies their email. |
| 8 | Cold email | Tiered: top matches get a researched personal email, others a shorter one. Sent through the Gmail API with a daily cap. Goes through batch review for the first 2 weeks, then auto-sends. |
| 9 | Dashboard | A local Next.js app: tracker, batch review, unanswered questions, email log, settings, kill switch, blocklist, action log. |

**v1.1 and later**

- Gmail reply tracking that updates statuses automatically (needs read permission).
- More job boards: JobStreet, Indeed, Kalibrr, LinkedIn jobs.
- LinkedIn contact lookups (capped low) and LinkedIn note drafting that you send yourself.
- AI filling of external employer sites, always routed to batch review.
- One follow-up email after a few days without a reply.
- Cold emails to companies with no open posting.
- Phone notifications.

## How it works

Code does every action and the AI only answers questions. Playwright drives a browser, the Gmail API sends email, and SQLite stores everything. The AI (Ollama locally, or Gemini) is called at a few points and returns JSON that the code acts on.

**Flow of one job:**

```
Find jobs (Playwright on Prosple)
  → Score + pick resume (AI, 1 call)
  → Fill the form (Playwright + answer bank)
  → Batch review (YOU approve)
  → Submit application (Playwright, screenshot saved)
  → Find contact (search API + Hunter)
  → Write cold email (AI, 1 call)
  → Send email (Gmail API, capped)
Every step logs to the encrypted SQLite database, and the dashboard reads it.
```

An application costs about 2–3 AI calls: one to score and pick a resume, one to map form fields to answers when the form has questions, and one for the cold email.

**Where the AI is used**

- **Match + resume pick:** job post + profile summary in, `{score, reasons, missing_skills, resume: "A"|"B"}` out.
- **Form answers:** field labels + retrieved profile and answer-bank snippets in, `{field: answer, confidence}` out. Low confidence = flagged; no match = added to the unknown-questions list.
- **Cold email:** job, contact name and title, and your matching projects in, subject + body out.
- **RAG retrieval:** profile, resumes and answer bank are split into chunks and embedded. Each task pulls only the top matching chunks.

**What stays out of the AI:** phone number, home address, ID numbers and similar fields are filled by code directly from the encrypted database.

**Claude Pro vs the app's AI:** Claude Pro (with Claude Code) is the coding assistant for building JobPilot. It does not give the app an API key. The running app uses Ollama (local) and/or the Gemini API free tier.

## Stack

Python runs the engine, and Next.js runs the dashboard. Everything is free, and everything runs on your Windows PC.

| Part | Choice | Why |
| --- | --- | --- |
| Language | Python 3.12 | Best libraries for automation and AI |
| Browser automation | Playwright for Python, with a dedicated Chrome profile logged into Prosple | Real logged-in session; `playwright codegen` records selectors |
| Engine API | FastAPI | Dashboard talks to the engine over localhost; used in EconLens |
| Database | SQLite + `cryptography` (Fernet) for sensitive columns | One file, no server; personal fields encrypted |
| Secrets | `keyring` → Windows Credential Manager | No API keys in `.env` files that could get committed |
| AI | Ollama (local) and/or Gemini API free tier via `google-genai` | Free; structured JSON output |
| Embeddings + RAG | Ollama `nomic-embed-text` + `sqlite-vec` | Vectors live in the same SQLite file |
| Email | Gmail API via `google-api-python-client`, `gmail.send` scope only | Official OAuth, can only send |
| Contacts | Google Programmable Search or Brave Search API + Hunter API | Names and titles without logging into LinkedIn; verified emails |
| Scheduling | APScheduler | Runs jobs while the PC is on |
| Notifications | `win11toast` | Windows pop-ups |
| Dashboard | Next.js + TypeScript + Tailwind | Used in Countdown Game |
| Tests | pytest + saved HTML fixtures | Test scrapers offline |

Free-tier limits for Gemini, the search API and Hunter change often. Check the current numbers on each provider's site before building those parts.

**Local AI: Ollama.** All AI calls go through one `ask_ai()` function. A setting picks the provider per task:

| Task | Suggested provider | Why |
| --- | --- | --- |
| Match + resume pick | Ollama | Many calls, short JSON, private, no quota |
| Form answers | Ollama | Your personal details never leave the PC |
| Embeddings (RAG) | Ollama (`nomic-embed-text`) | Free and fast locally |
| Cold emails | Gemini | Writing quality matters most here |

Model size depends on the PC: a 7–8B model needs about 8 GB of GPU VRAM; a 3–4B model (e.g. `qwen3:4b`, `gemma3:4b`, `llama3.2:3b`) works on 4–6 GB VRAM or 8–16 GB RAM. Local models follow JSON instructions less reliably, so Pydantic validation and one retry are required. If Gemini's quota runs out, the app can fall back to Ollama for that task.

## Data model

Ten SQLite tables hold everything. Columns marked (enc) are encrypted.

| Table | Key columns |
| --- | --- |
| `profile` | name, email (enc), phone (enc), address (enc), school, year_level, grad_year, location, links, preferred_locations, job_types |
| `resumes` | id (A/B), label (e.g. web, mobile), file_path, extracted_text |
| `chunks` | source (profile/resume/answer), text, embedding |
| `answers` | question, answer, location_scope (any / city / remote / abroad), times_used |
| `unknown_questions` | question_text, job_id, first_seen, status (open/answered) |
| `jobs` | source, url, title, company, location, job_type, posted_at, text, fingerprint (for duplicates), apply_type (native/external) |
| `applications` | job_id, score, reasons, resume_id, status (new → queued → approved → submitted / rejected / failed / manual), filled_fields, flagged_fields, submitted_at, screenshot_path |
| `contacts` | company, name, title, email (enc), email_verified, source_url |
| `emails` | application_id or company, contact_id, tier (personal/short), subject, body, status (draft → queued → sent / failed / bounced), sent_at |
| `action_log` | time, kind (navigate, fill, submit, email, error, captcha), target, details, screenshot_path |

Settings (daily caps, score thresholds, filters, blocklist, run mode, the auto-send switch for emails) live in a `settings` table or a JSON file.

## Security and privacy rules

These rules are requirements, not suggestions. Each one should have a test or a check.

1. **No secrets in the repo.** API keys, the Gmail OAuth token and the database key live in Windows Credential Manager via `keyring`. `.gitignore` covers `data/`, `*.db`, `*.env*`, `profiles/`, `screenshots/`, and the resumes folder.
2. **Encrypt personal fields.** Phone, address, email and contact emails are encrypted with Fernet. The key is stored in Credential Manager.
3. **Least data to the AI.** Each prompt gets only the retrieved chunks it needs. Phone, address and ID numbers are never sent; code fills those fields directly.
4. **No invented facts.** The AI may only use facts from the profile, resumes and answer bank. Legal, eligibility, GPA and "have you ever" questions come only from the answer bank. Otherwise they go to unknown questions.
5. **Least permission.** Gmail uses the `gmail.send` scope only. The bot uses its own Chrome profile, separate from your everyday browser.
6. **Never store site passwords.** You log into Prosple once by hand in the bot's Chrome profile. The tool reuses that session.
7. **Localhost only.** The FastAPI engine and the dashboard bind to `127.0.0.1`, never `0.0.0.0`.
8. **Kill switch.** One dashboard button stops all browser actions and emails within a second. The engine checks a stop flag before every action.
9. **Blocklist.** Companies, domains and people that must never get an application or email. Checked before every submit and send.
10. **Action log.** Every navigate, fill, submit and email is logged, with a screenshot for submits and errors.
11. **Contact data stays local.** Names and emails of other people are never shared or exported. Check the Philippine Data Privacy Act before sharing the tool with others.

## Run modes

Three modes share the same code. Only two switches change: whether the AI is real, and whether submit and send are real.

| Mode | Prosple | AI | Submit | Email | Use it for |
| --- | --- | --- | --- | --- | --- |
| Mock | Saved HTML pages, offline | Fake: canned JSON from `fixtures/ai/` | Never | Never; saved to the log | Building and testing the plumbing, no quota used |
| Dry run | Real site | Real AI calls | Never; screenshot of the filled form instead | Never; shown in the log for reading | Checking quality of matches, answers and emails |
| Live | Real site | Real | After batch approval | Real (reviewed for the first 2 weeks) | Actual applying |

**How the fake AI works.** All AI calls go through one function, `ask_ai(task, prompt)`. In mock mode it skips the model and returns a pre-written answer for that task, such as `{"score": 78, "resume": "A"}`. Tests can also choose the answer, for example a low score, to check that the job gets skipped.

**How saved pages work.** Run once against Prosple in a record mode that saves each page's HTML into `fixtures/prosple/`. Mock mode loads those files instead of the live site, so scraper tests run offline and never touch the real site.

The current mode shows as a coloured badge on every dashboard screen, so live mode is never a surprise.

## Limits, risks and edge cases

Free-tier quotas will cap real throughput below 25 a day. Each other risk has a planned response.

| Situation | What JobPilot does |
| --- | --- |
| AI or Hunter free quota used up | Spends quota on the best matches first, queues the rest for tomorrow, alerts you |
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
3. **Resume:** a toggle with two options, `Resume A · Web` and `Resume B · Mobile`, the AI's choice pre-selected with "AI picked this because…". A Preview link opens the PDF.
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

Jenel opens JobPilot for the first time. The stepper asks for his details, school and expected graduation. He drags in Resume A (Web / Full stack) and Resume B (Mobile / Flutter). He picks Internship, Part-time and Full-time, with Metro Manila and Remote as locations. He connects Gmail, which says "Send-only permission", and chooses Ollama for matching and Gemini for emails. He logs into Prosple in the bot browser. He clicks "Find my first matches (dry run)", watches the progress list, and lands on Review batch with 14 matches and nothing submitted.

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

Build JobPilot in small versions, each one finished and usable on its own: v0 (job finder and tracker) in 6 phases, then v1–v4. Each phase lists what to learn, what to prompt Claude Code, what to run, and how to know it's done.

## At a glance

| Version / phase | What | Time |
| --- | --- | --- |
| **v0** Phase 0 | Setup and foundations | 3–4 days |
| v0 Phase 1 | Profile and resumes | 1 week |
| v0 Phase 2 | Prosple scraper | 1–1.5 weeks |
| v0 Phase 3 | Matching and resume picker | 1 week |
| v0 Phase 4 | Engine API and dashboard v0 | 1.5 weeks |
| v0 Phase 5 | Email drafts and v0 release → **tag v0.1, resume-ready** | 1 week |
| **v1** | Apply flow: forms + batch review | 2–3 weeks |
| **v2** | Contact finder + Gmail sending | 1–1.5 weeks |
| **v3** | RAG, encryption, AI routing and fallback | 1.5 weeks |
| **v4** | Safety, polish, first live run → **JobPilot 1.0** | 1–1.5 weeks |

v0 takes about 6 weeks at 10–15 hours a week and is a complete project on its own. Each later version adds one capability, and you can stop after any of them.

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

- [ ] Install Python 3.12, Node.js LTS, Git, VS Code, Ollama
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
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q
python -c "from engine.ai import ask_ai; print(ask_ai('match', 'test'))"
```

**Done when:** tests pass, mock and Ollama both return JSON, and `git log` shows your first commits with no secrets.

## Phase 1: Profile and resumes (1 week)

Goal: your details and both resumes live in a local SQLite database, loaded from a JSON file and readable by code.

**Learn**

- SQL basics: CREATE, INSERT, SELECT, UPDATE — [SQLBolt lessons 1–12](https://sqlbolt.com/)
- Python `sqlite3` — [docs](https://docs.python.org/3/library/sqlite3.html)
- Pydantic models — [Pydantic docs](https://docs.pydantic.dev/latest/)
- Extracting text from PDFs — [pdfplumber](https://github.com/jsvine/pdfplumber)
- Storing secrets — [keyring](https://pypi.org/project/keyring/)

**Checklist**

- [ ] `engine/db.py`: create tables `profile`, `resumes`, `jobs`, `applications`, `action_log` (from the Data model in Part 1)
- [ ] `data/profile.json` (git-ignored) with your real details; a `profile.example.json` with fake ones is committed
- [ ] Your 2 resume PDFs in `data/resumes/` with labels (e.g. A = Web, B = Mobile)
- [ ] `engine/profile.py`: load the profile and resumes into the DB, extract resume text
- [ ] `engine/secrets.py`: get/set API keys through `keyring`
- [ ] CLI command: `python -m engine.cli profile show`
- [ ] Tests with a fake profile and a small sample PDF

**Prompts for Claude Code**

```text
Phase 1. First explain how SQLite works in Python and what each table in the spec's
data model is for. Then create engine/db.py with only the tables profile, resumes,
jobs, applications and action_log. Use Pydantic models for rows. Show me the SQL.
```

```text
Create engine/profile.py that loads data/profile.json and the resumes in
data/resumes/ into the database, extracting each resume's text with pdfplumber.
Add a CLI command "profile show" that prints the profile with phone and address
masked. Write tests using fixtures, never my real data.
```

**Run and check**

```powershell
python -m engine.cli profile load
python -m engine.cli profile show
python -m pytest -q
git status   # data/ must NOT appear
```

**Done when:** the profile loads, resume text prints, tests pass, and `git status` shows no personal files.

## Phase 2: Prosple scraper (1–1.5 weeks)

Goal: JobPilot opens Prosple in its own Chrome profile, searches with your filters, and saves job listings to the database without duplicates.

**Learn**

- HTML and CSS selectors (enough to read a page's structure) — [MDN: CSS selectors](https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_selectors)
- Playwright for Python: intro, locators, waits, persistent context — [Playwright Python docs](https://playwright.dev/python/docs/intro)
- Recording selectors with codegen — [Test generator](https://playwright.dev/python/docs/codegen)
- Read Prosple's terms of use before automating it

**Checklist**

- [ ] `playwright install chromium`; create the bot's persistent browser profile in `data/browser/`
- [ ] Log into Prosple once by hand in that profile
- [ ] Run `playwright codegen` on a Prosple search, note the selectors
- [ ] `engine/sites/prosple.py`: search → collect job links → open each → extract title, company, location, type, posted date, description, apply type (native or external)
- [ ] Random 1–4 s delays between actions; a max of N jobs per run
- [ ] Duplicate fingerprint (company + title + location)
- [ ] Record mode: save each page's HTML to `fixtures/prosple/`
- [ ] Mock mode: parse the saved HTML instead of the live site
- [ ] Log every navigate to `action_log`

**Prompts for Claude Code**

```text
Phase 2. Explain how Playwright's persistent context works and why we use a separate
Chrome profile. Then write a small script that opens Prosple in data/browser/ with
a visible window so I can log in once by hand. Nothing else yet.
```

```text
Here are the selectors I recorded with codegen: <paste>. Write
engine/sites/prosple.py with search_jobs(filters) and get_job(url). Separate
"fetch the HTML" from "parse the HTML" so parsing can be tested on saved files in
fixtures/prosple/. Add human-like delays and log each navigation. Prefer role and
text locators over CSS classes.
```

```text
Write tests for the parser using the saved HTML fixtures. Then show me what happens
if a field is missing: it should skip that job and log it, not crash.
```

**Run and check**

```powershell
playwright codegen https://prosple.com
python -m engine.cli scrape --mode mock
python -m engine.cli scrape --mode dry_run --limit 20
python -m engine.cli jobs list
```

**Done when:** a dry run saves about 20 real jobs, running it twice adds no duplicates, and the parser tests pass offline.

## Phase 3: Matching and resume picker (1 week)

Goal: every saved job gets a score 0–100, reasons, missing skills, and resume A or B. Your own judgment is the test.

**Learn**

- How LLM APIs work: messages, temperature, tokens — [Ollama API reference](https://github.com/ollama/ollama/blob/main/docs/api.md)
- Structured (JSON) output — [Ollama structured outputs](https://ollama.com/blog/structured-outputs) and [Gemini structured output](https://ai.google.dev/gemini-api/docs/structured-output)
- Prompt design basics — [Anthropic prompt engineering overview](https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/overview) (the ideas apply to any model)
- BM25 (already in `jobpilot/bm25.py`) — read the code and explain it

**Checklist**

- [ ] Move the existing `bm25.py` + `matcher.py` in as a cheap pre-filter (skip obvious misfits before any AI call)
- [ ] Filters before AI: job type, location, posting age, blocklist
- [ ] Prompt in `prompts/match.md`: profile summary + both resume summaries + job → `{score, reasons[], missing_skills[], resume: "A"|"B", resume_reason}`
- [ ] Pydantic validation; on invalid JSON retry once, then skip and log
- [ ] Save the results to `applications` with status `new`
- [ ] An evaluation file: 10 real jobs where you wrote down your own score and resume choice
- [ ] Compare the AI vs your answers; tweak the prompt until they mostly agree

**Prompts for Claude Code**

```text
Phase 3. Explain the difference between the BM25 pre-filter and the AI scoring,
and why we use both. Then design the match prompt in prompts/match.md. Show me the
prompt and the JSON schema before writing code.
```

```text
Write engine/matcher.py: pre-filter -> ask_ai("match", ...) -> validate -> save.
Add a CLI "match --limit 10" and an "eval" command that compares AI results with
data/eval/my_scores.json and prints where we disagree.
```

**Run and check**

```powershell
python -m engine.cli match --mode mock
python -m engine.cli match --limit 10
python -m engine.cli eval
```

**Done when:** on your 10 evaluation jobs, the AI's resume choice matches yours at least 8 times and the scores rank jobs roughly the way you would.

## Phase 4: Engine API and dashboard v0 (1.5 weeks)

Goal: a local dashboard, styled from your design system, that shows the app shell, a simple Home, and the Applications tracker with real data.

**Learn**

- FastAPI: path operations, request/response models, CORS — [FastAPI tutorial](https://fastapi.tiangolo.com/tutorial/)
- Next.js App Router: pages, layouts, data fetching — [Next.js docs](https://nextjs.org/docs)
- Tailwind CSS theme customization (to map your tokens) — [Tailwind theme](https://tailwindcss.com/docs/theme)
- TypeScript refresher — [TypeScript handbook](https://www.typescriptlang.org/docs/handbook/intro.html)

**Checklist**

- [ ] `engine/api.py`: FastAPI on `127.0.0.1:8000` with `GET /jobs`, `GET /applications`, `PATCH /applications/{id}` (status, notes), `GET /stats`
- [ ] `npx create-next-app@latest dashboard` (TypeScript, Tailwind, App Router)
- [ ] Import `design/tokens.css` in `globals.css`; map tokens in the Tailwind theme
- [ ] Shared components in `components/ui/`: StatusChip, ScoreBadge, ModeBadge, Button, NavItem, StatCard, DataTable, Drawer, EmptyState
- [ ] App shell: top bar + sidebar, matching `design/screens/Patterns.html`
- [ ] Home (lite): stat cards + top matches, from `Home.html`
- [ ] Applications tracker: table, filters, status dropdown, detail drawer with notes, from `Applications.html`
- [ ] Side-by-side check of each screen vs its mockup

**Prompts for Claude Code**

```text
Phase 4, backend. Explain how FastAPI routes and Pydantic response models work.
Then create engine/api.py with the endpoints in the roadmap, bound to 127.0.0.1
only, with CORS allowing http://localhost:3000.
```

```text
Phase 4, frontend. Read design/DESIGN.md and design/tokens.css. Set up the Next.js
app so tokens.css is imported and mapped into the Tailwind theme. Then build the
shared components listed in DESIGN.md, matching design/screens/Components.html.
Show them all on a /dev/components page so I can compare with the mockup.
```

```text
Build the Applications tracker page from design/screens/Applications.html, using
only components from components/ui and data from GET /applications. When done,
list every visual difference from the mockup.
```

**Run and check**

```powershell
python -m engine.api                # terminal 1
cd dashboard; npm run dev           # terminal 2, open http://localhost:3000
```

**Done when:** the tracker shows your real jobs from Phase 3, changing a status persists after a refresh, and the screens look like your mockups.

## Phase 5: Email drafts and v0 release (1 week)

Goal: each good match gets a cold email draft you can edit and copy, and v0 is finished, documented and in daily use.

**Learn**

- Writing good cold emails (short, specific, one ask). Read 2–3 guides and save examples you like.
- Gemini API quickstart, if you use it for emails — [Gemini API docs](https://ai.google.dev/gemini-api/docs)

**Checklist**

- [ ] `prompts/email.md`: job + your matching projects + optional contact name → `{subject, body, facts_used[]}`; only facts from your profile
- [ ] Generate drafts for applications with score ≥ your threshold
- [ ] `emails` table + `GET /emails`, `PATCH /emails/{id}`
- [ ] Emails screen (lite) from `Emails.html`: list + preview, editable body, **Copy** button, "Facts used" list
- [ ] Link from each tracker row to its draft
- [ ] Use v0 for real for a week: run scrape + match each morning, apply manually, send emails yourself from Gmail
- [ ] Write the README: what it does, a screenshot, how to run, design decisions, what's next
- [ ] Tag the release: `git tag v0.1`

**Prompts for Claude Code**

```text
Phase 5. Write prompts/email.md for a short, friendly cold email from a CS student.
Rules: under 120 words, mention one specific project that matches the job, one
clear ask, no invented facts. Return facts_used so I can verify. Show me 3 sample
drafts in mock mode first.
```

```text
Build the Emails page (lite) from design/screens/Emails.html: list on the left,
preview on the right with editable subject/body, a Copy button, and the facts_used
list. No sending yet.
```

```text
Help me write the README for v0. Ask me 5 questions about my design decisions
first, then draft it. Keep it honest about what's not built yet.
```

**Run and check**

```powershell
python -m engine.cli scrape --mode dry_run
python -m engine.cli match
python -m engine.cli drafts
```

**Done when:** you have used v0 for a week to find jobs and send emails, the README is written, and `v0.1` is tagged. **This is a complete project you can put on your resume.**

## v1: Apply flow with batch review (2–3 weeks)

Goal: JobPilot fills Prosple's own application forms and uploads the right resume, then waits for your approval in Review batch before submitting.

**Learn**

- Playwright forms: fill, select, check, file upload, waiting — [Input actions](https://playwright.dev/python/docs/input) and [Auto-waiting](https://playwright.dev/python/docs/actionability)
- Screenshots — [Screenshots](https://playwright.dev/python/docs/screenshots)

**Checklist**

- [ ] Read the form: collect every field's label, type and options
- [ ] Answer bank table + `answers` lookup (exact and similar questions, with location scope)
- [ ] `prompts/form.md`: field labels + allowed facts → `{field: answer, confidence, source}`; legal/eligibility questions never answered by AI
- [ ] Private fields (phone, address) filled by code, never sent to AI
- [ ] Unknown questions go to the `unknown_questions` table
- [ ] Stop before Submit, screenshot, set status `queued`
- [ ] Review batch screen from `Review.html`; Questions screen from `Questions.html`
- [ ] Submit approved: click Submit, check for the confirmation, screenshot, status `submitted` or `failed` (never resubmit)
- [ ] Kill switch: a stop flag checked before every action, plus a STOP button in the top bar

**Prompts for Claude Code**

```text
v1. Explain how we'll read an unknown form's fields with Playwright and decide
which answers come from code, the answer bank, or the AI. Draw it as a short flow
in text. Don't code yet.
```

```text
Implement fill_application(job) in engine/sites/prosple.py following that flow.
It must stop before Submit, take a screenshot, and save filled and flagged fields.
Test it on saved form HTML in fixtures/prosple/forms/.
```

```text
Build the Review batch page from design/screens/Review.html and the Questions
page from Questions.html. Approve and reject call the API; "Submit approved" opens
the confirm dialog from Components.html.
```

**Run and check**

```powershell
python -m engine.cli apply --mode dry_run --limit 5   # fills, screenshots, never submits
```

**Done when:** a dry run fills 5 real forms correctly, you approve 3 in Review batch, they submit for real, and you see the confirmations.

## v2: Contact finder and Gmail sending (1–1.5 weeks)

Goal: JobPilot finds a recruiter or hiring manager for each good match, verifies their email, and sends the approved cold email from your Gmail within a daily cap.

**Learn**

- OAuth 2.0 basics (what a token and a scope are) — [Google: Using OAuth 2.0](https://developers.google.com/identity/protocols/oauth2)
- Gmail API Python quickstart — [Quickstart](https://developers.google.com/gmail/api/quickstart/python)
- A search API — [Google Custom Search JSON API](https://developers.google.com/custom-search/v1/overview) or [Brave Search API](https://brave.com/search/api/)
- Hunter API: domain search, email finder, verifier — [Hunter API docs](https://hunter.io/api-documentation)
- Check each service's current free limits

**Checklist**

- [ ] Google Cloud project; OAuth client; `gmail.send` scope only; token stored with `keyring`
- [ ] `engine/contacts.py`: search for `"<company>" recruiter OR "talent acquisition" site:linkedin.com/in` → names + titles → Hunter finder → verifier
- [ ] Save the contact's source URL with every contact
- [ ] Tiered emails: personal for score ≥ 80, short for the rest
- [ ] `engine/mailer.py`: send only verified addresses, daily cap, 2–5 min random spacing, plain text
- [ ] Emails queue in Review batch for the first 2 weeks; then an auto-send switch
- [ ] Bounce handling: mark the contact invalid
- [ ] Full Emails screen (Queued / Sent / Failed tabs, Regenerate)

**Prompts for Claude Code**

```text
v2. Explain OAuth 2.0 for Gmail in simple terms: client ID, consent screen, scope,
access and refresh tokens. Then walk me through the Google Cloud setup step by
step. I'll do the clicking; you tell me what to click.
```

```text
Write engine/mailer.py using the Gmail API with only the gmail.send scope, token
from keyring. Enforce the daily cap and random spacing. In mock and dry_run modes
it must never send. Send exactly one test email to myself in live mode.
```

```text
Write engine/contacts.py: search API -> candidate names and titles -> Hunter
finder -> verifier. Count every API call against the daily quota. Test with saved
responses in fixtures/, never live calls.
```

**Run and check**

```powershell
python -m engine.cli contacts --limit 3 --mode dry_run
python -m engine.cli email test --to me
```

**Done when:** the test email reaches your inbox, 3 real contacts are found with sources, and a full dry run produces emails ready for review.

## v3: RAG, encryption and AI routing (1.5 weeks)

Goal: forms and emails pull only the relevant pieces of your profile, personal fields are encrypted, and each AI task can use Ollama or Gemini with automatic fallback.

**Learn**

- Embeddings and similarity search: what a vector is and why cosine similarity works. Any short intro article, then the [Ollama embeddings docs](https://github.com/ollama/ollama/blob/main/docs/api.md)
- Vector storage in SQLite — [sqlite-vec](https://github.com/asg017/sqlite-vec)
- Symmetric encryption — [cryptography: Fernet](https://cryptography.io/en/latest/fernet/)

**Checklist**

- [ ] `engine/rag.py`: chunk the profile, resumes and answer bank; embed with `nomic-embed-text` via Ollama; store in sqlite-vec
- [ ] `retrieve(question, k=5)`; form and email prompts now use only retrieved chunks
- [ ] Re-index command, plus a Re-index button on the Profile screen
- [ ] Fernet encryption for phone, address, email and contact emails; the key in keyring
- [ ] Migration: encrypt the existing rows
- [ ] Provider per task in settings; Gemini → Ollama fallback when quota runs out; quota counters
- [ ] Profile screen from `Profile.html`; Settings screen from `Settings.html`

**Prompts for Claude Code**

```text
v3. Teach me RAG with a tiny example first: 5 sentences, embed them with Ollama,
ask a question, show the similarity scores. Then we'll apply it to my profile.
```

```text
Implement engine/rag.py with sqlite-vec and nomic-embed-text. Show me which chunks
are retrieved for 3 real form questions, so I can judge if retrieval works.
```

```text
Add Fernet encryption for the sensitive columns listed in the spec, with the key
in keyring, and write a one-time migration. Prove with a test that the database
file doesn't contain my phone number in plain text.
```

**Run and check**

```powershell
python -m engine.cli rag reindex
python -m engine.cli rag ask "What is your expected graduation date?"
python -m pytest -q
```

**Done when:** retrieval returns the right chunks for 5 test questions, the DB shows encrypted values, and switching a task's provider in Settings works.

## v4: Safety, polish and first live run (1–1.5 weeks)

Goal: JobPilot runs on its own while your PC is on, alerts you when it needs you, and is safe enough to leave in live mode at a low cap.

**Learn**

- Scheduling jobs — [APScheduler user guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html)
- Windows notifications — [win11toast](https://pypi.org/project/win11toast/)

**Checklist**

- [ ] Scheduler: active days and hours, class-hour pauses, "Run once now"
- [ ] Blocklist (companies, domains, people), checked before every submit and send
- [ ] Daily caps for applications, emails, AI calls and lookups, shown in the top bar
- [ ] CAPTCHA / logout detection → pause the site, Windows alert, resume button
- [ ] Windows alerts: batch ready, CAPTCHA, quota out, submit failed
- [ ] Activity log screen from `Activity.html`; full Home from `Home.html`
- [ ] Onboarding from `Onboarding.html`; empty and error states from `States.html`
- [ ] A full week in dry run, then live at 5 applications a day
- [ ] Update the README with results (applications, reply rate, what you changed) and tag `v1.0`

**Prompts for Claude Code**

```text
v4. Review the whole engine for safety: list every place that can submit, send, or
navigate, and confirm each one calls safety.check() and logs to action_log. Show me
any gaps before fixing them.
```

```text
Build the onboarding flow and the empty/error states from Onboarding.html and
States.html. Then do a design QA pass: open every screen next to its mockup and
list the differences.
```

**Run and check**

```powershell
python -m engine.cli run --mode dry_run     # leave it running for a day
python -m engine.cli stats --week
```

**Done when:** a week of live runs at 5 a day goes smoothly, and your README shows real numbers. That's JobPilot 1.0.

## Technologies to learn

There are 17 technologies in total. Learn each one right before the phase that needs it, not all at once.

| Technology | What it does in JobPilot | First needed | Docs |
| --- | --- | --- | --- |
| Git + GitHub | Version control, safe experiments | Phase 0 | [Pro Git](https://git-scm.com/book/en/v2) |
| Python venv + pip | Isolated project dependencies | Phase 0 | [venv](https://docs.python.org/3/library/venv.html) |
| pytest | Tests that run offline | Phase 0 | [pytest](https://docs.pytest.org/en/stable/getting-started.html) |
| Ollama | Local AI: matching, form answers, embeddings | Phase 0 | [ollama-python](https://github.com/ollama/ollama-python) |
| Pydantic | Validating AI JSON and data rows | Phase 0 | [Pydantic](https://docs.pydantic.dev/latest/) |
| SQL + SQLite | All storage | Phase 1 | [SQLBolt](https://sqlbolt.com/), [sqlite3](https://docs.python.org/3/library/sqlite3.html) |
| keyring | API keys and tokens in Windows Credential Manager | Phase 1 | [keyring](https://pypi.org/project/keyring/) |
| Playwright (Python) | Browser automation: scraping, filling forms | Phase 2 | [Playwright](https://playwright.dev/python/docs/intro) |
| LLM prompting + structured output | Scoring, resume pick, answers, emails | Phase 3 | [Prompt engineering](https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/overview) |
| FastAPI | Engine API for the dashboard | Phase 4 | [FastAPI tutorial](https://fastapi.tiangolo.com/tutorial/) |
| Next.js + TypeScript | Dashboard | Phase 4 | [Next.js](https://nextjs.org/docs) |
| Tailwind CSS | Styling from your design tokens | Phase 4 | [Tailwind](https://tailwindcss.com/docs) |
| Gemini API | Cold email writing (optional) | Phase 5 | [Gemini API](https://ai.google.dev/gemini-api/docs) |
| OAuth 2.0 + Gmail API | Sending email safely | v2 | [Gmail quickstart](https://developers.google.com/gmail/api/quickstart/python) |
| Embeddings + sqlite-vec | RAG retrieval | v3 | [sqlite-vec](https://github.com/asg017/sqlite-vec) |
| cryptography (Fernet) | Encrypting personal fields | v3 | [Fernet](https://cryptography.io/en/latest/fernet/) |
| APScheduler | Running on a schedule | v4 | [APScheduler](https://apscheduler.readthedocs.io/en/3.x/userguide.html) |

The concepts matter more than the libraries: how a browser loads and finds elements, how an LLM turns a prompt into JSON, how embeddings find similar text, and how OAuth grants limited permission. If you can explain those four, you understand the system.
