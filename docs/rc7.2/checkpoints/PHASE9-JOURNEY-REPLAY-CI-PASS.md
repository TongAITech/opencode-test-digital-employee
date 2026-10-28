# RC7.2 Phase 9 Journey Replay checkpoint

Status: `CI_PASS` (repository qualification only)

Qualified code HEAD: `fb371a786a9a9be9043507009919c0345b888f2b`
Qualified workflow run: `40735018227`

Qualification evidence:

- RC7.2 contracts Python 3.8: PASS — `183 passed`.
- RC7.2 contracts Python 3.11: PASS — `183 passed`.
- inherited RC7 regression Python 3.8: PASS — `492 passed, 1 skipped`.
- runtime compile: PASS.

Delivered slice:

1. only `COMPILED_CANDIDATE` Journey IR may enter replay.
2. replay is bound to canonical WorkItem/Attempt/Worker/Session truth and an ACTIVE WRITE BrowserLease for that same execution identity.
3. Runtime dispatches Candidate steps in order through an explicit replay adapter and persists per-step Actual/Evidence truth in R1.
4. first failed step fails fast and stops later step dispatch.
5. candidate `replay_status` is controlled to `NOT_RUN/PASSED/FAILED`; replay never changes `official=false` or `executable=false`.
6. contract/CI adapters cannot self-claim Field verification. `field_verified=true` requires both adapter self-assertion and explicit Runtime trust of the adapter kind.
7. replay and per-step truth survive R1 restart.
8. adapter exceptions are replay failures, never successful execution.

Important boundary:

- repository CI proves replay orchestration contracts only; it does not prove real BSK/CDP replay in bank.
- successful replay is not Benchmark PASS and cannot promote a Journey to Official/Executable.
- actual Field adapter qualification remains Field integration work.

Phase 9 overall remains **IN_PROGRESS**.
Field validation: **NO**.

Next atomic slice: Journey Benchmark. Benchmark must aggregate multiple replay truths under an explicit persisted policy, detect failures/inconsistency, distinguish contract replay from Field-verified replay, update only candidate benchmark status, and must not promote the Candidate to OFFICIAL/EXECUTABLE.
