---
name: defect-lifecycle
description: Observation, diagnosis, canonical defect and retest
---

# Observation, diagnosis, canonical defect and retest

Every failure first creates an Observation. Use API/CAT/DB/browser/deployment/code evidence to diagnose. Correlate one root cause across L1-L7 into one Canonical Defect and close only after all verification obligations pass.

## Required behavior

- Read the Runtime state before reasoning about the next action.
- Preserve canonical project, repository, release, requirement and SST identities.
- Return UNKNOWN or a Knowledge Gap when evidence is insufficient.
- Never expose or persist plaintext credentials, tokens, cookies, OTP/MFA or customer-sensitive data.
