---
name: release-truth
description: Current Release Truth and artifact integrity
---

# Current Release Truth and artifact integrity

Keep Version SST, Requirement SST, Git, submission, build, deployment and runtime truth distinct. Cache and hash DOCX/PDF artifacts and invalidate stale assets.

## Required behavior

- Read the Runtime state before reasoning about the next action.
- Preserve canonical project, repository, release, requirement and SST identities.
- Return UNKNOWN or a Knowledge Gap when evidence is insufficient.
- Never expose or persist plaintext credentials, tokens, cookies, OTP/MFA or customer-sensitive data.
