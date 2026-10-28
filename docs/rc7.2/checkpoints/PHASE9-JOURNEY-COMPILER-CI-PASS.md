# RC7.2 Phase 9 Journey Compiler checkpoint

Status: `CI_PASS` (repository qualification only)

Qualified code HEAD: `e4db60df0a033eca16b0671d103d7c742e52af7a`
Qualified workflow run: `40734328675`

Qualification evidence:

- RC7.2 contracts Python 3.8: PASS — `175 passed`.
- RC7.2 contracts Python 3.11: PASS — `175 passed`.
- inherited RC7 regression Python 3.8: PASS — `492 passed, 1 skipped`.
- runtime compile: PASS.

Delivered slice:

1. `CAPTURED` Journey Teaching recording compiles into canonical `rc72_journey_candidate` truth.
2. compiler rejects non-CAPTURED recordings and incomplete/non-contiguous source steps.
3. Candidate preserves ReleaseBatch -> Requirement -> SST -> TestObligation lineage and source recording identity.
4. each compiled IR step preserves `source_step_id`, sequence, action type, URL/page-role, DOM/page-state/network/screenshot/wait/evidence provenance.
5. INPUT steps compile only reference-based values (`value_ref` / `credential_ref`); plaintext captured values are not copied into Candidate IR.
6. ASSERT steps require an explicit `oracle_ref` and fail closed when absent.
7. one recording cannot produce competing Candidates.
8. compiler output is fixed to `COMPILED_CANDIDATE`, `asset_class=CANDIDATE`, `executable=false`, `official=false`, `replay_status=NOT_RUN`, `benchmark_status=NOT_RUN`, `review_status=NOT_REVIEWED`.
9. Candidate truth survives R1 replay.

Important boundary:

- compilation is not browser replay and proves no real browser execution.
- Candidate is not an official Journey asset and cannot yet be treated as production L4/L5 executable truth.
- Replay, Benchmark and Human Review promotion remain Phase-9 work.

Phase 9 overall remains **IN_PROGRESS**.
Field validation: **NO**.

Next atomic slice: Journey Replay. Replay must execute only a COMPILED_CANDIDATE through an explicit browser replay adapter under canonical BrowserLease/Attempt ownership, persist per-step actual/evidence truth, fail closed on assertion/action divergence, and must not promote a Candidate to OFFICIAL/EXECUTABLE.
