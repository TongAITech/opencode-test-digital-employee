---
name: session-recovery
description: OpenCode worker session recovery
---

# OpenCode worker session recovery

Treat OpenCode sessions as disposable workers. Checkpoint Mission state before rotation, rebuild a bounded Context Pack, and preserve plan version and cursor.

## Required behavior

- Read the Runtime state before reasoning about the next action.
- Preserve canonical project, repository, release, requirement and SST identities.
- Return UNKNOWN or a Knowledge Gap when evidence is insufficient.
- Never expose or persist plaintext credentials, tokens, cookies, OTP/MFA or customer-sensitive data.
