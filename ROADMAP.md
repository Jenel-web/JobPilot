# JobPilot Roadmap: from today to done

Written Nov 9, 2026 for Jenel. This is the working checklist. For library docs and learning links, see Part 3 of [SPEC.md](SPEC.md). For the rules Claude Code follows, see [CLAUDE.md](CLAUDE.md).

**How to read each phase**

- **You do**: things only you can do, outside prompting (real data, logging in, picking test pages, judging results).
- **Prompt Claude Code**: the sessions to run, in order. Each starts with the plan-first routine (explain, plan, wait for your OK).
- **Check**: commands and manual tests that prove it works.
- **Done when**: the exit gate. Don't start the next phase before it passes. Then update "Current stage" in CLAUDE.md and commit.

---

## 1. Where the project is today

| Area | State | Notes |
| --- | --- | --- |
| Repo, git, `.gitignore`, CLAUDE.md, SPEC.md, `design/` | Done | 3 commits, working tree clean |
| `engine/ai.py` (`ask_ai`, mock + Ollama, Pydantic, one retry) | Done | Tasks: `form_answer`, `resume_pick` (v0), `match`, `email` (v1/v2) |
| `engine/settings.py` + `settings.json` | Done | `run_mode` and `ai_provider` only |
| `fixtures/ai/` | Done for now | `form_answer`, `resume_pick`, `match`, `email` |
| Tests | 109 pass | `test_ai.py` (ai + settings, including the new v0 tasks). The old-plan matcher tests were removed |
| Ollama | Ready | `llama3.1:8b` and `nomic-embed-text` pulled |
| `engine/db.py`, `profile.py`, `secrets.py`, `safety.py`, `cli.py` | Done (Phase 1) | Real data loads into `data/jobpilot.db` |
| `engine/forms/browser.py` | Done (Phase 2 step 1) | Launcher; you have not tried it yet |
| `engine/forms/reader.py`, `capture.py` | Done (Phase 2) | Reader + capture; 1 real form saved, 2 more wanted (Google Form, Prosple) |
| `engine/rag.py` | Built (Phase 3 step 2) | Chunks, `sqlite-vec` index, `retrieve()`, `rag reindex/ask/eval`; tested with mock vectors only. Not yet judged on real Ollama vectors |
| `api.py` | Empty stub | Phase 4 |
| `engine/forms/`, `fixtures/forms/`, `prompts/` | Created (empty) | Filled from Phase 2 |
| `requirements.txt` | Incomplete | Has `ollama`, `pydantic`, `pytest`. Playwright, FastAPI, uvicorn, pdfplumber, keyring, sqlite-vec still to add, one at a time with your OK |
| Dashboard (`dashboard/`) | Built ahead of schedule | Shell, 25 shared UI components, Home, Applications and Review pages, all on mock data. None of the 4 v0 controls-page sections exist yet |

**Housekeeping (done Nov 9, 2026)**

1. Python: the machine and venv run 3.13.2, so CLAUDE.md and SPEC.md now say 3.13.
2. Old-plan code removed: the `jobpilot/` package (`bm25.py`, `matcher.py`, `cli.py`), `tests/test_matcher.py` and `data/sample_jobs.json`. The code is still in git history (`git show d12ff77:jobpilot/matcher.py`) if you want it for v1. `sample_jobs.json` was git-ignored, so it is gone for good (fake sample data).
3. Stray root `.next/` build folder deleted.
4. `ask_ai` comment fixed: the form tasks arrive in v0.
5. Created `engine/forms/` (with `__init__.py`), `fixtures/forms/`, `prompts/`, and `.gitkeep` files so empty folders stay in git.
6. `.gitignore` now allows `data/*.example.json`, so `profile.example.json` can be committed (it was being ignored by `data/*`).
7. The dashboard is untouched. Home, Applications and Review are v1 screens built early. Phase 4 adds the controls page beside them and reuses the existing components.

**Still open in Phase 0:** nothing except your commit.

