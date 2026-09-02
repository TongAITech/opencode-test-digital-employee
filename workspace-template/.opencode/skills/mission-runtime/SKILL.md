---
name: mission-runtime
description: Mission Runtime and resume semantics
---

# Mission Runtime and resume semantics

Use persisted Mission state, frozen plans, current cursor, checkpoints, pause/resume and gates. Never translate “continue testing” into a new plan.

## Required behavior

- Read the Runtime state before reasoning about the next action.
- Preserve canonical project, repository, release, requirement and SST identities.
- Return UNKNOWN or a Knowledge Gap when evidence is insufficient.
- Never expose or persist plaintext credentials, tokens, cookies, OTP/MFA or customer-sensitive data.
