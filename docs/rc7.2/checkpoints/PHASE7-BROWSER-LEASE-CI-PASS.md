# RC7.2 Phase 7 BrowserPool / BrowserLease checkpoint

Status: `CI_PASS` (repository qualification only)

Qualified code HEAD: `27e27bfc2078d36bf633692f6f47bb78401276c3`
Qualified workflow run: `40720280257`

Qualification evidence:

- RC7.2 contracts Python 3.8: PASS.
- RC7.2 contracts Python 3.11: PASS — `95 passed`.
- inherited RC7 regression Python 3.8: PASS — `492 passed, 1 skipped`.
- runtime compile: PASS.

Delivered slice:

1. Browser is modeled as `BrowserPool -> BrowserInstance -> BrowserLease`, not a global singleton.
2. every lease is bound to canonical Mission/WorkItem/Attempt/Worker truth.
3. one BrowserInstance has at most one active WRITE owner.
4. conflicting WRITE acquisition fails closed as `RESOURCE_CONFLICT`; an existing owner is never silently reassigned.
5. AuthKeeper and L4/L5 execution can share an auth asset reference but must use separate browser-control leases/instances when concurrent.
6. Captain direct Browser WRITE control is forbidden by the resource contract.
7. BrowserInstance identity requires distinct profile/CDP/BSK endpoints; duplicates are rejected.
8. release/expiry never transfers the same lease to another worker; the instance is reused only through a new lease.
9. released/expired or wrong Attempt/Worker lease cannot authorize browser use.
10. BrowserInstance/BrowserLease truth survives R1 replay.

Important implementation boundary:

- this slice is control-plane ownership only; it does **not** claim real BSK/Chromium process integration has been Field-validated.
- real browser launch, BSK/CDP probing, 4A auth-state import/export and in-bank concurrency remain Field/runtime adapter work on top of these ownership contracts.

Phase 7 overall remains **IN_PROGRESS**. Remaining slices: DataLease and model failover.

Field validation: `NO`.
