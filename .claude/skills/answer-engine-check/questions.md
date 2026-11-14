# Sample questions for answer-engine-check

Generic wording only. No real personal data here. Add a row whenever a real question went wrong.
Scope defaults to `any`. "Path" is what the engine must do.

| # | Question | Type / options | Expected path | Must not |
|---|---|---|---|---|
| 1 | First name | text | personal, by code | call the AI |
| 2 | Email address | text | personal, by code | call the AI |
| 3 | Phone number | text | personal, by code, stored format | call the AI |
| 4 | LinkedIn profile URL | text | personal, by code | call the AI |
| 5 | Are you legally authorized to work in this country? | radio: Yes, No | sensitive: closest saved answer, NOT RECOMMENDED if weak | AI answer |
| 6 | Do you require visa sponsorship? | radio: Yes, No | sensitive | AI answer |
| 7 | What is your gender? | select | sensitive | AI answer |
| 8 | Are you open to relocating? (use `--scope remote`) | radio: Yes, No | fixed or protected answer, scope respected | rewrite a protected answer |
| 9 | What are your salary expectations? | text | saved answer if one exists, flagged | invent a number |
| 10 | Describe a project you are proud of | textarea | open: flagged draft from projects | number or name not in the facts |
| 11 | Tell us about your strengths | textarea | reflective: pattern, stance, max 2 examples, humble closing | self-praise, copying the prompt |
| 12 | How do you decide when you are stuck? | textarea | reflective | more than 2 examples |
| 13 | Why do you want to work at this company? | textarea | company: waits for the job post | AI answer |
| 14 | Tell me about yourself | textarea | about_me detail fields, flagged draft | email or phone in the text |
| 15 | A brand-new odd question nobody saved: "What is your favourite colour?" | text | unknown: goes on the unknown-questions list (copy DB only) | crash, duplicate entry |
| 16 | The same question as #10 asked in new words: "Share an accomplishment you are proud of" | textarea | matched via RAG, suggested wording waits for approval | auto-save the new wording |
