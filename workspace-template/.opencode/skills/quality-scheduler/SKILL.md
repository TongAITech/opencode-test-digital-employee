---
name: quality-scheduler
description: L1-L7 applicability and campaign scheduling
---

# L1-L7 applicability and campaign scheduling

L1-L5 need an explicit automatic decision for every SST. L6/L7 require per-SST risk selected/not-selected decisions. Schedule by dependency DAG, not a serial L1→L7 loop.

## Required behavior

- Read the Runtime state before reasoning about the next action.
- Preserve canonical project, repository, release, requirement and SST identities.
- Return UNKNOWN or a Knowledge Gap when evidence is insufficient.
- Never expose or persist plaintext credentials, tokens, cookies, OTP/MFA or customer-sensitive data.
