# RC6 Wave 1 — Runtime Kernel Qualification

Status is derived from executable tests, not design claims.

## Scope
- Mission != Session durable state
- Runtime-issued immutable Worker Identity
- Role/Artifact ACL and Tool ACL
- Same-role recovery generation
- Pre-request context budget guard
- Global provider rolling-window budget/backpressure
- 429/451 provider cooldown hooks
- Fail-closed stage machine
- Bounded resume envelope without conversation history

## Required tests
- `ROLE_SPOOF_REJECTED`
- `COORDINATOR_PROFESSIONAL_WRITE_REJECTED`
- `SAME_ROLE_ROTATION_PRESERVES_AUTHORITY`
- `TOOL_ACL_ENFORCED`
- `CONTEXT_HARD_LIMIT_PREVENTED`
- `REQUEST_WINDOW_BACKPRESSURE`
- `RETRY_STORM_PREVENTED_AFTER_429`
- `RESUME_ENVELOPE_HAS_NO_CHAT_HISTORY`
- `STAGE_GATE_FAIL_CLOSED`

Qualification command:

```bash
python -m unittest discover -s tests -v
```

Wave 1 must not be marked ENGINEERING_PASS until this command passes on committed source and the commit SHA is recorded in `docs/RC6_CONSTRUCTION_STATUS.md`.
