---
name: legacy-migration
description: V1.9.4/V1.10.x conservative migration
---

# V1.9.4/V1.10.x conservative migration

Import historical assets without trusting them as canonical. Skip secret-like content and mark imported knowledge LEGACY_UNVERIFIED until revalidated.

## Required behavior

- Read the Runtime state before reasoning about the next action.
- Preserve canonical project, repository, release, requirement and SST identities.
- Return UNKNOWN or a Knowledge Gap when evidence is insufficient.
- Never expose or persist plaintext credentials, tokens, cookies, OTP/MFA or customer-sensitive data.