**Current position:** v0, Phase 2 done (3 forms: Angkas/Workable, Indie Campers/Greenhouse iframe, a synthetic one; Google Form skipped by choice). Now: Phase 3. `rag.py` is built and tuned (right saved question first 25/26 on the eval). The `llama3.1:8b` match judge was tested and put on hold (too unreliable on this PC). Next: compare stronger embedding models, then the personal-field detector and `engine/forms/answers.py`.

**Progress log** (newest last; Claude Code adds a line after every working step)

- 2026-11-09: plan changed to RAG + form filler; SPEC.md, CLAUDE.md and this roadmap rewritten.
- 2026-11-09: Phase 0 cleanup (Python 3.13 docs, old matcher removed, `engine/forms/`, `fixtures/forms/`, `prompts/` added).
- 2026-11-09: `form_answer` and `resume_pick` AI tasks added with fixtures and mock-mode tests (40 tests pass).
- 2026-11-09: data folders and templates created (`data/resumes/`, `screenshots/`, `browser_profile/`, `answers.json`, new `profile.example.json`); resumes are now "A and B with your own label and target", not Web/Mobile.
- 2026-11-09: reviewed `answers.json` (96 answers): added `kind` per answer (fixed/open/protected; simplified from 5 kinds the same day), fixed typos in 2 answers and the GPA wording; resume picker now returns `evidence` and judges by resume content; upload uses a formal file name.
- 2026-11-09: `pdfplumber` and `keyring` approved and installed (`requirements.txt` updated); profile.json updated to the new shape; both resume PDFs have readable text.
- 2026-11-09: Phase 1 step 1: `engine/db.py` (6 tables, safe defaults, constraints) + `tests/test_db.py` (52 tests pass).
- 2026-11-09: Phase 1 complete: `engine/profile.py` (loads profile, resumes via pdfplumber, 96 answers; scoped `lookup_answer`; masked `profile_summary`), `engine/secrets.py` (keyring), `engine/safety.py` (`check()` refuses submit/send in v0, `log_action`), `engine/cli.py` (`load`, `profile show`, `answers list`). 83 tests pass. Real data loaded into `data/jobpilot.db`. Removed the real phone number that had slipped into a docstring and a test.
- 2026-11-09: Phase 2 step 1: `playwright` 1.64.1 + Chromium installed; `engine/forms/browser.py` (own persistent profile, visible window, debugging port on 127.0.0.1 only) and `python -m engine.cli browser open`; 86 tests pass. Decision: the bot uses its OWN browser profile, never your everyday Chrome.
- 2026-11-09: Phase 2 step 3: `engine/forms/reader.py` (`FormField`, `read_fields`, `read_current_page`) + `python -m engine.cli forms read`; synthetic `fixtures/forms/sample_form.html`; 97 tests pass. Tried on a real company page: 28 raw elements became 20 fields, radio pairs merged into 4 questions. Fixed: nearby-text label search climbing too high, lone checkboxes, empty `<label for>`, select placeholder options.
- 2026-11-09: Phase 2 step 4: `engine/forms/capture.py` + `python -m engine.cli forms capture NAME` (removes scripts, typed values, hidden inputs, your name/email/phone/address); captured `fixtures/forms/angkas_workable.html`, checked it for leaks (none); offline test reads it as 20 fields. 103 tests pass.
- 2026-11-09: Phase 2 bug-fix round after a third real site (Indie Campers) read only "Enter your e-mail": the application form was inside an iframe. Fixed: reader now reads every frame (`FormField.frame`), skips cookie/CAPTCHA frames; custom dropdowns (`role=combobox` + bare helper box) become one `dropdown` field; invisible and `type=search` boxes ignored; capture embeds iframes as `srcdoc`; sanitizer no longer rewrites digits inside ids. Saved `fixtures/forms/indiecampers_greenhouse.html`. 109 tests pass.
- 2026-11-10: Phase 2 closed after codebase review (109 tests pass, tree clean, no personal data or hardcoded paths in code/fixtures). Browser launcher now uses installed Chrome with the automation flag off (your change); you still solve any bot check by hand.
- 2026-11-09: Ollama speed check done (about 20 s cold start, then quick). Phase 0 complete pending commit.
- 2026-11-10: Phase 3 prep: `sqlite-vec` 0.1.9 approved and pinned; `ai.embed()` added (the only place that calls the embedding model; deterministic mock vectors; `embed_model` setting); `tests/fixtures/eval_questions.sample.json` format added. 120 tests pass. Next: `engine/rag.py`.
- 2026-11-10: Phase 3 step 2: `engine/rag.py` (chunker with email/phone/ID scrubbing, answer chunks hold the question only, `sqlite-vec` cosine index, `retrieve(question, k, sources)`, index remembers its embedder and refuses a mismatched search) + `rag reindex`, `rag ask`, `rag eval` commands. 136 tests pass. Real data indexed in mock mode: 121 chunks, none contains email, phone, address or GPA. Next: re-index with real Ollama vectors (needs `run_mode` set to `dry_run` by you) and judge the top 5 per eval question.
- 2026-11-10: first real-vector eval was poor (right saved question first 7/11; every score 0.5-0.65). Fixes: (1) saved questions and incoming questions now both use nomic's symmetric `clustering:` prefix (facts keep `search_document`/`search_query`); index version bumped to v2; (2) new `also_asked_as` field in answers.json + `answer_aliases` table: 312 alternate wordings for all 95 questions, modelled on Greenhouse/Lever/Workday/LinkedIn/Indeed/JobStreet/EEO forms. Result: right saved question first 25/26. Scores shifted up, so `MATCH_THRESHOLD` recalibrated 0.7 -> 0.85. Caveat: the wordings were written after seeing the eval set, so the eval is now optimistic; a fresh held-out set is needed. Backup: `data/answers.backup-2026-11-10.json`.
- 2026-11-10: Step 1 timing check of `llama3.1:8b` as a match judge (no project code changed): CPU only, 5.6 GB RAM, about 5 s per question warm (much slower when RAM runs out), but only 3/6 right and inconsistent; it confused visa sponsorship with work authorization. AI judge on hold; next is an embedding-model comparison. Details under Phase 3 "Matching decisions".


