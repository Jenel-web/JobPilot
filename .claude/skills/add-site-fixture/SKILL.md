---
name: add-site-fixture
description: Add offline support and tests for a new application form in JobPilot. Saves the page as a fixture in fixtures/forms/ with personal data removed, writes a reader test against it, and checks that nothing can submit. Run with /add-site-fixture <site name>, for example /add-site-fixture greenhouse.
disable-model-invocation: true
argument-hint: <site-name>
---

# add-site-fixture

Goal: a new form becomes testable offline, with no real website touched by tests. The site name is `$ARGUMENTS` (snake_case, e.g. `indiecampers_greenhouse`). If it is empty, ask for it.

## Flow to explain first (short, then wait for OK)

1. The user opens the form in the bot's browser (the one `engine/forms/browser.py` launches) and leaves it on the page.
2. `python -m engine.cli forms capture <name>` saves the open page to `fixtures/forms/<name>.html` with personal data removed.
3. A test reads that saved page with a headless browser and checks the fields the reader finds.
4. We check the page has no way for our code to press Submit.

Then wait for the user's OK. They do step 1 and run step 2 (capture needs their live page). Do not try to browse to the site yourself.

## After the fixture exists

1. **Check the file.** Open `fixtures/forms/<name>.html`. Confirm there is no real name, email, phone, address, token or resume text. If any is left, tell the user and stop. Do not commit it.
2. **Look at what the reader finds.** Run `python -m engine.cli forms read --json` style output against the fixture if the CLI supports it, or use `read_fields` in a throwaway script in the scratchpad. List each field: label, type, options, required, `needs_you`.
3. **Write the test** `tests/test_reader_<name>.py`, copying the pattern in `tests/test_reader.py` (module-scoped fixture, `sync_playwright`, `page.set_content`, `read_fields`). Assert only what is stable: the labels, types, option lists, required flags, and that unlabelled fields are reported as needs-you. Include any quirk of this site (iframe, custom dropdown, radio groups becoming one question).
4. **Submit check.** Assert that the reader returns no field of the submit button and that the filler (when it exists) never clicks an element that looks like Submit. If `engine/forms/filler.py` does not exist yet, say so and add a note to the ROADMAP instead of inventing the filler.
5. **Run** `.venv\Scripts\python.exe -m pytest tests/test_reader_<name>.py -q`, then the full suite.

## Rules

- Never commit a fixture with real personal data.
- Tests never open the live site. Fixtures only.
- No new dependency without asking.
- When done, point the user to `/finish-step`.
