# RC7.2 Phase 8 R1-native N10 Release Convergence checkpoint

Status: `CI_PASS` (repository qualification only)

Qualified code HEAD: `9bbc3b63348a06b568291f3b5853a9a9c7c813ea`
Qualified workflow run: `40729144870`

Qualification evidence:

- RC7.2 contracts Python 3.8: PASS — `144 passed`.
- RC7.2 contracts Python 3.11: PASS — `144 passed`.
- inherited RC7 regression Python 3.8: PASS — `492 passed, 1 skipped`.
- runtime compile: PASS.

Tests-first / implementation chain:

- `074ffdec...` froze R1-native N10 convergence contracts.
- `9bbc3b63...` implemented `ReleaseConvergenceAggregator` and replayable convergence snapshots.

Delivered slice:

1. callers no longer pass a manufactured list of convergence booleans to the new aggregation path; facts are derived from canonical R1 truth.
2. a raw `TestObligation.status=VERIFIED` is not trusted as completion by itself.
3. an obligation is proven only through the chain: VERIFIED obligation -> PASS ETU -> PASS WorkItem with independent Evaluation -> COMPLETED WorkItemAttemptBinding -> PASS execution_attempt -> canonical Evidence resolving back to Attempt/Case/Obligation.
4. Release Scope Manifest/denominator is mandatory. Missing or incomplete Requirement/SST/L1-L7 denominator blocks convergence.
5. all N1-N9 MissionNodes must have real Delivery + PASS Gate state before runtime integrity can pass; N10 cannot be reached by bypassing prior nodes.
6. 92% coverage alone never produces `CONVERGED`.
7. every ReleaseBatch application needs a qualifying coverage observation at or above its target.
8. open Coverage Gap, open canonical Gap or unresolved BackEdge blocks convergence.
9. HIGH/CRITICAL/BLOCKER defect states are acceptable only when CLOSED/DUPLICATE/NOT_A_DEFECT; DEFERRED is not silently treated as release-safe.
10. non-PASS WorkItems block release convergence.
11. provider/runtime blocked truth and Human Gate truth are carried into the existing N10 convergence evaluator.
12. derived convergence facts/result/blockers/proven/unproven obligations are persisted as `rc72_release_convergence_snapshot` and survive R1 replay.

Important boundary:

- this slice proves repository/runtime semantics only; no in-bank ReleaseBatch has yet passed this RC7.2 N10 aggregator.
- Coverage Gap lifecycle still needs explicit RESOLVED / EXCLUDED_APPROVED semantics. Without that final slice, a historical coverage gap would remain an unresolved blocker forever even after repair or approved exclusion.

Phase 8 overall remains **IN_PROGRESS** until that lifecycle is implemented and qualified.

Field validation: `NO`.
