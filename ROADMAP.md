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
| Tests | 966 pass (all audit bugs fixed; the settings-file test fails only while your local settings.json says dry_run) | `test_ai.py` (ai + settings, including the new v0 tasks). The old-plan matcher tests were removed |
| Ollama | Ready | `llama3.1:8b` and `nomic-embed-text` pulled |
| `engine/db.py`, `profile.py`, `secrets.py`, `safety.py`, `cli.py` | Done (Phase 1) | Real data loads into `data/jobpilot.db` |
| `engine/forms/browser.py` | Done (Phase 2 step 1) | Launcher; you have not tried it yet |
| `engine/forms/reader.py`, `capture.py` | Done (Phase 2) | Reader + capture; 1 real form saved, 2 more wanted (Google Form, Prosple) |
| `engine/rag.py` | Built (Phase 3 step 2) | Chunks, `sqlite-vec` index, `retrieve()`, `rag reindex/ask/eval`; tuned on real `nomic-embed-text` vectors (same `clustering:` prefix both sides, `also_asked_as` wordings, cutoff 0.85). Matching frozen at good enough |
| `engine/learning.py` | Built (Phase 3 step 3b) | Unknown questions list (counted, not duplicated) and suggested wordings: a matched question in new words waits for your approval, then goes into `answers.json` `also_asked_as` (backup first; protected needs `--yes-protected`). CLI: `questions list/approve/reject`. Not yet called by the answer engine |
| `engine/forms/answers.py` | Built (Phase 3 steps 3 and 5), elaboration partly | Personal-field detector: name parts, email, phone (format from one stored number), address, city, country, links; by code, never AI. Sensitive-question detector `is_sensitive()` added (Nov 14: legal/eligibility/identity words, never AI). `FieldAnswer`, `answer_field()` and `answer_form()` (Nov 14): personal by code, protected exact + flagged, fixed as written, sensitive with weak match = closest saved, NOT RECOMMENDED, calls `learning.triage_question()` for every non-personal field; the AI is never called on these paths. Step 3 (Nov 14): new non-sensitive text-box questions get a flagged Ollama draft, matched `open` answers a flagged rewrite, via `engine/forms/drafting.py` + `prompts/form.md`; every reply is checked in code (field, length, no email/phone, first person, source, numbers and names must be in the facts). Reflective and story questions (strengths, how you decide, what drives you, tell me about a time...) use the `WRITE` prompt and the `reflect_text` task: the best 1-2 projects are chosen from ALL of them by scoring every detail of every project against the question, and the model writes ONE free first-person answer from those notes (impact, what you did, a reflection; or a direct answer, one or two moments, a reflection). It may reword your notes and add a reflective sentence but no new fact. Hard blocks (answer rejected): private data, a number or name not in your notes, assistant talk, empty reply. Everything else (stock phrases, praise, inflated words, technology lists, repeated openers, length) is only a warning in the note. Company questions ("Why do you want to work here?") are answered from the job post (Nov 22): `drafting.build_company_brief()` copies notes about the company and role out of the post (`BRIEF` prompt, `company_brief` task) and code drops every note the post does not back up; `drafting.company_answer()` (`COMPANY` prompt) writes the answer from that brief + your notes, or adapts your saved answer; a post that says nothing about the company gives a role-focused answer; claims like "I heard..." and invented names or numbers are rejected. The brief is built once per form. `forms answer --fixture` command built (Nov 18, preview only, `--record` saves). Relocation questions: yes/no decided from the job location by code, AI only words it (`jobpost.py`, `ELABORATE`). Privacy test for the answer engine built. General elaboration built (Nov 19): a `fixed` saved answer of 3 words or fewer starting with yes/no, in a text box, gets 1-2 flagged sentences from your notes (`drafting.elaborate_short`, `ELABORATE_SHORT`); radios, protected, sensitive and long answers untouched; any doubt falls back to the plain saved answer |
| `engine/forms/jobfinder.py` | Built (Phase 4, job post finder) | Form page → opener tab → same-site tab → asks you; read-only, keyword check (not AI), skips LinkedIn; reads the opener from Chrome's own record (Playwright's `opener()` is unreliable when attaching to the running bot browser); rejects search-result lists (repeated-line share); pasted text or a chosen tab replaces the post (Change); no post = `None`, so no resume upload. Not wired into a fill yet (orchestrator comes after the filler). 23 tests |
| `engine/forms/orchestrator.py`, `history.py` | Built (Phase 4 step 4.3) | `fill_current_page()`: safety check, read fields (none = stop), job post (your `--post`, else the finder), scrub your details from the post, pick resume (no post = no pick, no upload), `answer_form`, `fill_page`, screenshot, `fills` row + linked `action_log` rows. `python -m engine.cli forms fill [--tab] [--post] [--resume] [--mode mock|dry_run] [--fixture]`. 13 tests. Not tried on a real page yet |
| `engine/forms/filler.py` | Built (Phase 4 step 4.1) | `fill_page()` + `FillReport`; text, select, radio, checkbox, date, resume upload under `upload_name`; safety check + one log row per field; amber flags in the page (solid = guess, dashed = needs you); custom dropdowns left to you; checks each element is the expected kind (and name) before touching it; **never clicks a button** (recorder test on 4 saved pages). CLI `forms fill [--resume A|B] [--post FILE] [--fixture NAME] [--fast]`. 40 tests\|B] [--post FILE] [--fixture NAME] [--fast]`. 38 tests |
| `engine/api.py`, `api_write.py`, `api_fill.py`, `api_browser.py`, `api_deps.py`, `api_models.py` | Done (Phase 4 steps 4.4b-e, 4.5 step 1) | Guards, reads, writes (backup, re-index, protected confirmation) and the fill job (`POST /fill`, `GET /fill/{id}`). Tried on saved data and tests only; not yet on a real page. The dashboard still shows mock data (4.5). 4.5 step 1: read-only `GET /status`, `GET /jobpost` (preview + tabs), `GET /fills/{id}/screenshot` (PNG inside `data/screenshots/` only); fill choices `post_tab_url` and `no_resume` |
| `engine/forms/`, `fixtures/forms/`, `prompts/` | Created (empty) | Filled from Phase 2 |
| `requirements.txt` | Incomplete | Has `ollama`, `pydantic`, `pytest`. Playwright, FastAPI, uvicorn, pdfplumber, keyring, sqlite-vec still to add, one at a time with your OK |
| Dashboard (`dashboard/`) | v0 controls page built (stage 4.5) | Fill this page, Questions (Waiting, Wordings, Answered), Answer bank, Filled pages, all on live engine data through `lib/api.ts` (never the database). v0 shell (mode badge, engine status, sidebar counts). The v1 mock screens are in the `(v1)` group (`/home`, `/review`, `/applications`), out of the menu. Not tried on a real job site yet |

**Housekeeping (done Nov 9, 2026)**

1. Python: the machine and venv run 3.13.2, so CLAUDE.md and SPEC.md now say 3.13.
2. Old-plan code removed: the `jobpilot/` package (`bm25.py`, `matcher.py`, `cli.py`), `tests/test_matcher.py` and `data/sample_jobs.json`. The code is still in git history (`git show d12ff77:jobpilot/matcher.py`) if you want it for v1. `sample_jobs.json` was git-ignored, so it is gone for good (fake sample data).
3. Stray root `.next/` build folder deleted.
4. `ask_ai` comment fixed: the form tasks arrive in v0.
5. Created `engine/forms/` (with `__init__.py`), `fixtures/forms/`, `prompts/`, and `.gitkeep` files so empty folders stay in git.
6. `.gitignore` now allows `data/*.example.json`, so `profile.example.json` can be committed (it was being ignored by `data/*`).
7. The dashboard is untouched. Home, Applications and Review are v1 screens built early. Phase 4 adds the controls page beside them and reuses the existing components.

**Still open in Phase 0:** nothing except your commit.

**Current position:** v0, Phase 2 done (3 forms: Angkas/Workable, Indie Campers/Greenhouse iframe, a synthetic one; Google Form skipped by choice). Phase 3 done. `rag.py` is built and tuned (right saved question first 25/26 on the eval). The `llama3.1:8b` match judge was tested and put on hold (too unreliable on this PC). `mxbai-embed-large` was compared and lost to the current `nomic-embed-text` (6/6 vs 4-5/6 on held-out questions). Matching frozen at good enough (Nov 11). The personal-field detector is built. **You:** add `first_name`, `middle_name`, `last_name` to `data/profile.json`. Unknown-questions list and approved-wording learning are built (`engine/learning.py`). `answer_field()` is built and calls `learning.triage_question()` for every non-personal field. `prompts/form.md` and the Ollama draft/rewrite paths are built (step 3). The `forms answer --fixture` command (step 5), the prompt-privacy test and relocation elaboration are built, and the 5 job posts are collected (Nov 18). The resume picker is built (Nov 19): `pick_resume(conn, job_text, settings)` in `engine/matcher.py`, CLI `python -m engine.cli resume pick --post <file>`, prompt in `prompts/resume.md`. **Phase 3 is done (Nov 19):** you judged the retrieval output, the 3 form tables, the drafted answers and the picker yourself and accepted them. Note for the record: the picker scored 3/5 on the sample posts (gate was 4/5); you accepted it, and evidence lines sometimes echo the job post. Revisit if the picker misses on real applications. **Now: Phase 4.** Finding the job post text across browser tabs is a Phase 4 step (decided Nov 12). **Phase 4 step 4.1 is built (Nov 20): the filler.** `fill_page()` in `engine/forms/filler.py` fills text/select/radio/checkbox/date, uploads the resume under `upload_name`, pauses 1-4 s, outlines guesses (solid) and needs-you fields (dashed) with a tag in the page, and never clicks anything but fields; `python -m engine.cli forms fill` runs reader → answers → filler. Next: wire the job post finder, the `fills` row and the unknown-questions save into one "Fill this page" action (4.3), then the on-page panel and API. **Now (Nov 25): audit fixes** (see the checklist under Phase 4). Step 0 and Bug 1 done; Bug 2 next, then 2b, 3, 4, one commit each. **Stage 4.5 (the controls page) is built (Nov 26). v0 is NOT finished yet.** Left in Phase 4: (1) Claude: passive submit detection (no code yet), and `times_used` counting if you want it; (2) you: look at the side-by-side, test Google Form / Prosple / a career page in `dry_run`, a week of real applications with `notes/v0-misses.md`, check the README, then tag `v0.1` and move CLAUDE.md to v1.

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
- 2026-11-10: `mxbai-embed-large` pulled (669 MB) and compared with `nomic-embed-text` on your 10 held-out questions: nomic 6/6 right first, mxbai 4-5/6 and slower. Keeping nomic; no code changed. Next: personal-field detector by code, then `engine/forms/answers.py`.
- 2026-11-11: decisions: matching frozen at good enough; protected answers on a weak match are filled and flagged for review (kept). Coverage check on the 2 saved real forms: general questions covered; you added 6 internship questions (OJT hours, academic internship, MOA, own laptop, headline, duration). Fixed `answers.json` (the 6 were pasted as one nested list; backup `data/answers.backup-2026-11-11.json`).
- 2026-11-11: personal-field detector. Step A: `profile.json` takes `first_name`, `middle_name`, `last_name` (full name built from them; old `name` still loads), new DB columns added to existing databases by `init_db`. Step B: reader captures `autocomplete`, `placeholder`, `max_length`, `pattern`. Step C: `engine/forms/answers.py` with `detect_personal` (autocomplete → type → name attribute → short label; skips long questions and other people's details), `format_phone` (one stored number → +63 / 09 / bare from the field's hints), dropdown option matching, blank + flagged when a value is missing. Both real forms read correctly (Address no longer mistaken for Email). 215 tests pass.
- 2026-11-11: learning rules. New `engine/learning.py`: questions below the cutoff go to `unknown_questions` (same question seen again only raises `times_seen`); a matched question in new words is queued in `suggested_wordings` and only written into `answers.json` after `questions approve` (timestamped backup, atomic write, `load` keeps it). Protected answers need `--yes-protected`; rejected wordings never return. New CLI `questions list/approve/reject`. DB: new table and 2 columns, old databases upgraded by `init_db`. 18 new tests (233 pass). Also fixed: nested eval file, venv hint, run instructions in `cli.py`, Chrome launch for Cloudflare.
- 2026-11-11: portfolio facts for form answers. Scraped markjenelcortas-portfolio.vercel.app with headless Playwright (raw text in git-ignored `data/portfolio_scrape.json`). `Project` now takes optional `status`, `result`, `problem`, `solution`, `hardest_part`; `rag.build_chunks` makes an overview chunk and a separate `(story)` chunk per project (10 project chunks for 5 projects). `profile.json` gained EconLens, richer text for the other 4 and 7 skills (backup: `data/profile.backup-2026-11-11.json`). Real-vector check on a temp DB: challenge, WebSocket and Spring Boot questions find the right story chunks; "led a team" does not rank Pag-IBIG first (the AI sees the top few chunks anyway). 3 new tests (236 pass).
- 2026-11-11: first `README.md` written (how it works, safety, honest limits, status). It describes the filler as not built yet; re-check and update it after Phase 4, which is when the README checkbox gets ticked.
- 2026-11-12: decision: the job post is often in another tab, so a **job post finder** goes into Phase 4 (form page → opener tab → same-site tab → ask you; shows what it used with Change; no job post = no resume upload). The Phase 3 resume picker takes job post text as input. SPEC.md (features, flow, edge cases, controls page, Phase 3/4 checklists) and this roadmap updated. No code changed.
- 2026-11-13: decision: an **on-page Fill button** (floating panel injected by Playwright into the bot's browser, wired to the engine with `expose_binding`) is added to Phase 4 next to the dashboard button; a mockup comes first. A Chrome extension for your everyday Chrome goes to SPEC "Later (optional)" (needs a JS rewrite of reader/filler, a token for the localhost API, and breaks the own-profile decision). SPEC.md and this roadmap updated. No code changed.
- 2026-11-13: SPEC Part 2 gained "How v0 works day to day" (two windows, what Fill does, start-up) and 8 "v0 scenarios"; Part 1 edge cases gained Google sign-in (sign in once by hand; workaround if Google blocks it). Phase 4 gained a Google sign-in test step. Open for later: whether the job post finder may read a LinkedIn tab (rule 9). No code changed.
- 2026-11-14: decisions for the answer engine: sensitive questions never go to Ollama (your saved text word for word, or empty); strong-match `fixed` answers are not flagged; elaboration only for a saved answer of 3 words or fewer starting with yes/no in a free-text box; Google Form fixture skipped. Built `is_sensitive()` in `answers.py` with `tests/test_sensitive.py`. 274 tests pass. Next: `FieldAnswer` and `answer_field()` (personal, protected, fixed, sensitive no-match).
- 2026-11-14: answer engine step 2: `FieldAnswer`, `answer_field()`, `answer_form()` for the paths that never use the AI; `tests/test_answer_engine.py` (17 tests, includes a guard that fails if the AI is called). 291 tests pass. Next: `prompts/form.md` + draft/rewrite via Ollama.
- 2026-11-14: answer engine step 3: `prompts/form.md` (DRAFT, REWRITE), `engine/forms/drafting.py` with 7 layers of guardrails, `answers.py` wired (draft = source `draft`, always flagged; rewrite falls back to saved text; AI only in text boxes; never for sensitive, fixed or protected). Ollama now runs at temperature 0. `tests/test_drafting.py`; each guard checked by breaking it on purpose. 324 tests pass. Next: elaboration.
- 2026-11-14: reflective answers (your feedback: too objective). `is_reflective()`, `is_company_question()`, `drafting.reflect_answer()`, `REFLECT` prompt, best 3 of all projects chosen per question, `num_ctx` 4096 for Ollama; opinions allowed, new facts not; humble voice enforced; company questions wait for the job post (Phase 4: use the job post in `REFLECT` for them). `tests/test_reflective.py`; guards checked by breaking them. Note: the settings-file test fails while `settings.json` is `dry_run`; set it back to `mock` before committing. Next: try it with real Ollama, then elaboration.
- 2026-11-14: reflective answers, round 2 (your feedback: at most 2 projects, facts short, a reflective ending). Best 2 projects (was 3), shape stance + 2 short examples + closing, new `reflect_answer` task with `pattern`/`stance`/`examples`/`closing` fields (`ReflectAnswer` in `ai.py`, mock fixture `fixtures/ai/reflect_answer.json`). Found with real Ollama: the model copied the worked example from the prompt word for word, so the example was removed and a 7-word copy guard added; it also wrote resume bullets, so projects are now shown to it as only `What started it` + `What was hard`. Closing praise words rejected. 384 tests pass (the settings-file test fails only while `settings.json` is `dry_run`).
- 2026-11-14: open questions, round 3 ("Why do you like software engineering?" came back as a skills list). Cause: it was not on the reflective list, so it took the strict fact-only prompt. Fix: much wider `is_reflective()` (why/how/what do you..., goals, good fit, anything else), new `is_story()` + `wants_opinion()` (story questions send only the best 1 project), preferences/target roles added to the reflective facts, extra examples are cut instead of rejecting the answer, the strict prompt now says not to answer with a list of technologies, and a phrase in the prompt that was echoed into every closing was removed. 407 tests pass (settings-file test fails only while `settings.json` is `dry_run`).
- 2026-11-15: open answers, round 4 (your feedback: repeated "I think", too short, more of your own data). Voice: confident first person; leading "I think/I believe" is removed from every sentence in code; 3+ sentences opening the same way are rejected; internal fact labels must not leak. Depth: the box size sets the sentence budget (up to 8 for a big box); over-long replies are cut to the box instead of rejected; the length cap only applies when the form states a limit. Data: new optional project fields (`why_i_built_it`, `my_part`, `key_decision`, `what_i_learned`, `would_change`, `proud_of`) and `about_me` (why software engineering, how I choose/work, strengths with evidence, goals, values, `voice_notes`) in `profile.json`; stored in a new `profile.about_me` column; indexed (INDEX_VERSION 3, run `rag reindex`); `data/profile.new-fields.template.json` is the fill-in template. Colon examples ("Project: I...") are rewritten as "With Project, I...". 440 tests pass (settings-file test fails only while `settings.json` is `dry_run`). Next: you fill the template, then elaboration (step 4) and `forms answer --fixture` (step 5).
- 2026-11-15: reflective answers, round 5 (your feedback: the guardrails made the local AI refuse or just copy your data; you wanted it to rephrase your facts in first person, reflectively). Replaced the 4-part `reflect_answer` task (pattern/stance/examples/closing, retries, own-words fallback, sentence dropping) with ONE free answer: `reflect_text` task, `WRITE` prompt section, two shapes (XYZ-style impact then what I did then a reflection for story questions; direct answer, one or two real moments, reflection for questions about you). Soft rules became warnings in the note (`Warnings: ...`); hard blocks kept as you chose. New project fields `how_i_got_through_it`, `mistake_and_fix`, `teamwork`, `timeline` and optional `short_name` (default: the part before the comma, at most 3 words), so answers never use the full project title. Every detail of every project is its own search chunk (INDEX_VERSION 4, run `rag reindex`); a project ranks by its best detail plus 0.3 of its second best, and among close matches the richer detail wins. Notes now show `Built with:` so a reflection may name a tool you really used and no other. Each guard checked by breaking it. 450 tests pass (settings-file test fails only while `settings.json` is `dry_run`).
- 2026-11-18: `python -m engine.cli forms answer --fixture <file>` (path or name in `fixtures/forms/`): reads a saved page with `reader.read_fixture` and prints field / answer / source / confidence / flagged. It is a **preview**: nothing is saved unless you add `--record` (`record` flag threaded through `answer_form` → `answer_field` → `learning.triage_question`; the library default stays `True`, so the Phase 4 filler records). **File fields** now get their own path (`answers.file_answer`) before any lookup: resume/CV → new source `resume` (value empty; flagged until a job post exists), bare "Attach"/"Upload" → flagged resume guess, cover letter/photo/other → needs you. They never reach the answer bank or the unknown questions list (fixes "Resume" matching "Yes, PDF format"). Cleaned the stray `Photo`/`Attach` unknowns and the `Resume` wording. `tests/test_file_fields.py` (21 tests). **Phase 4 contract:** the filler uploads the file the resume picker chose whenever `source == "resume"`. Suite: 512 pass; fails: the settings-file test (`settings.json` is `dry_run`) and 2 in the new `tests/test_prompt_privacy.py` (a `200000` from the Angkas form text is flagged as a long number).
- 2026-11-18: open answers, round 6 (your feedback: "what can you contribute / what is unique about you" retold one project, and answers on the same form sounded alike). Questions about YOU (not story questions) now put your `about_me` lines first (up to 6, instead of 3) and the projects last; the shape says to answer from how you work, with a project only as one clause of evidence. `answer_form` passes the long open answers already written on the page (`earlier`) into the `WRITE` prompt (new `OTHER ANSWERS ALREADY ON THIS FORM` block), and a repeat (6 shared words in a row, or the same project as another answer) is only a warning in the note, never a rejection. 456 tests pass (settings-file test fails only while `settings.json` is `dry_run`).
- 2026-11-18: relocation answers, pulled forward from Phase 4 by your decision. New `engine/forms/jobpost.py`: plain keyword matching (no AI) finds where the job is from the job post text, or from scope/city: Metro Manila place -> commutable, remote wording -> remote, anything else or nothing found -> unknown. Stance by code: commutable or remote = YES (no move needed), everything else = NO, always flagged. `answer_field` / `answer_form` take `job_text` (None = no post given, saved answers work as before). New `ELABORATE` prompt gets only the stance, the reason and your `preferences` + `about_me`; the AI may not flip the stance, add a place or number, or include private data, otherwise a plain sentence is used. Radios and dropdowns get plain Yes/No. `ask_engine.py --job / --job-file` to try it. `tests/test_relocation.py`; 488 tests pass (settings-file test fails only while `settings.json` is `dry_run`). Next: add 'Mandaluyong' to `preferences`, reindex; Phase 4 passes the real page text as `job_text`.
- 2026-11-18: roadmap brought up to date (Phase 3 audit). Done: `forms answer` command, prompt-privacy test for the answer engine (`tests/test_prompt_privacy.py`), 5 real job posts + `expected_resume.json` in `data/job_posts/`, relocation elaboration. **Still open in Phase 3:** the resume picker (`engine/matcher.py` is an empty stub, no `pick_resume`; the picker privacy test is skipped until it exists), general elaboration (a short saved yes/no in a free-text box; only relocation has `ELABORATE`), and your manual checks (dry-run table review, `rag eval` targets, picker 4/5). 515 tests pass, 1 skipped. CLAUDE.md stays on Phase 3.
- 2026-11-19: resume picker built. `pick_resume` retrieves the 3 closest chunks of each resume (`rag.retrieve`, sources=resume), sends the scrubbed post + chunks labelled only "Resume A/B" to `ask_ai("resume_pick")`, returns `ResumePick` (resume, reason, evidence). Empty post = no pick, no AI call. CLI `resume pick --post`. `tests/test_matcher.py` (incl. swapped file names change nothing) and the picker privacy test now run. 525 tests pass. Not yet tried on the 5 real posts with Ollama.
- 2026-11-19: general elaboration. `wants_elaboration()` + `_elaborated_answer()` in `answers.py`; `drafting.elaborate_short()` (stance must match the saved yes/no, no new number/name/private data, notes must score >= 0.6 `ELABORATE_MIN_SCORE`, search or AI failure = plain saved answer, unflagged); new `ELABORATE_SHORT` prompt. `tests/test_elaboration.py` (28 tests); two guards checked by breaking them. 553 tests pass (settings-file test fails only while `settings.json` is `dry_run`). Untested with real Ollama; the 0.6 cutoff is a guess to tune.
- 2026-11-19: `python -m engine.cli forms elaborate --fixture NAME [--as-text]` (preview, saves nothing): shows each short saved yes/no, the notes found with scores, and the result. First real-Ollama run on the Angkas form (as text boxes): the 0.6 cutoff is too low and logistics questions (laptop, hybrid) get irrelevant or invented sentences. Fixed the same day by your decision: only experience/knowledge questions are elaborated (`is_experience_question()`); logistics questions (hybrid, laptop...) keep the plain Yes; notes cutoff 0.65 (set after seeing that real scores run 0.5-0.72 even for Spring Boot; you will check results yourself, and `--min-score` tries other values). Also `forms elaborate --question "..." [--saved Yes]` tries one question without a page. 566 tests pass.
- 2026-11-19: Phase 3 closed by your decision. You reviewed retrieval, the form tables, drafted answers and `rag eval` and judged the performance fine. Picker was 3/5 on the sample posts (gate 4/5), accepted; watch it in real use. 567 tests pass. CLAUDE.md moved to Phase 4.
- 2026-11-20: first real employer try (EastWest: Prosple job page -> careers-page.com apply form). The opener was found, but the job page was refused (0 headings): Prosple uses "Your Role", "Key responsibilities include:", "About You", "The company is looking for:", "Qualifications & other requirements". Added them to the heading list (+1 test, 26 finder tests); the Prosple search list is still rejected by the repeated-line rule (it now has 2 headings but a 0.46 repeated share). Reader on that form: 10 fields, and the file button's own label is read as an extra checkbox "Resume: * Choose file" (to watch).
- 2026-11-20: Phase 4 step 4.3, the fill orchestrator. `engine/forms/orchestrator.py` runs reader -> job post finder -> answer engine -> resume picker -> filler -> screenshot -> `fills` row and stops; `history.py` saves the row (labels and scrubbed notes only, never values) and links the `action_log` rows to it afterwards (note the last log id before the fill). The CLI `forms fill` now calls it (new `--tab`, `--mode mock|dry_run`; `--post` replaces the finder; `--fixture` is a preview that saves nothing). Step 0: job text is the page's `<main>` content when it has 100+ words (no site menu, no signed-in name), and your full name, email, phone and address are scrubbed from it (whole values only, so "Marketing" survives). 13 orchestrator tests + 2 finder tests; three deliberate code breaks were each caught by the right test. Unknown questions are still saved by `answer_form` (not duplicated). Not done: company-question wiring (`REFLECT`), `company` in `fills` (left empty), real-page try-out. Heads-up: `settings.json` with `run_mode: dry_run` was committed in 56d55ba, which fails the mock-mode settings test.
- 2026-11-20: Phase 4 job post finder built (`engine/forms/jobfinder.py`, `tests/test_jobfinder.py`, 18 tests; whole suite 620 pass). Read-only; headings + word count decide "looks like a post" (all 5 saved posts pass); shared job boards (Workable, Greenhouse, Prosple...) also need the same first path segment; LinkedIn tabs are never read. Not done yet: the company-question (`REFLECT`) wiring and the orchestrator (4.3), both after the filler.
- 2026-11-20: job post finder tried on the real Prosple pages and fixed twice. (1) Playwright's `opener()` said None for every tab after `connect_over_cdp`; Chrome's own `openerId` knows the chain (search list -> job page -> apply form), so `opener_of()` asks Chrome. (2) Filter labels ("Unpaid with benefits") and a results list were accepted as a post; headings must now be whole lines, and a page whose lines are mostly repeated card labels is rejected (job page 0.00, search list 0.46, cutoff 0.15). Prosple job pages have only 1 heading, so the 1-heading rule stays. Check on the real browser: form -> opener tab = the job page. Open: the post text includes the site menu (and your name); the picker should get only the main content, and `rag.scrub` needs checking before wiring.
- 2026-11-20: Phase 4 design step: `fastapi` 0.165.0 and `uvicorn` 0.54.0 approved and installed. Mockups made (awaiting your approval): Wordings tab in `design/screens/Questions.html` (inline Approve/Reject per row, neutral grey kind chips, plain-number score, protected = ConfirmDialog) and new `design/screens/FillPanel.html` (5 states; "Fill without resume" when no job post, no Stop button; panel opens by itself on pages that look like an application, collapsed tab elsewhere). No code written.
- 2026-11-20: Phase 4 step 4.1, the filler. `engine/forms/filler.py` (`fill_page`, `FillReport`, `load_resume_file`, `to_iso_date`), `fixtures/forms/fill_types.html`, `tests/test_filler.py` (40 tests; whole suite 625 pass). Each field: `safety.check`, a random 1-4 s pause, fill by type, one `action_log` row (label and outcome, never the value). Flags are drawn in an overlay (shadow DOM, clicks pass through) with the amber from `tokens.css`: solid outline = guess, dashed = needs you. Never clicks a button: a recorder in the page checks every click on 4 saved pages, a static check scans the source, and the test was proved by breaking the filler on purpose. Found and fixed on the way: (1) several frames can share the address `about:srcdoc`, so the reader now also saves `frame_number` (Greenhouse fill 95 s → 0.3 s); (2) "Git, Docker" matched only Git. Safety tightened: in `mock` mode `fill` and `upload` on a real `http(s)` page are refused (a saved page is fine). CLI `forms fill` added. Not done in 4.1: custom dropdown options (left to you, reported), `fills` row, wiring the job post finder, on-page panel. Not yet tried on a real page.
- 2026-11-22: Phase 4 step 4.3, company questions wired to the job post (stage 4.3 gap 1). New: `CompanyBrief`, `build_company_brief()`, `company_answer()` in `drafting.py`; `BRIEF` and `COMPANY` prompts in `prompts/form.md`; `company_brief` AI task + `fixtures/ai/company_brief.json`; `answers.py` routes company questions (saved answer adapted, or a new one written; falls back to the saved text, or empty for you, when there is no post, no usable brief or the draft is rejected). More wordings count as company questions ("what do you know about us", "tell us why you want to join"...). The brief is built once per form (in memory, no new table). New read-only command `python -m engine.cli forms why-company [--tab|--post] [--question] [--mode dry_run]` to try it on a real post without a form. `tests/test_company_answer.py` (33 tests; suite 680 pass). Not done: your real-post try-out of the `[R]` company-question check, `company` in `fills`, the two orchestrator tests, the real-form dry run.
- 2026-11-22: Phase 4 step 4.4a (API groundwork, no API yet). `httpx` 0.28.1 added to `requirements.txt` (TestClient needs it; it was already installed). New `engine/answers_file.py` (read, backup, one-step write, `upsert_entry`, `delete_entry`, validated with `AnswerEntry`; `learning.py` now uses it). `learning.py`: `answer_unknown()` (file first with backup, then database, then marks the question answered), `reindex_after_change()` (returns a warning instead of failing when Ollama is off) and error subclasses `NotFound`, `AlreadyDecided`, `ProtectedNotConfirmed` (all still `LearningError`, so the CLI is unchanged). `history.py`: `list_fills()` and `mark_fill()` (only `filled` can change; `submitted_at` set on submitted). 51 new tests, whole suite 698 pass. Next: 4.4b API skeleton and localhost guards.
- 2026-11-22: Phase 4 step 4.3, the two missing orchestrator tests (stage 4.3 gap 2). `tests/test_orchestrator.py` now also runs the REAL `answer_form` (no spy; only the picker is faked, the AI is offline, the index is built with the mock embedder): unknown questions are really saved with their source page and the ids match `out.unknown_ids`; filling the same page twice leaves one row with `times_seen` 2 and two `fills` rows; the whole chain runs on `sample_form`, `angkas_workable` and `indiecampers_greenhouse` (fills, saves, never clicks, rerun adds no rows). Proved by breaking `record=save` on purpose: 5 of the 5 new tests failed. Found on the way: an EMPTY search index makes every field "error: RagError" (real use must run `rag reindex` first; the CLI already checks this). Orchestrator tests: 18.
- 2026-11-22: Phase 4 step 4.4b, API skeleton and guards (`engine/api.py`, `tests/test_api.py`, 32 tests; whole suite 730 pass). `create_app(settings, db_path, answers_path)`, `GET /health` (shows the run mode, cannot change it), `python -m engine.api [--host --port]`. Three layers: `serve()` refuses any host but 127.0.0.1 / localhost / ::1 (the server never starts), a Host check on every request (stops DNS rebinding), an Origin check on POST/PUT/PATCH/DELETE (only the dashboard at localhost:3000; no Origin = script, allowed), plus CORS for the dashboard only. One database connection per request (`db.connect(check_same_thread=False)`, API only). Proved by removing each guard on purpose: each removal was caught. Lesson: a test that calls `main()` must fake `uvicorn.run`, or a broken guard opens a real port (it hung once). Note: Starlette warns that `TestClient` prefers `httpx2`; harmless for now. Next: 4.4c read endpoints.
- 2026-11-22: Phase 4 step 4.4c, read endpoints (`GET /unknown`, `/wordings`, `/answers`, `/fills?status=&limit=`; JSON shapes in `engine/api_models.py`; 10 new tests, whole suite 745 pass). Look only: a test proves a read never changes a row. `/fills` has no field for typed values (a test saves a phone number in a note and checks it never comes back). `/wordings` carries `protected` and the saved answer's `kind`; `/answers` carries the answer text (local-only) and its wordings; empty lists return `[]`. Each of 3 deliberate breaks (protected flag, wordings, ordering) was caught. Not tracked yet: how many different pages an unknown question was seen on (only the last page URL is stored). Next: 4.4d write endpoints.
- 2026-11-22: Phase 4 step 4.3, `company` in the filled pages history (stage 4.3 gap 3). `history.pick_company()` takes the first usable name: the company brief (already checked against the job post), then the form page's `og:site_name`; job-board names (Prosple, Workable, Greenhouse...), empty and over-long values are skipped, and it never guesses, so no reliable name saves NULL. The orchestrator now reads the brief ONCE per fill (only when a job post exists, so no post = no extra AI call) and hands it to `answer_form` through the new `brief_cache` argument, so company questions reuse it. `FillOutcome.company`, and `forms fill` prints a `Company:` line. 13 new orchestrator tests (31 in the file); two deliberate breaks (no brief reuse, company not saved) were each caught. Page titles are not parsed for a name (too unreliable). Still to do in 4.3: the real-form dry run, and your real-post try of the company answer.
- 2026-11-22: Phase 4 step 4.4d, write endpoints (`engine/api_write.py`, `api_deps.py`; `tests/test_api_write.py`). `POST /unknown/{id}/answer`, `POST /wordings/{id}/approve` (`confirm_protected`) and `/reject`, `POST/PUT/DELETE /answers`, `POST /fills/{id}/status`. Order for every change: check, backup + write `answers.json`, update the database, rebuild the index; a failed re-index is a warning (`reindexed: false`), never an undo. Your two choices: PUT and DELETE (`?confirm_protected=true`) on a protected answer need the same confirmation as approving a wording for it (also when demoting its kind), and every change returns the updated item. Errors come back as `{code, detail}`: 404 not_found, 409 protected_needs_confirmation / already_decided / already_exists / not_allowed, 422 invalid. Requests use `scope` (as in the SPEC); responses keep `location_scope`. Changes run one at a time (a write lock). Found by a test and fixed: two backups in the same second had the same filename, so the second overwrote the first (`answers_file.backup` now adds -2, -3). Also: answering an unknown question can no longer overwrite a saved answer (`add_entry` refuses; `update_entry` is the only way to change one). 5 deliberate breaks (confirm ignored, edit/delete check removed, lock removed, backup overwrite, add overwrite) were each caught. Next: 4.4e the fill job.
- 2026-11-22: Phase 4 step 4.4e, the fill job (`engine/api_fill.py`, `tests/test_api_fill.py`, 25 tests) and `scripts/api_sandbox.py` (runs the API on a COPY of your data, mock mode, port 8001). `POST /fill` (optional body: `tab`, `post_text`, `resume`) answers 202 with a job id at once; `GET /fill/{job_id}` gives running / done (summary: counts, job post used + Change tabs, resume and why, flagged labels, unknown ids, screenshot, fills row id) / error (plain reason). It runs `fill_current_page()`, the same call as `forms fill`, in its own thread with its own Playwright and database connection. One fill at a time (409 `fill_running`); browser closed is 503 `browser_closed`; empty or wrong-mode index is 409 `index_not_ready` (same early check as the command line); Ollama unreachable is 503. A job always ends as done or error, an unexpected error shows only its type to you and in `action_log`, the last 20 jobs are kept. Decisions: polling (no streaming), tab chosen by text only. Tests: stub runner for job logic, plus the real chain on an inline page in a headless browser (history row saved, screenshot, no clicks, none of your details in the responses). 7 deliberate breaks (second start allowed, busy never cleared, status always done, index check skipped, error text leaked, browser check skipped, failure not logged) were each caught. Not tried against a real page yet. Next: 4.5 the controls page in the dashboard.
- 2026-11-22: Phase 4, every kind of field (after the first real Shopee try: 11 of ~20 fields read, names not filled, AI guesses in Company/Designation, all 9 dropdowns invisible). Reader: a new label step takes the ONE `<label>` in the field's own block (Shopee's `<label for>` points at nothing), before the placeholder; a red star counts as required; custom `<div>` dropdowns (class ending in select/dropdown/combobox, or role=combobox) are read as ONE `dropdown` field with their options (`CUSTOM_HELPERS_JS`, shared with the filler; phone widgets and react-select inputs are left to the old path; buttons in a list are never options). Answer engine: school, degree, education level (from your degree), year level, graduation year and skills come from the profile by code; country-code dropdown from your number, and the number box next to it gets the number without the code; no portfolio = GitHub (flagged); short fact boxes with no saved answer ("Previous / Current Company") are never AI-drafted (`is_fact_label`); `pick_option` now matches words not letters (Java is not JavaScript), handles yes/no, and returns "" on a tie; a value not in a custom list's visible part is kept and searched for (flagged). Filler: opens a custom dropdown, searches it when needed (full value, then the subject after "in", then the first long word), clicks the option, checks the box now shows it; multi-choice picks exact names only, up to the page's limit (default 8); nothing found = empty, search text cleared. Click rule changed with your OK: the filler may click a dropdown's box and its options (three helpers, checked by an AST test); buttons, links and Submit/Apply/Next stay forbidden, and the in-page recorder still fails any other click. Fixtures: `shopee_careers.html` (real page, sanitized) and `custom_dropdowns.html` (synthetic, behaves like Shopee's widgets + an ARIA list at the end of <body>). `tests/test_custom_dropdowns.py` (37 tests; suite 874 pass); two deliberate breaks caught. Found: the capture sanitizer over-redacts ("Denmark" -> "DenREDACTED" because of a name part, and "Philippines" from the address); fixed by hand in the fixture, not in `capture.py`. Not done: date pickers (Course Period, Work Period, Availability), the terms checkbox (left to you on purpose), a live fill on Shopee by you.

- 2026-11-25: audit fixes, Step 0 (no engine change). An audit of the filler on mock Greenhouse/Lever/Workday/Google Form/tricky forms found 4 bugs. Added 5 synthetic pages `fixtures/forms/audit_*.html` and `tests/test_audit_regressions.py` (32 tests: 18 for the bugs, marked `xfail(strict=True)` until each fix lands, and 14 guards that already pass, e.g. promo/referral codes stay not-personal, a yes/no radio is not personal, no button click or submit on any audit page). Plan changes agreed with you: Bug 1 stops at the first earlier block that holds a field (so a section heading is never taken as the question); a third Bug 1 layout (Greenhouse `<p>` without a legend); the safe Workday page shows the picked option on its button; unsupported controls get no outline in the page for now. Saved a 'before' snapshot of the reader on the 6 real forms (20/9/8/14/13/20 fields, 3-11 ms each). Suite: 889 pass, 18 xfail.
- 2026-11-25: audit fixes, Bug 1. `questionOf()` in the reader's page script (`engine/forms/reader.py`), used as `groupOf(e) || questionOf(e)`: a radio group (or 2+ same-name checkboxes) with no `<legend>` takes the short text just before its choices (nearest first, up to 4 levels up, 200 chars max), and stops at the first earlier block that holds a field, so a section heading past another question is never used; nothing found = the old `name` fallback. Lever (`cards[1]`), Google Form (`entry.14`) and Greenhouse-without-legend layouts now read their question; a legend still wins; a lone checkbox is unchanged. Python grouping untouched. The 6 real saved forms read exactly the same (all their groups already had legends); reader +0.3 ms. Suite: 892 pass, 15 xfail (bugs 2-4).
- 2026-11-26: stage 4.5 step 1, engine additions for the controls page (`engine/api_browser.py`, `tests/test_api_browser.py`, 29 tests; suite 921 pass, 15 xfailed). `GET /status` (mode, browser open, current page and title, running fill id so a reloaded dashboard keeps following it; the page is not read while a fill runs), `GET /jobpost` (the job post a fill WOULD use + your other tabs, read only, logs one `read` row; 503 browser closed, 409 `no_page`, 409 during a fill), `GET /fills/{id}/screenshot` (only a PNG that the row points to AND that sits inside `data/screenshots/`; `..`, other folders and non-PNG files are 404). `FillIn` gains `post_tab_url` (the tab you picked as the job post, by exact address: tab numbers shift) and `no_resume` ("Fill without resume": no finder, no picker, no upload); conflicting choices are 422. New `jobfinder.post_from_tab_url()`, `JobManager.running_id`, `fill_current_page(no_resume=...)`. Six deliberate breaks were each caught. Also tried for real against a throwaway Chromium on the debugging port with saved pages: the status reader names the open form, and the preview finds the job post in the opener tab (and says not found + lists the tab when the form was opened on its own).
- 2026-11-26: stage 4.5 step 2, the v0 dashboard shell on live data. `dashboard/lib/api.ts` is the only place the dashboard calls the engine (never the database; `NEXT_PUBLIC_ENGINE_URL`, default 127.0.0.1:8000); errors become `ApiError` with the engine's code and plain message (engine down = "The engine isn't running. Start it with: python -m engine.api"). `lib/api-types.ts` mirrors `engine/api_models.py`. `lib/usePoll.ts` (ask now, then every N s, keeps the last good data; no new dependency). `EngineProvider` polls `/status` every 4 s and the counts every 10 s. New `ControlsTopBar` (real mode badge, Engine connected / not reachable; no counters, quota or STOP in v0) and `ControlsSidebar` (Fill this page, Questions = unknown + wordings in amber, Answer bank, Filled pages = not marked yet in blue). `app/(controls)` holds the v0 screens; the v1 mock screens moved to `app/(v1)` (Home is now `/home`). Checked: `npm run build` and `npm run lint` pass; Playwright against the sandbox engine (copy of your data, port 8001) showed MOCK, Engine connected, Questions 23, Filled pages 4, every nav link; with the engine stopped, the top bar says Engine not reachable and the red banner appears.
- 2026-11-26: stage 4.5 step 3, the Questions screen (`components/questions/`; Waiting | Wordings | Answered, matching `design/screens/Questions.html`). Waiting: the selected question is a form (answer, kind, location scope, city; Save stays disabled until you choose a kind, because the engine requires it), the others are cards (long labels cut to 3 lines). Legal / eligibility questions say "You must answer this yourself" and can only be saved as protected: new `protected` flag on `GET /unknown` from `is_sensitive()` (+1 test). Wordings: a tall DataTable with Approve / Reject per row; a protected row opens the ConfirmDialog (Cancel focused) and only its confirm sends `confirm_protected`; an engine 409 asking for confirmation opens it too. Answered: the 15 most recently used saved answers + a link to the Answer bank. After every change: Toast, a "Saving and re-indexing" line while the engine works, an amber Banner if the re-index could not run, a danger Banner with the engine's message on errors, and the sidebar counts refresh. `DataTable` gained opt-in `tall` rows, `align: right` columns and `emptyMessage`; new shared `TextArea` and `StatusLine`; `lib/format.ts`, `lib/labels.ts`. Checked in a browser against the sandbox engine: answered 1 question (unknown 8 -> 7, answers 121 -> 122), approved a fixed wording, approved the protected visa wording through the dialog, rejected one (wordings 15 -> 12), deep link `?tab=wordings`; no console errors. Differences from the mockup: no AI suggestion box (there is no endpoint for one), and "last on <page>" instead of "on N pages" (the engine keeps only the last page).
- 2026-11-26: stage 4.5 step 4, the Answer bank editor (`components/answers/`, matching `design/screens/AnswerBank.html`). Search (question, answer and approved wordings), FilterChips by kind with counts, a tall DataTable, row click opens the edit drawer; "Add answer" opens it empty. The question of a saved answer is read only when editing (the engine keeps it as the answer's identity); the kind has one line of help each. Saving a protected answer (also when changing its kind) opens "Change a protected answer?" with before/after, and only its confirm sends `confirm_protected`; every delete asks first (protected adds a line). Toast after each change, "Saving and re-indexing" while the engine works, an amber Banner when the re-index could not run, engine errors inside the drawer. New shared `SearchInput` and a `dangerLink` Button variant (the red Delete link in the mockup). Checked in a browser against the sandbox engine: 122 answers (Fixed 64, Open 28, Protected 30), search and empty state, edited a fixed answer, edited a protected one through the dialog, added one (123) and deleted it (122); the engine data matched each step; no console errors.
- 2026-11-26: stage 4.5 step 5, the Filled pages history (`components/history/`, matching `design/screens/History.html`). Newest first, FilterChips by status with counts, refreshed every 15 s; rows still `filled` carry Mark submitted and Abandoned (Abandoned asks first; the engine allows one change only, so decided rows have no buttons). Row click opens the drawer: page link, times, resume, the real screenshot from `GET /fills/{id}/screenshot` with "Open full size", flagged fields with their notes and filled fields BY LABEL ONLY. Status chips reuse existing tokens: filled = queued blue, submitted = green, abandoned = rejected grey (`FillStatusChip`). Found and fixed: the engine's times are UTC (`datetime('now')`), so `dateLabel` now shows your local time (a Shopee fill read 10:23; it was 18:23 in Manila, matching its screenshot file name). Checked in a browser against the sandbox engine with your 4 real history rows: all 4 screenshots served (PNG), marked one submitted from the drawer (submitted_at set), abandoned one through the dialog (Cancel focused), sidebar count 4 -> 2, filters, a decided row's drawer says the status is final; no console errors.
- 2026-11-26: stage 4.5 step 6, Fill this page (`components/fill/`, matching `design/screens/Fill.html`). Status line from `/status` (browser ready + current page, browser not found with a danger Banner, no page open); the job post a fill would use, from `/jobpost` once per page, with Change; the picker (your other tabs, a paste box, "Use this job post and fill" sends `post_tab_url` or `post_text`, "Fill without resume" sends `no_resume`) opens by itself when no post is found; `POST /fill` then `GET /fill/{id}` every 1.5 s with a seconds counter; a reloaded dashboard keeps following the running fill; the Done summary (counts, flagged labels with reasons, engine messages, job post used, resume and why), "Answer the new question(s)" links to `/questions?id=`, "Fill this page again"; engine errors in a danger Banner in its own words; "Needs you" links on the right. Checked end to end with a throwaway headless Chromium on the debugging port (temp profile, saved pages only) and the engine on a COPY of your data in mock mode (mock search index, temp screenshots): job post found in the opener tab, fill done in 18 s (8 filled, 3 new questions, resume A, 5 flagged), reload during the fill, Change -> picked tab -> second fill, form opened on its own -> "Job post not found" -> Fill without resume (no upload, history row resume NULL), a page with no fields -> the engine's message. Found and fixed on the way: after a reload, the screen forgot the fill once `/status` stopped naming it (it now keeps the job id), and a `Date.now()` during render that Next.js flags for prerendering. Test-only note: headless Chrome reports every tab as visible, so the test marked background tabs hidden; a real window shows only the active tab.
- 2026-11-26: stage 4.5 step 7, side-by-side check and wrap-up. Each built screen was screenshotted next to its mockup frame (a comparison page, not committed). Differences: Questions Waiting has no AI suggestion box (no endpoint), shows "last on <page>" (not "on N pages"), labels questions by field type or "Legal and eligibility" (no topic), and saves one location scope at a time; the Answered tab has no mockup (recent answers + link); the Done summary uses the shared Tag for its count chips; the not-found box is an inline amber box (the Banner needs a button); DataTable headers follow Applications.html; "Used / Last used" in the Answer bank are 0 / Never for every answer because **the engine never counts uses** (`times_used` is never incremented): an engine gap found here, not fixed. SPEC Phase 4 boxes ticked: controls page, suggested wordings screen, Mark as submitted / Abandoned. DESIGN.md now lists the v0 controls page and the shared pieces added (TextArea, StatusLine, SearchInput, `dangerLink`, DataTable `tall` / `align` / `emptyMessage`). Final checks: 922 pytest pass, 15 xfailed; `npm run lint` and `npm run build` pass. Not done: a real job site in `dry_run` (yours), the on-page panel, passive submit detection.
- 2026-11-26: v0 status check against the code. Ticked what is done but was never ticked: fastapi/uvicorn approved (in `requirements.txt` since Nov 20), company questions get the job post (`company_answer`, Nov 22; your real-post try is still open), mock-mode flow on saved HTML (checked end to end in stage 4.5). SPEC Phase 4: job post finder, screenshot + `fills` row, unknown questions with their page, `engine/api.py` ticked. Still open, so v0 is not done: audit bugs 2/2b/3/4, the on-page Fill panel, passive submit detection, the real-site dry runs, a week of real use, README check, `v0.1` tag. README status updated.
- 2026-11-26: audit fixes, Bug 2 (Workday `<button role="combobox">` dropdowns). Reader: `findCustoms()` also takes a `<button role=combobox>` (any other button stays an action); new shared `listFor()` reads the options from the list the box controls (`aria-controls` / `aria-owns`, else a `role=listbox` right after it). Filler: before opening or closing a dropdown, `_SAFE_TRIGGER_JS` checks what would be clicked: a `<button>` or link is clicked ONLY when it is `<button role="combobox" type="button">` (cannot submit); a button with no type or `type=submit` leaves the field as needs you ("this dropdown is a button that could submit the form: pick it yourself") with zero clicks. Safety rule change agreed with you. The in-page click recorder in `tests/test_filler.py` allows that one kind of button and still fails any other button, link or submit; the source guard (no `type=submit` text, 3 allowed click helpers) is unchanged and passes. The Bug 2 label test now expects "How Did You Hear About Us?" (`clean_label` drops the star and keeps the `?`, like every label and the Bug 1 tests). Before/after reader dump on the 6 saved forms: same counts (20/9/8/14/13/20); one improvement: the ARIA-list "Education Level" dropdown in `custom_dropdowns.html` now lists its 3 options up front. Four deliberate breaks were each caught. Suite: 895 pass, 12 xfail.
- 2026-11-26: audit fixes, Bug 2b (never skip a control silently). New field type `unsupported`: the reader reports `role=slider / spinbutton / switch / textbox` elements and `contenteditable` boxes (outermost only; a plain button, link or menu never qualifies) with their label and NO saved position, so nothing can ever type into or click them. `answer_field` sends them straight to needs you ("a control JobPilot cannot fill (slider, rich-text box or switch): fill it yourself") without asking the AI or adding them to Questions (nothing you could save would be filled); the filler leaves them as needs you even when handed a value. No outline in the page for now (agreed Nov 25). 3 extra tests: a value is never put into a slider or rich-text box, an unsupported control never lands in Questions, a toggle `<button role=switch>` is reported and a menu button is not. 6 deliberate breaks caught; one line that no test could prove (buttons only as switches) was removed instead. The 6 saved forms read exactly the same. Suite: 929 pass, 10 xfail (the settings-file test fails only while your local settings.json says dry_run).
- 2026-11-26: audit fixes, Bug 3 (Workday phone fields), by code, no AI. A DROPDOWN labelled as a calling-code list ("Country Phone Code", "Phone code", "Dialing / Calling code", "Country code") is now the phone's country-code box, checked before the "someone else's details" words that contain "code"; `country_code_option` then picks your country ("Philippines (+63)"). "Phone Device Type" / "Type of phone": `phone_type_fill()` picks Mobile only for a Philippine mobile number (`is_ph_mobile`: 09... or +639..., 10 digits after the prefix); a landline or foreign number is left empty and flagged, never guessed. Referral, promo, verification, discount and course code dropdowns stay not personal, and a text box named "Country Phone Code" is untouched by the new rule (2 new tests). Found on the way: an editing script wrote `` as a backspace character into one regex; caught by the test and fixed. 4 deliberate breaks caught. Suite: 937 pass, 8 xfail.
- 2026-11-26: audit fixes, Bug 4 and the audit wrap-up. By code from your profile, no AI: the degree pattern also takes "Course / Program", "Course or Program", "Program / Course", "Degree and Major"; radios and checkboxes are checked against the EDUCATION patterns only ("Year level" picks your year when an option matches, else empty and flagged: Freshman/Sophomore stay yours) and never against the name/email/phone/city words; a checkbox group asking which technologies / tools / languages / frameworks you use ticks ONLY options named exactly like a saved skill (`skills_checkbox_fill`, Java is not JavaScript), always flagged. New guard test: yes/no radios and checkboxes that contain a profile word (city, phone, email, name) stay not personal. All 18 audit bug tests now pass (no xfail left); 4 deliberate breaks caught (one first missed, so the guard test was added). Before/after table (reader + by-code answers, code at 52ac9b0 vs now, every saved form): the 6 real forms are unchanged except `sample_form` "Which tools do you use?" (not personal -> Docker, flagged); audit pages: Google Form course / year / technologies now answered, the 2 Workday dropdowns now read, slider and rich-text box now reported. No-submit check passes on all 5 audit pages. Audit section done. Suite: 949 pass.
- 2026-11-26: Phase 4, the on-page Fill panel (`engine/forms/panel.py`, `tests/test_panel.py`, 17 tests), built from `design/screens/FillPanel.html` (approved by you as is). `python -m engine.cli browser open` now installs it in the bot's Chrome: `install_panel()` adds a bridge (`expose_binding`) and then the panel script (`add_init_script`, also run on pages already open). The panel lives in a CLOSED shadow DOM with the colours from `design/tokens.css`; it opens by itself when the page has 3+ visible form fields (code, no AI), otherwise it is a collapsed tab that makes no engine calls; it can be dragged and collapsed, and moves left when it would cover a Submit / Apply / Next button; it redraws itself last so the filler's amber labels never cover it. States: ready (mode badge, job post with Change), filling (seconds counter), done (counts, flagged, job post used, Fill this page again, Open dashboard), job post not found / Change (tabs, paste, Use this job post and fill, Fill without resume), error (engine's words + Try again). The bridge forwards to the engine API on 127.0.0.1 (`/status`, `/jobpost`, `POST /fill`, `GET /fill/{id}`), so the result is the same as the dashboard button. Safety (your choice, SPEC 1b updated): the panel takes the bridge function and deletes it from `window` before any site script runs, every call needs a fresh per-session token, calls from embedded frames are refused, script-faked clicks are ignored (`isTrusted`), only 4 actions and 3 fill choices exist, and the page to fill is always the panel's own page. 8 deliberate breaks were each caught. Checked end to end with a throwaway headless browser (debugging port 9333) and a mock-mode copy of your data (port 8001): the panel opened on the saved form, showed the opener-tab job post, filled 9 fields (3 new questions, resume A), and the history row was saved. Your real engine (port 8000, dry_run) and bot browser (9222) were running and were not touched. Suite: 966 pass.

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
- [x] Write about 10 **held-out** questions without looking at `also_asked_as`, so the eval measures understanding, not memorised wordings. (Done Nov 15: 10 added to `tests/fixtures/eval_questions.json` as `ho-01`..`ho-10`: 6 reworded, 1 legal, 1 personal, 2 new open; 60 questions in total. Never copy these into `also_asked_as`; the eval warns if you do.)
- [x] Write project descriptions that are specific and true (technologies, what you built). The AI may only use these. (Done Nov 11: taken from your portfolio, 5 projects with result, problem, solution and hardest part in `profile.json`. Check them once and fix anything that is not exactly true.)
- [x] Collect 5 real job posts as text files and write down which resume you would send for each, to test the resume picker. (Done: `data/job_posts/`, answers in `expected_resume.json`.) Resume content decides, so make sure each resume's text really shows the skills you want it chosen for.
- [x] Judge retrieval output yourself in step 2. If the wrong chunk comes first, say so, because only you know what's correct.
- [x] Decide the confidence cutoff for "flagged" (started at 0.7; now 0.85 after the prefix change, see "Matching decisions" below).
- [x] Approve adding `sqlite-vec` (approved and installed Nov 10, 2026).

**Prompt Claude Code**

1. Teach-first: "Teach me RAG with 5 sentences: embed them with Ollama, ask a question, show the similarity scores."
2. "Implement `engine/rag.py`: chunking (profile, resumes, projects, answers), embeddings with `nomic-embed-text`, sqlite-vec storage, `retrieve(question, k=5)`, a re-index command. Show the top 5 chunks for each question in my eval set."
3. "Write `engine/forms/answers.py` with the rule order: by each answer's kind: protected → used exactly as saved, never sent to the AI, highlighted for review (and questions containing sensitive words are treated as protected even with no saved match); fixed → bank via RAG with scope, used as written; open and new non-sensitive questions → Ollama rewrites from retrieved facts only, flagged. Also add elaboration: a short saved \"Yes\" in a free-text box becomes \"Yes\" plus 1–2 sentences of real reasons from my answers, projects and resumes, flagged; radios and dropdowns get the plain answer; protected is never expanded. Add `prompts/form.md`. Mock-mode tests for each rule."
4. "Add the resume picker (job post **text** + the most similar chunks of each resume → A or B with evidence, never by file name) and the test that **no prompt ever contains phone, address, email or ID numbers**." The picker takes the text as input; finding the job post in the browser is Phase 4 (decided Nov 12).
5. "Run the answer engine against the 3 form fixtures with real Ollama in `dry_run` and print a table: field, answer, source, confidence."

**Matching decisions (Nov 10, 2026)**: how a form question finds its saved answer. Kept here so we don't re-argue them.

| Decision | Why |
| --- | --- |
| Saved questions and form questions are both embedded with nomic's `clustering:` prefix; facts keep `search_document:`/`search_query:` | Same-kind comparison. Eval: right question first went from 7/11 to 10/11 before any other change |
| `also_asked_as` alternate wordings in `answers.json` (312 written from real ATS forms) | Gives retrieval more ways in. Right question first: 25/26. Not a long-term fix for synonyms on its own |
| `MATCH_THRESHOLD` = 0.85 (was 0.7) | The new prefix lifts all scores; 0.7 accepted everything |
| Below the cutoff: NO MATCH → unknown questions list; may still be filled, flagged **not recommended**, any kind (including protected) | Your rule |
| A match in NEW words → suggested wording, **never saved until you approve** (`questions approve ID`); protected answers also need `--yes-protected`; rejected wordings never return | Stops one wrong match from becoming a permanent 1.0 match (Nov 11) |
| Approved design for an AI check: personal fields by code first; skip the AI only at score ≥ 0.95 and ≥ 0.05 ahead of #2; protected answers need the AI to agree **and** score ≥ 0.80; fallback to the cutoff if the AI fails | Your choices, Nov 10 |

**Step 1 result: `llama3.1:8b` as a "same question?" judge (Nov 10)**. Tested on 6 hard questions (start/begin, hybrid, feedback, visa, address, industry):

- **Speed:** 100% CPU (the Radeon iGPU isn't used), 5.6 GB RAM. Cold start 23–55 s; warm about 5 s per question when RAM is free, 15–45 s when Windows runs short of RAM (free RAM fell to 0.7 GB with other apps open).
- **Quality: not good enough.** With a loose prompt it picked related-but-wrong questions, including "Will you need visa sponsorship?" → "Are you legally authorized to work?" (dangerous for a protected answer). With a strict prompt (temperature 0, JSON schema) it answered "none" to everything, missing begin = start and the hybrid question: 3/6, and the 3 "right" answers were all "none". Answers also changed between runs.
- **Decision:** don't build the AI judge on `llama3.1:8b` for now. Next, test a stronger **embedding** model (light on RAM, fast). Keep `llama3.1:8b` for its planned job, drafting open answers. Personal-field detection by code (step 2 of the plan) goes ahead regardless.

**Embedding model comparison (Nov 10)**. Run on your 10 held-out questions (written without looking at `also_asked_as`); 6 should match a saved question, 2 should not:

| Setup | Right question first (no wordings) | Right question first (with wordings) | Speed |
| --- | --- | --- | --- |
| `nomic-embed-text`, `clustering:` both sides (current) | **6/6** | **6/6** | fastest |
| `mxbai-embed-large`, no prefix | 4/6 | 4/6 | about 2x slower |
| `mxbai-embed-large`, query instruction both sides | 5/6 | 5/6 | about 3x slower |

- **Decision: keep `nomic-embed-text`.** `mxbai-embed-large` was not better on your questions (it sent "most at ease using at work" to "working asynchronously"). Small sample, so this says "no reason to switch", not "nomic is best".
- With the current 0.85 cutoff on the held-out set: 4/6 correct matches accepted, the other 2 (scores 0.80 and 0.82) still pointed at the right saved question but were flagged NO MATCH (filled, marked not recommended); 2/2 open questions rejected. Personal questions found the right field (phone, city), but these must still be caught by code first.
- Roles stay split: the **embedding model** finds things (RAG); **`llama3.1:8b`** writes open answers.

**Check**

```powershell
python -m engine.cli rag reindex
python -m engine.cli rag ask "When can you start?"
python -m engine.cli forms answer --fixture fixtures/forms/google_form.html
python -m pytest -q
```

Manual:
- [x] Review the table for all 3 forms. Every field has the right source label.
- [x] No legal or eligibility field was answered by AI.
- [x] At least 7 of the 8 reworded questions found the right saved answer.
- [x] Resume picker chose correctly on all 5 sample posts (run `resume pick --post data/job_posts/<file>.txt` in `dry_run`) (4 of 5 is acceptable; investigate the miss).
- [x] No invented facts in drafted answers (read every one).

**Done when:** the eval set passes (reworded questions 7/8, legal 4/4 not AI-answered, personal 4/4 by code), the picker is right on 4+ of 5 posts, the privacy test passes, and you can explain how a field gets its answer.

---

## Phase 4: Fill, review, controls page and real use (1.5 weeks, then 1 week of use)

**Goal:** press **Fill this page** and the form is filled, the resume uploaded and guesses highlighted. It stops, and you submit. The history shows what you filled, and passive detection offers to mark submitted.

**You do**

- [x] Approve adding `fastapi` and `uvicorn`.
- [ ] Test on your own Google Form first, then Prosple, then a career page, always in `dry_run`. **You** click Submit.
- [ ] Sign in to Google by hand in the bot's Chrome (pick which account employers will see). Use a Google Form that requires sign-in (file upload or "limit to 1 response") for the first test. If Google says "This browser or app may not be secure": open the bot's profile on its own without JobPilot attached, sign in, close it, then let JobPilot reopen it (SPEC Part 1 edge cases). Never share or sync `data/browser_profile/`; it holds your logins.
- [x] **Design the Wordings screen first** (a third tab in `design/screens/Questions.html`: Waiting | Wordings | Answered), then build it. Requirements are in `SPEC.md` Part 2 "2b. Suggested wordings" and `design/DESIGN.md`: rows with new wording, matched saved question, score, times seen, kind chip; Approve / Reject; a ConfirmDialog for protected answers; Toast, Banner and EmptyState. Unknown question cards also show "seen N times, on N pages".
- [x] **Mock up the on-page Fill panel** (new `design/screens/FillPanel.html`, using `tokens.css`): collapsed tab, ready, filling, done (summary + job post with Change), job post not found. Approve it before it's built.
- [ ] Look at the controls page next to the design mockups (`Questions.html`, `Applications.html`, `Components.html`) and tell Claude what differs. CLAUDE.md requires a side-by-side comparison, so don't skip it.
- [ ] Use it for **a week of real applications**. Keep `notes/v0-misses.md`: for every wrong, missing or awkward fill, write the page URL, the field and what went wrong.
- [ ] Review the screenshot of every filled page before you submit.
- [ ] Write the README with Claude. Check that it matches reality.

**Prompt Claude Code**

1. Explain-first: "Explain how the filler handles each field type, how we highlight guesses, and how passive submit detection works without ever clicking."
2. "Implement `engine/forms/filler.py`: fill text, select, radio, checkbox, date; upload the resume; 1–4 s random delays; `safety.check()` and logging before each action. **Add a test that fails if any code path clicks a Submit or Apply button.** Test on saved HTML."
3. "Add the **job post finder** (SPEC Part 1 'Finding the job post'): look on the form page, then the tab that opened it (`page.opener()`), then other tabs on the same site, else ask me (pick a tab or paste text). Read-only. Show which job post was used with a Change button. No job post = no resume upload, flagged. Mock-mode tests with saved pages."
4. "Save a `fills` row (URL, job and company, resume, flagged count, screenshot path, status `filled`) and an unknown-questions row for each unanswered question."
5. "Add `engine/api.py` (FastAPI on 127.0.0.1 only): fill, unknown questions, answers CRUD, filled pages, mark status, and the wordings endpoints (`GET /wordings`, approve with `confirm_protected`, reject) plus answering an unknown question (writes `answers.json` with a backup, then re-indexes). Reuse `engine/learning.py`."
6. "Build the controls page in the existing dashboard: Fill this page, Unknown questions, Answer bank editor, Filled pages history. Reuse the existing components. Compare with the mockups afterwards and list the differences."
7. "Add the **on-page Fill button** (SPEC Part 2 '1b'): explain `add_init_script`, shadow DOM and `expose_binding` first. Then inject a small floating JobPilot panel into every page of the bot's browser that calls the same fill steps as the dashboard button, shows the job post used (Change), progress and the result. It never clicks or covers Submit. Test on saved HTML in mock mode."
8. "Passive detection: after a fill, watch the page read-only for a confirmation (thank-you text, URL change) and offer 'Looks submitted. Mark it?'. Never clicks, never marks without confirmation."
9. After the week: "Here are my notes from `notes/v0-misses.md`. Group them by cause and propose fixes, smallest first."

**Check**

```powershell
python -m engine.api
cd dashboard; npm run dev
python -m pytest -q
```

Manual checklist (do all three sites):
- [ ] Press Fill this page: fields fill, resume uploads, flagged answers are highlighted.
- [ ] Job post finder: with the description on the form page, in the opener tab, and not open at all (it asks you), the controls page shows the right job post, and Change works.
- [x] Company questions ("Why do you want to work here?"): once the job post is found, pass it to the `REFLECT` prompt so these get an answer that fits the job. Until then `answers.py` leaves them to you (`is_company_question()`).
- [ ] On-page panel: it appears on the job page in the bot's browser, its Fill button gives the same result as the dashboard button, it doesn't cover Submit, and it collapses out of the way.
- [ ] The Submit button was **not** clicked, and the form is still open.
- [ ] A new row appears in Filled pages history with a screenshot.
- [ ] A question you've never answered lands in Unknown questions. Answer it, re-fill, and see it filled.
- [ ] Submit by hand. Passive detection offers to mark it. Confirm, and the status turns `submitted`.
- [ ] Press **Abandoned** on a row you didn't send.
- [x] Mock mode: the same flow works on saved HTML with no network.

**Audit fixes (Nov 25):** four reader / answer-engine bugs found by running the real pipeline on mock Greenhouse, Lever, Workday, Google Form and "tricky" forms. One commit per bug, each with its regression tests in `tests/test_audit_regressions.py` (marked expected-to-fail until fixed).
- [x] Step 0: regression pages `fixtures/forms/audit_*.html` and the tests, no engine change.
- [x] Bug 1: radio/checkbox questions without a `<legend>` keep their question text (not `cards[1]`).
- [x] Bug 2: Workday-style `<button role="combobox">` dropdowns are read and filled; one that could submit the form is never clicked.
- [x] Bug 2b: a control the reader cannot drive is reported as "needs you" (`unsupported`), never skipped.
- [x] Bug 3: "Phone Device Type" and "Country Phone Code" answered from your number.
- [x] Bug 4: course/program, year level and technology checkboxes answered from your profile.
- [x] Before/after table of every saved real form; no-submit check on all audit pages.

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
