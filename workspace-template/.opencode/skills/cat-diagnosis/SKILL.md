---
name: cat-diagnosis
description: CAT-assisted technical defect confirmation
---

# CAT-assisted technical defect confirmation

Use environment/system/time window/trace ID/request ID/business key to query CAT through the approved connector. CAT is supporting evidence, not the sole authority for product-defect confirmation.

## Required behavior

- Read the Runtime state before reasoning about the next action.
- Preserve canonical project, repository, release, requirement and SST identities.
- Return UNKNOWN or a Knowledge Gap when evidence is insufficient.
- Never expose or persist plaintext credentials, tokens, cookies, OTP/MFA or customer-sensitive data.
