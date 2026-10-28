# RC7.2 Phase 8 Release Scope Denominator checkpoint

Status: `CI_PASS` (repository qualification only)

Qualified code HEAD: `a8a82d6a4a61024318aa3ef7d92d5c3461038d12`
Qualified workflow run: `40727813317`

Qualification evidence:

- workflow: `completed/success`.
- RC7.2 contracts Python 3.8: PASS — `136 passed`.
- RC7.2 contracts Python 3.11: PASS — `136 passed`.
- inherited RC7 regression Python 3.8: PASS — `492 passed, 1 skipped`.
- runtime compile: PASS.

Tests-first / implementation chain:

- `1c5ba27c...` froze ReleaseBatch Requirement/SST/L1-L7 denominator contracts.
- `a8a82d6a...` implemented canonical `ReleaseScopeManifest` and replayable `ScopeDenominatorSnapshot` in the same R1.

Delivered slice:

1. observed Requirements/SSTs/Cases can no longer define their own denominator.
2. manifest Requirement keys must exactly match `ReleaseBatch.requirement_ids`.
3. one SST cannot silently belong to multiple Requirements.
4. every expected SST must declare a non-empty set of required L1-L7 levels.
5. denominator evaluation exposes missing SSTs even when they never produced an obligation.
6. an SST with some obligations still reports missing required test levels.
7. out-of-scope TestObligation truth is not ignored; it makes the denominator incomplete.
8. manifest/snapshot truth survives R1 replay.
9. this slice deliberately does not infer execution PASS, defect closure or coverage convergence; those belong to the N10 convergence aggregator.

Phase 8 overall remains **IN_PROGRESS**.

Next atomic slice:

> implement an R1-native N10 convergence aggregator. It must consume this frozen scope denominator plus canonical TestObligation, coverage, defect, task, gap, evidence and runtime truth. Any dimension that cannot be proven from R1 stays false/blocked; callers may not manufacture a list of PASS booleans.

Field validation: `NO`.
