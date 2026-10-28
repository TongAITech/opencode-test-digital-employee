# RC7.2 Phase 8 Coverage Feedback Mapping checkpoint

Status: `CI_PASS` (repository qualification only)

Qualified code HEAD: `cb657e9043e76142fd33eb1f8bb54d99be85cbe4`
Qualified workflow run: `40726963682`

Qualification evidence:

- workflow: `completed/success`.
- RC7.2 contracts Python 3.8: PASS — `129 passed`.
- RC7.2 contracts Python 3.11: PASS — `129 passed`.
- inherited RC7 regression Python 3.8: PASS — `492 passed, 1 skipped`.
- runtime compile: PASS.

Tests-first / implementation chain:

- `7400dbf2...` froze Coverage Observation -> CodeSlice -> Requirement/SST/TestObligation lineage contracts.
- `cb657e90...` implemented canonical coverage observation, deterministic business-lineage mapping and evidence-backed gap classification in the same R1.

Delivered slice:

1. Libra-like coverage observation is persisted under ReleaseBatch/Mission/Application, with covered/total units, target ratio and evidence ref.
2. uncovered CodeSlice is mapped only to existing TestObligation lineage for the same ReleaseBatch/Application.
3. zero match becomes `NO_REQUIREMENT_MAPPING` and routes to N2/N3 investigation; no orphan Case/ETU is created.
4. multiple matches become `AMBIGUOUS_OBLIGATION_MAPPING`; Runtime fails closed instead of choosing an arbitrary Requirement/SST/Obligation.
5. exactly one mapping only establishes lineage. Coverage itself does **not** infer `CASE_MISSING` or another business reason.
6. evidence-backed classification routes `ANALYSIS_MISSING -> N3`, `CASE_MISSING -> N4`, `DATA_BLOCKED -> N5`, `EXECUTABLE_BLOCKED -> N6`, `PATH_NOT_REACHED -> N8`.
7. `UNREACHABLE` requires multiple evidence refs and becomes `EXCLUSION_REVIEW_REQUIRED`; it is not silently excluded from the coverage denominator.
8. coverage observation/gap truth survives R1 replay.
9. this service does not create TestCases/ETUs and therefore does not make Libra the test-asset root.

Phase 8 overall remains **IN_PROGRESS**.

Next atomic slice:

> build an R1-native Release Convergence Aggregator for N10. It must derive convergence facts from canonical truth and keep any unprovable dimension false/unknown; callers must not manufacture a set of PASS booleans merely to obtain `CONVERGED`.

Field validation: `NO`.
