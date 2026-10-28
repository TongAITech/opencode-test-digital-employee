# RC7.2 Phase 9 Journey Human Review / Official Promotion checkpoint

Status: `CI_PASS` (repository qualification only)

Qualified code HEAD: `50195db3ced06df7e287806d821278f710dc5aae`
Qualified workflow run: `40736921507`

Qualification evidence:

- RC7.2 contracts Python 3.8: PASS — `199 passed`.
- RC7.2 contracts Python 3.11: PASS — `199 passed`.
- inherited RC7 regression Python 3.8: PASS — `492 passed, 1 skipped`.
- runtime compile: PASS.

Delivered slice:

1. Promotion API accepts only `attestation_ref`; it does not accept caller-supplied `approved=true` or reviewer identity.
2. external HumanApprovalVerifier must resolve a trusted attestation and Runtime must explicitly allowlist the verifier kind.
3. approval requires `actor_type=HUMAN` and `field_verified=true`; Worker/Agent self-approval fails closed.
4. approval scope binds exact Candidate, Benchmark, ReleaseBatch, Requirement, SST, Obligation, artifact versions and a canonical SHA-256 scope digest.
5. stale/mutated Candidate or Benchmark invalidates approval.
6. repository-only Benchmark cannot be promoted: `field_benchmark_verified=true` is mandatory.
7. REJECTED human review persists canonical review truth but creates no Official asset.
8. APPROVED trusted Field review creates a separate `rc72_official_journey_asset`; Candidate remains `asset_class=CANDIDATE`, `official=false`, `executable=false`.
9. duplicate/competing promotion for the same Candidate fails closed.
10. Human Review and Official asset truth survive R1 restart.

Important boundary:

- CI uses a contract verifier to prove the verification/promotion mechanics. It does not prove a real bank Human Gate integration.
- Field validation remains **NO** until a real bank human approval verifier/attestation source is connected and exercised.
- Phase 9 is still not complete: the frozen construction contract also requires the Official Journey asset to be consumable/replayable by an L4/L5 worker under isolated browser ownership.

Phase 9 overall remains **IN_PROGRESS**.
Field validation: **NO**.

Next atomic slice: Official Journey Worker Consumption under canonical WorkItem/Attempt/Worker/Session + ACTIVE WRITE BrowserLease ownership, without mutating the immutable Official asset.
