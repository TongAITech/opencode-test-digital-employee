# RC7.2 Phase 7 DataLease checkpoint

Status: `CI_PASS` (repository qualification only)

Qualified code HEAD: `4dde899b894070a4d991e8fff8a7c5aef2d579cd`
Qualified workflow run: `40720774677`

Qualification evidence:

- RC7.2 contracts Python 3.8: PASS.
- RC7.2 contracts Python 3.11: PASS — `105 passed`.
- inherited RC7 regression Python 3.8: PASS — `492 passed, 1 skipped`.
- runtime compile: PASS.

Delivered slice:

1. N5 owns DataRef discovery/construction/verification; DataLease only owns runtime reservation.
2. mutable DataRef requires exact `EXCLUSIVE_WRITE` ownership.
3. immutable/reference DataRef may be shared through `SHARED_READ` leases.
4. a conflicting lease fails closed as `DATA_RESOURCE_CONFLICT`; the runtime never guesses or substitutes another DataRef for the executor.
5. unverified DataRef cannot be leased.
6. lease identity is bound to canonical Mission/WorkItem/Attempt/Worker and the exact DataRef.
7. wrong Attempt/Worker/DataRef, expired or released lease cannot authorize data use.
8. release requires cleanup evidence and reason; old lease is never transferred to another worker.
9. after release/expiry, the same resource can be reused only through a new lease.
10. DataResource/DataLease truth survives R1 replay.

Important implementation boundary:

- this slice does not discover, fabricate or repair test data during N7 execution.
- if required data is unavailable/conflicted/invalid, execution must surface a Data Gap and return to N5 rather than silently selecting replacement business data.
- actual DB reservation/cleanup adapters remain Field/runtime integration work on top of these ownership contracts.

Phase 7 overall remains **IN_PROGRESS**. The remaining slice is model/provider failover.

Field validation: `NO`.
