---
name: execution-boundary
description: Planner/Executor/Evaluator and capability boundaries
---

# Planner/Executor/Evaluator and capability boundaries

Use only role-scoped AI Test tools. Planner reads and freezes plans; Executor executes only the current step; Evaluator evaluates evidence. Built-in shell/edit/read access is forbidden.

## Required behavior

- Read the Runtime state before reasoning about the next action.
- Preserve canonical project, repository, release, requirement and SST identities.
- Return UNKNOWN or a Knowledge Gap when evidence is insufficient.
- Never expose or persist plaintext credentials, tokens, cookies, OTP/MFA or customer-sensitive data.
