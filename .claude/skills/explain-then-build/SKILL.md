---
name: explain-then-build
description: Use before starting ANY new build step, feature or unfamiliar concept in JobPilot (Playwright selectors, embeddings, OAuth, a new engine module, a new dashboard screen). Shows the user flow, walks one concrete scenario, gives a short plan, then waits for the user's OK before writing code.
---

# explain-then-build

The user is a CS student building this to learn, and regrets rushing and following a plan blindly. So no code is written until they understand the step and say OK.

## Before you write anything

1. **Find the step.** Read only the current phase in ROADMAP.md and the SPEC.md sections it points to. Do not build anything from a later stage.
2. **Explain the concept** in plain words, max about 6 lines. If it uses a new library or idea, say what it is and why we need it here.
3. **Show the flow** as a short numbered list of what happens, from what the user does to what they see. Name the files that will change.
4. **Walk one concrete scenario** with real-looking values. Example: "You open the Angkas form, press Fill this page. The reader finds 'Why do you want this job?'. Code sees it is a company question, so it waits for the job post..." Include one case where it goes wrong and what the user sees then.
5. **Give the plan**: the small steps, each one testable, in order. Say which tests will prove each step, and that it works in mock mode first.
6. **Flag decisions.** Any new dependency, any change to safety rules, any place the AI is called: say it and ask. Give a recommendation, not a list of options.
7. **Stop and wait** for the user's OK. Do not start coding in the same message.

## While building (after the OK)

- One small step at a time. Tests with the code.
- After each working step, point the user to `/finish-step`.

## Keep it short

Plain words, no jargon without a one-line explanation. The goal is that the user could explain the step out loud in 2 minutes afterwards (ROADMAP rule).