---

## 2. Order of work at a glance

| # | Phase | Time | Ends with |
| --- | --- | --- | --- |
| 0 | Close out setup | 1–2 days | clean repo, matching docs, new AI tasks added |
| 1 | Profile, resumes, answer bank | ~1 week | your data in SQLite, `profile show` works |
| 2 | Form reader | 1–1.5 weeks | 3 saved forms read correctly offline |
| 3 | RAG + answer engine + resume picker | ~1.5 weeks | right source for every field of the 3 forms |
| 4 | Fill, review, controls page, real use | 1.5 weeks + 1 week use | **tag v0.1** |
| 5 (v1) | Batch mode | 3–4 weeks | 5 jobs filled, 3 approved and submitted |
| 6 (v2) | Cold email | 1–2 weeks | test email delivered, contacts with sources |
| 7 (v3) | Hands-off | 1–2 weeks | a week live at low cap → **tag v1.0** |

**Every session:** start prompt → plan (max 3 steps) → your OK → build → run checks → commit.

```text
Read CLAUDE.md and ROADMAP.md. Tell me which phase we're in and what's done, in 5
bullets. Propose a plan for THIS session only (max 3 steps). Wait for my OK.
```

---

## Phase 0: Close out setup (1–2 days)

**Goal:** a clean base: docs match the machine, the missing folders exist, and `ask_ai` knows the v0 tasks.

**You do**

- [x] Python version: 3.13 everywhere (docs updated).
- [x] Stray `.next/` deleted.
- [x] Ollama speed check: first call about 20 s (model loading), later calls quick. Idle models unload after about 5 min, so consider `keep_alive` or a warm-up call in Phase 4.
- [x] Old `jobpilot/` code removed (still in git history).

**Prompt Claude Code**

