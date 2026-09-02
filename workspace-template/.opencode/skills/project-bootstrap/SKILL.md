---
name: project-bootstrap
description: Guided project bootstrap
---

# Guided project bootstrap

Discover complete Git repository identities, systems, environments and connectors. Ask only for facts that cannot be discovered. Store credentials only as secret/auth references.

## Required behavior

- Read the Runtime state before reasoning about the next action.
- Preserve canonical project, repository, release, requirement and SST identities.
- Return UNKNOWN or a Knowledge Gap when evidence is insufficient.
- Never expose or persist plaintext credentials, tokens, cookies, OTP/MFA or customer-sensitive data.
