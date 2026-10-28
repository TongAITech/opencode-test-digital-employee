# RC7.2 Phase 7 CapabilityBroker checkpoint

Status: `CI_PASS` (repository qualification only)

Qualified code HEAD: `6e33ba903c8c880f19bf920a7106d04cbf1ceb3b`
Qualified workflow run: `40719684817`

Qualification evidence:

- RC7.2 construction contracts, Python 3.8: PASS.
- RC7.2 construction contracts, Python 3.11: PASS — `86 passed`.
- inherited RC7 regression, Python 3.8: PASS — `492 passed, 1 skipped`.
- runtime compile: PASS.

Delivered slice:

1. Worker remains STRICT; missing tools are not silently granted.
2. `CapabilityRequest` is bound to canonical Mission/WorkItem/Attempt/Worker/parent TaskLease truth.
3. decisions are `AUTO_GRANT_TEMP_LEASE`, `DELEGATE_TO_SPECIALIST`, `HUMAN_GATE`, or `DENY`.
4. safe grant reuses the existing HMAC-signed TaskLease authority and creates a short-lived child lease for the exact capability.
5. wildcard/full-access requests are fail-closed.
6. specialist/high-risk capabilities can be delegated or human-gated without expanding requester privilege.
7. revoke is enforced inside `RC7AuthorityRuntime`, not only recorded in R1; expiry/revoke therefore fail closed in actual authorization.
8. child lease cannot be reused by another Worker/Attempt/WorkItem.
9. R1 persists audit metadata only; signing key, TaskLease signature, Captain token/credential and Full Access are never persisted in CapabilityLease truth.
10. CapabilityRequest/decision/lease audit survives R1 replay.

Important implementation boundary:

- `rc6_runtime.authority` remains frozen.
- RC7.2 extends `RC7AuthorityRuntime` with revocation/readback only.
- the cryptographic TaskLease itself remains runtime authority state; R1 is audit truth and does not reconstruct signing secrets after process restart. A new secure lease must be issued after authority-process recovery when required.

Phase 7 overall is **NOT COMPLETE**. Remaining independent slices are BrowserPool/BrowserLease, DataLease, and model failover.

Field validation: `NO`.