1. ~~Housekeeping prompt~~ — done.
2. ~~New AI tasks~~ — done (kept for reference):
   ```text
   Add two tasks to ask_ai: form_answer and resume_pick, each with a Pydantic model
   and a canned fixtures/ai/<task>.json. form_answer returns a list of
   {field, answer, confidence, source}; resume_pick returns {resume: "A"|"B", reason}.
   Tests for mock mode, including a test that a bad fixture raises AIError.
   ```

**Check**

```powershell
.venv\Scripts\activate
python -m pytest -q
python -c "from engine.ai import ask_ai; print(ask_ai('resume_pick', 'x'))"
git status
```

**Done when:** tests pass, both new tasks answer in mock mode, `git status` is clean after your commit, and Python versions match everywhere. (Everything is met except your commit.)

---

## Phase 1: Profile, resumes and answer bank (~1 week)

**Goal:** your details, both resumes and your answer bank are in SQLite and readable by code, with no secrets in output or git.

**You do** (the part that takes real thought, so start before the session)

- [x] Fill `data/profile.json` (the file exists but uses the old format; copy the new shape from `data/profile.example.json`) with your real details: name, email, phone, address, school, year level, graduation year, location, links (GitHub, LinkedIn, portfolio), job preferences, and a short blurb per project. `data/` is git-ignored, so it stays local.
- [x] Your 2 resume PDFs are in `data/resumes/` (`java dev.pdf`, `startup.pdf`; the file names don't matter). In `data/profile.json` list them under `resumes` with an `id` (A/B), a display `label` and the `file`. The resume picker ignores names and labels and judges by what each resume says. The employer sees a formal name like `Your Name.pdf`, set once as `upload_name`.
- [x] Write 20+ starter answers in `data/answers.json` (it exists with 6 fake examples; replace them. Format: `question`, `answer`, `location_scope`, `city`, `kind` = `fixed`, `open` or `protected`), because only you know them: expected salary (Metro Manila vs remote vs abroad), relocation, availability and start date, work authorization, notice period, why you want to work here (generic), strengths, GPA if asked, and so on. Give each a location scope (any / city / remote / abroad).
- [x] Mark each answer's `kind` in `answers.json` (done, simplified Nov 9): `fixed` (use as written), `open` (AI may rewrite it to fit the job, from your facts only), `protected` (AI never sees or changes it; legal, consent and personal answers). A forgotten tag only makes the bot more careful, never riskier.
- [x] Approve adding `pdfplumber` (reads resume text from the PDFs) and `keyring` (stores secrets in Windows Credential Manager). Just reply "yes"; Claude installs them and updates `requirements.txt`.

**Prompt Claude Code**

1. Explain-first: "Explain the tables for profile, resumes, answer bank, unknown questions, filled pages and the action log, and why answers need a location scope. Show the schema. Wait for my OK."
2. "Implement `engine/db.py` (connection, schema, `init_db`) and `engine/profile.py` (load `profile.json`, load both resumes, extract resume text). Tests use a fake profile and a tiny sample PDF."
3. "Implement the answer bank loader and exact-match lookup with scope fallback (a city answer beats `any` for that city). Add `engine/secrets.py` with get/set through keyring. CLI: `profile show`, `answers list`."
4. "Add `engine/safety.py` with `check()` (for now: run mode and an action log writer). No kill switch yet."

**Check**

```powershell
python -m pytest -q
python -m engine.cli profile show      # shows details, masks phone and address
python -m engine.cli answers list
git ls-files | Select-String "data/"   # only .gitkeep and *.example.json
```

Manual:
- [x] Open the DB in any SQLite viewer; confirm both resume texts look right (not garbled).
- [x] `profile show` output contains no raw phone or address.
- [x] Search the repo for your phone number and email. It should appear only in git-ignored `data/`.

**Status: code and data done Nov 9. Only your visual check in a SQLite viewer is left.**

**Done when:** profile, both resumes and 20+ answers load into SQLite, scoped lookup returns the right answer for "Makati" vs "remote", and tests pass with fake data only.

---

## Phase 2: Form reader (1–1.5 weeks)

**Goal:** for the page you opened, return every field's label, type, required flag and options, tested offline on saved HTML.

**You do**

- [x] Approve adding `playwright`, then run `playwright install chromium` (done Nov 9).
- [x] Pick your **3 target forms** and keep them stable for the whole project:
  1. A real Prosple application form (log in by hand in the bot browser).
  2. A Google Form. Make your own test one with text, long text, dropdown, radio, checkbox and file upload fields.
  3. A real company career-page application.
- [x] Log in to Prosple by hand in the bot's persistent browser profile (Claude builds the launcher; you type the password yourself, and the bot never sees or stores it).
- [x] Before committing any fixture HTML, **check it for your real data** (name, email, tokens, hidden fields) and have Claude sanitize it.
- [x] Read the Prosple terms of use about automation and keep to a human pace.

**Status: done Nov 10.** Known gaps carried forward: custom dropdown options are not read until opened (Phase 4), main-page extras are returned with the form (Phase 3 filters), and no Google Form was tested.

**Prompt Claude Code**

1. Explain-first: "How does Playwright find elements, why prefer role/label/text selectors, and how does a persistent browser profile keep me logged in? Don't code."
2. ~~"Create the bot browser launcher in `engine/forms/` (persistent profile in `data/browser_profile/`, headed). One command opens it so I can log in and navigate."~~ Done: `engine/forms/browser.py`.
3. "Write `engine/forms/reader.py` and a `FormField` Pydantic model. Read label (from label, aria-label, placeholder, nearby text), type, required, options. Wrap every read in `safety.check()` and log it."
4. "Add a command that saves the current page's HTML to `fixtures/forms/` and sanitizes personal data. Then write offline tests against the 3 saved forms."

**Check**

```powershell
python -m engine.cli browser open          # log in, navigate to a form
python -m engine.cli forms read            # prints the field list of the current page
python -m pytest -q                        # reader tests use saved HTML only
```

Manual: compare the printed field list with what you see on screen for each of the 3 forms.

**Done when:** the reader returns every visible field with the right type and options on all 3 saved forms, tests pass with no network access, and no fixture contains your personal data.

---

## Phase 3: RAG + answer engine + resume picker (~1.5 weeks)

**Goal:** each field gets answered by the correct source, and the correct resume is picked.

**You do**

- [x] Write a **test set** of 20 questions in `tests/fixtures/eval_questions.json`: for each, the question as a form would word it and which saved answer or source should answer it. Include 8 reworded versions of your saved questions, 4 legal/eligibility, 4 personal fields, and 4 brand-new open questions ("Why do you want to join us?"). This is how you'll judge quality. (Done: 45 questions.)
- [ ] Write about 10 **held-out** questions without looking at `also_asked_as`, so the eval measures understanding, not memorised wordings.
- [ ] Write project descriptions that are specific and true (technologies, what you built). The AI may only use these.
- [ ] Collect 5 real job posts as text files and write down which resume you would send for each, to test the resume picker. Resume content decides, so make sure each resume's text really shows the skills you want it chosen for.
- [ ] Judge retrieval output yourself in step 2. If the wrong chunk comes first, say so, because only you know what's correct.
- [x] Decide the confidence cutoff for "flagged" (started at 0.7; now 0.85 after the prefix change, see "Matching decisions" below).
- [x] Approve adding `sqlite-vec` (approved and installed Nov 10, 2026).

**Prompt Claude Code**

1. Teach-first: "Teach me RAG with 5 sentences: embed them with Ollama, ask a question, show the similarity scores."
2. "Implement `engine/rag.py`: chunking (profile, resumes, projects, answers), embeddings with `nomic-embed-text`, sqlite-vec storage, `retrieve(question, k=5)`, a re-index command. Show the top 5 chunks for each question in my eval set."
3. "Write `engine/forms/answers.py` with the rule order: by each answer's kind: protected → used exactly as saved, never sent to the AI, highlighted for review (and questions containing sensitive words are treated as protected even with no saved match); fixed → bank via RAG with scope, used as written; open and new non-sensitive questions → Ollama rewrites from retrieved facts only, flagged. Also add elaboration: a short saved \"Yes\" in a free-text box becomes \"Yes\" plus 1–2 sentences of real reasons from my answers, projects and resumes, flagged; radios and dropdowns get the plain answer; protected is never expanded. Add `prompts/form.md`. Mock-mode tests for each rule."
4. "Add the resume picker (job post + the most similar chunks of each resume → A or B with evidence, never by file name) and the test that **no prompt ever contains phone, address, email or ID numbers**."
5. "Run the answer engine against the 3 form fixtures with real Ollama in `dry_run` and print a table: field, answer, source, confidence."

**Matching decisions (Nov 10, 2026)**: how a form question finds its saved answer. Kept here so we don't re-argue them.

| Decision | Why |
| --- | --- |
| Saved questions and form questions are both embedded with nomic's `clustering:` prefix; facts keep `search_document:`/`search_query:` | Same-kind comparison. Eval: right question first went from 7/11 to 10/11 before any other change |
| `also_asked_as` alternate wordings in `answers.json` (312 written from real ATS forms) | Gives retrieval more ways in. Right question first: 25/26. Not a long-term fix for synonyms on its own |
| `MATCH_THRESHOLD` = 0.85 (was 0.7) | The new prefix lifts all scores; 0.7 accepted everything |
| Below the cutoff: NO MATCH → unknown questions list; may still be filled, flagged **not recommended**, any kind (including protected) | Your rule |
| Approved design for an AI check: personal fields by code first; skip the AI only at score ≥ 0.95 and ≥ 0.05 ahead of #2; protected answers need the AI to agree **and** score ≥ 0.80; fallback to the cutoff if the AI fails | Your choices, Nov 10 |

**Step 1 result: `llama3.1:8b` as a "same question?" judge (Nov 10)**. Tested on 6 hard questions (start/begin, hybrid, feedback, visa, address, industry):

- **Speed:** 100% CPU (the Radeon iGPU isn't used), 5.6 GB RAM. Cold start 23–55 s; warm about 5 s per question when RAM is free, 15–45 s when Windows runs short of RAM (free RAM fell to 0.7 GB with other apps open).
- **Quality: not good enough.** With a loose prompt it picked related-but-wrong questions, including "Will you need visa sponsorship?" → "Are you legally authorized to work?" (dangerous for a protected answer). With a strict prompt (temperature 0, JSON schema) it answered "none" to everything, missing begin = start and the hybrid question: 3/6, and the 3 "right" answers were all "none". Answers also changed between runs.
- **Decision:** don't build the AI judge on `llama3.1:8b` for now. Next, test a stronger **embedding** model (light on RAM, fast). Keep `llama3.1:8b` for its planned job, drafting open answers. Personal-field detection by code (step 2 of the plan) goes ahead regardless.

**Check**

```powershell
python -m engine.cli rag reindex
python -m engine.cli rag ask "When can you start?"
python -m engine.cli forms answer --fixture fixtures/forms/google_form.html
python -m pytest -q
```

Manual:
- [ ] Review the table for all 3 forms. Every field has the right source label.
- [ ] No legal or eligibility field was answered by AI.
- [ ] At least 7 of the 8 reworded questions found the right saved answer.
- [ ] Resume picker chose correctly on all 5 sample posts (4 of 5 is acceptable; investigate the miss).
- [ ] No invented facts in drafted answers (read every one).

**Done when:** the eval set passes (reworded questions 7/8, legal 4/4 not AI-answered, personal 4/4 by code), the picker is right on 4+ of 5 posts, the privacy test passes, and you can explain how a field gets its answer.

---

## Phase 4: Fill, review, controls page and real use (1.5 weeks, then 1 week of use)

**Goal:** press **Fill this page** and the form is filled, the resume uploaded and guesses highlighted. It stops, and you submit. The history shows what you filled, and passive detection offers to mark submitted.

**You do**

- [ ] Approve adding `fastapi` and `uvicorn`.
- [ ] Test on your own Google Form first, then Prosple, then a career page, always in `dry_run`. **You** click Submit.
- [ ] Look at the controls page next to the design mockups (`Questions.html`, `Applications.html`, `Components.html`) and tell Claude what differs. CLAUDE.md requires a side-by-side comparison, so don't skip it.
- [ ] Use it for **a week of real applications**. Keep `notes/v0-misses.md`: for every wrong, missing or awkward fill, write the page URL, the field and what went wrong.
- [ ] Review the screenshot of every filled page before you submit.
- [ ] Write the README with Claude. Check that it matches reality.

**Prompt Claude Code**

1. Explain-first: "Explain how the filler handles each field type, how we highlight guesses, and how passive submit detection works without ever clicking."
2. "Implement `engine/forms/filler.py`: fill text, select, radio, checkbox, date; upload the resume; 1–4 s random delays; `safety.check()` and logging before each action. **Add a test that fails if any code path clicks a Submit or Apply button.** Test on saved HTML."
3. "Save a `fills` row (URL, job and company, resume, flagged count, screenshot path, status `filled`) and an unknown-questions row for each unanswered question."
4. "Add `engine/api.py` (FastAPI on 127.0.0.1 only): fill, unknown questions, answers CRUD, filled pages, mark status."
5. "Build the controls page in the existing dashboard: Fill this page, Unknown questions, Answer bank editor, Filled pages history. Reuse the existing components. Compare with the mockups afterwards and list the differences."
6. "Passive detection: after a fill, watch the page read-only for a confirmation (thank-you text, URL change) and offer 'Looks submitted. Mark it?'. Never clicks, never marks without confirmation."
7. After the week: "Here are my notes from `notes/v0-misses.md`. Group them by cause and propose fixes, smallest first."

**Check**

```powershell
python -m engine.api
cd dashboard; npm run dev
python -m pytest -q
```

Manual checklist (do all three sites):
- [ ] Press Fill this page: fields fill, resume uploads, flagged answers are highlighted.
- [ ] The Submit button was **not** clicked, and the form is still open.
- [ ] A new row appears in Filled pages history with a screenshot.
- [ ] A question you've never answered lands in Unknown questions. Answer it, re-fill, and see it filled.
- [ ] Submit by hand. Passive detection offers to mark it. Confirm, and the status turns `submitted`.
- [ ] Press **Abandoned** on a row you didn't send.
- [ ] Mock mode: the same flow works on saved HTML with no network.

**Done when:** it correctly fills Prosple's form, one Google Form and one company career page; the Submit-never-clicked test passes; the history matches what you actually submitted after a week of real use; the README is written; and `v0.1` is tagged. Update "Current stage" in CLAUDE.md.

---

## Phase 5 (v1): Batch mode (3–4 weeks)

Do not start until v0.1 has been used for a week. Split into sub-phases:

| Sub-phase | What | Check |
| --- | --- | --- |
| 5a | Write `engine/matcher.py` (optionally reuse the old BM25 code from git history, commit `d12ff77`); Prosple discovery with filters and duplicate fingerprints, on saved Prosple pages first | scraper tests on `fixtures/prosple/`; no duplicate fingerprints |
| 5b | BM25 pre-filter + Ollama match score `{score, reasons, missing_skills, resume}` | the top 10 scored jobs look right to you; low scorers skipped before any AI call |
| 5c | Background filling with the v0 filler and a screenshot per application, queued as `queued` | a dry run fills 5 jobs; none submitted |
| 5d | Review batch screen (approve/reject, edit answers, switch resume) | you can approve 3 and reject 2 |
| 5e | Submit approved with a confirmation check; never resubmit; failures marked `failed` | 3 real submits show confirmations |
| 5f | Full Applications tracker (extends the history), Needs manual apply tab, Home screen, kill switch, daily cap | kill switch stops mid-form within a second |

**You do:** set your filters (roles, locations, max age), read Prosple's terms again, choose the daily cap (start at 5), approve each batch yourself, and check every submit.

**Prompt pattern per sub-phase:** explain, plan, build in mock mode with tests, `dry_run`, then (5e only) a live test on 3 jobs you'd happily apply to. Never switch to `live` in code; only you do, from the dashboard.

**Done when:** a dry run fills 5 discovered jobs correctly, you approve 3, they submit for real, and the tracker shows their confirmations. Tag `v0.5`.

---

## Phase 6 (v2): Cold email (1–2 weeks)

**You do**

- [ ] Create the Google Cloud project, the OAuth consent screen (add yourself as a test user) and a Desktop OAuth client. Claude tells you what to click; you do the clicking.
- [ ] Sign up for a search API and Hunter, and check each one's current free limits.
- [ ] Authorise Gmail once in the browser (scope `gmail.send` only).
- [ ] Review every email, and every contact's source link, for the first 2 weeks.
- [ ] Choose the daily email cap (start at about 10 or less).

**Prompt Claude Code**

1. "Explain OAuth 2.0 for Gmail (client ID, consent screen, scope, access and refresh tokens) and walk me through the setup step by step."
2. "Write `engine/mailer.py`: `gmail.send` only, token in keyring, verified addresses only, daily cap, 2–5 minute spacing, plain text. Never send in mock or `dry_run`. Send exactly one test email to myself."
3. "Write `engine/contacts.py`: search → names and titles → Hunter finder → verifier. Save the source URL. Count every API call against quota. Tests use saved responses only."
4. "Email writer using only my real projects, returning `facts_used`; personal tier for top matches, short tier for the rest."
5. "Emails screen (Queued / Sent / Failed, Regenerate), blocklist checked before every send, bounce handling."

**Check:** the test email reaches your inbox; 3 real contacts are found with source links; a full dry run creates emails in the review queue; an unverified address is never emailed (test).

**Done when:** all four checks pass and you've reviewed at least 5 drafts, each with correct facts. Tag `v0.8`.

---

## Phase 7 (v3): Hands-off (1–2 weeks)

**You do**

- [ ] Set your active hours and class-time pauses.
- [ ] Back up the encryption key note: if you lose the keyring entry, encrypted fields can't be read. Keep a note of how to re-enter your details.
- [ ] Run a **full week in dry run**, then a week live at 5 a day, checking every submit and email.
- [ ] Record real numbers (applications, replies) for the README.
- [ ] Decide whether to turn on the Gemini fallback (read its current free-tier terms first; it may use prompts for training).

**Prompt Claude Code**

1. "List every place that can navigate, fill, submit or send, and confirm each calls `safety.check()` and logs to `action_log`. Show gaps before fixing."
2. "Scheduler (active days and hours, pauses, Run once now), CAPTCHA/logout detection with pause and Resume, Windows alerts."
3. "Fernet encryption for phone, address, email and contact emails with the key in keyring, plus a one-time migration. Prove with a test that the DB file doesn't contain my phone number in plain text."
4. "Per-task AI provider setting with Gemini → Ollama fallback and quota counters."
5. "Settings, Profile, Activity log, onboarding, empty and error states from the mockups, then a design QA pass listing every difference."
6. "Update the README with my real numbers."

**Check**

```powershell
python -m engine.cli run --mode dry_run
python -m engine.cli stats --week
python -m pytest -q
```

Manual: kill switch stops everything; a CAPTCHA pauses the site and alerts you; encrypted values show in the DB viewer.

**Done when:** a week live at a low cap goes smoothly, personal fields are encrypted, the provider switch and fallback work, and the README shows real numbers. Tag `v1.0`.

---

## Rules that hold in every phase

- One phase at a time, one step per session, commit after each working step.
- Every feature works in `mock` mode with a test before `dry_run`. You alone switch to `live`.
- No new dependency without your OK and a reason.
- Never put real personal data, keys or tokens in code, fixtures, tests, logs or git.
- Explain it out loud in 2 minutes before moving on. If you can't, you're not done.
