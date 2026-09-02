---
name: human-browser
description: HumanTask and controlled browser
---

# HumanTask and controlled browser

Create HumanTask for authentication, MFA, CAPTCHA, business confirmation, showcase or review. Transfer browser lease to HUMAN and resume the same step after completion. Never record secrets.

## Required behavior

- Read the Runtime state before reasoning about the next action.
- Preserve canonical project, repository, release, requirement and SST identities.
- Return UNKNOWN or a Knowledge Gap when evidence is insufficient.
- Never expose or persist plaintext credentials, tokens, cookies, OTP/MFA or customer-sensitive data.
