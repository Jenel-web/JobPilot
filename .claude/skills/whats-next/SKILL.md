---
name: whats-next
description: Use when the user says "what's next", "next step" or "what do we do now" in JobPilot, or pastes a whole phase or plan and asks what to do. Finds the next step, gives a detailed implementation plan, then shows two scenarios, how the system behaves NOW and how it behaves AFTER the change. Waits for the user's OK before any code.
---

# whats-next

The user finds it hard to write a good prompt every time, and wants the same clear structure every time. They learn by seeing the system before and after a change, and they regret following a plan blindly. So: no code until they say OK.

## Sources of truth (use both)

- **ROADMAP.md** = the theme. It says *what* is needed and which checkbox is next. Read "Current position" and the current phase only.
- **The phase detail** = the how. It gives the implementation steps. This is the phase's own section in ROADMAP.md, the SPEC.md sections it points to, and any text the user pasted.
- If they disagree, do not guess. Say so in "Decisions" and ask.
- Never plan work from a later phase (CLAUDE.md "Current stage").

## Output: always these sections, in this order

### 1. What's next
One or two lines: the step, and the phase and checkbox it comes from.

### 2. Where we are
Two or three lines from ROADMAP.md "Current position": what is done, what this step builds on.

### 3. Implementation plan
Numbered, small steps, each one testable. For every step give:
- the files that change (use `file_path` links)
- the test that proves it
- that it works in `mock` mode first

### 4. Right now (scenario)
A concrete story with real-looking values. Walk through what the user does and what the system does today. End where the system falls short, for example "it doesn't catch this field, so it is left empty."

### 5. After the change (scenario)
The same story with the change in. Say step by step what the user opens, presses and sees, and why it is easier. Add one failure case and what the user sees then.

### 6. Decisions for you
New dependencies, changes to safety rules, any new AI call (`ask_ai`), anything unclear. Give a recommendation, not a list of options. If there are none, say "None."

### 7. Stop
End with: "Say OK and I'll start with step 1." Do not write code in the same message.

## Rules

- Plain words. A new concept gets a short explanation, about 6 lines max. For a big new concept, use `explain-then-build`.
- Keep it short enough to read in one sitting. Skip a section only if it truly doesn't apply, and say so.
- After the user says OK, build one small step at a time with tests, then point them to `/finish-step`.
