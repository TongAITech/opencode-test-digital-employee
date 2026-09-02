---
name: admin-control-plane
description: Local control plane operation
---

# Local control plane operation

Use the local control plane to inspect Missions, Human Tasks, Defects, Campaigns and Connectors. It is a local pilot control plane; enterprise IAM and shared worker pools require the team deployment profile.

## Required behavior

- Read the Runtime state before reasoning about the next action.
- Preserve canonical project, repository, release, requirement and SST identities.
- Return UNKNOWN or a Knowledge Gap when evidence is insufficient.
- Never expose or persist plaintext credentials, tokens, cookies, OTP/MFA or customer-sensitive data.
