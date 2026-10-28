# RC7.2 Phase 9 Journey Teaching Capture checkpoint

Status: `CI_PASS` (repository qualification only)

Qualified code HEAD: `9b25f2ce37cf63878885ee5bfef904340c8892c9`
Qualified workflow run: `40731522392`

Qualification evidence:

- workflow: `completed/success`.
- RC7.2 contracts Python 3.8: PASS — `167 passed`.
- RC7.2 contracts Python 3.11: PASS — `167 passed`.
- inherited RC7 regression Python 3.8: PASS — `492 passed, 1 skipped`.
- runtime compile: PASS.

Delivered slice:

1. Human Journey Teaching recording is canonical R1 truth, rooted at ReleaseBatch -> Requirement -> SST -> TestObligation.
2. only L4/L5 obligations can create Journey Teaching recordings.
3. start/append operations reuse Phase-7 BrowserPool ownership and require an ACTIVE WRITE BrowserLease for the same Mission/WorkItem/Attempt/Worker.
4. recording is also bound to the canonical WorkItemAttemptBinding and real Worker Session identity.
5. capture steps are strictly ordered and persist structured URL/page-role/element/page-state/DOM/network/screenshot/wait/evidence references rather than opaque chat history.
6. plaintext secret-bearing capture metadata such as password, Authorization, Cookie, access/refresh/session tokens, client secret or API key fails closed; auth/credential references must be used instead.
7. completion requires at least one captured step and recording-level evidence.
8. completed teaching recording state is `CAPTURED` with `asset_class=CANDIDATE_SOURCE` and `executable=false`.
9. this slice deliberately does not register or create an official/executable Journey asset.
10. recording/step truth survives R1 replay.

Important boundary:

- this slice does not prove real BSK/CDP teaching capture in-bank; BrowserLease ownership is real runtime semantics, while actual browser event adapters remain Field integration work.
- CAPTURED recording is not an executable Journey and cannot be consumed by L4/L5 execution yet.
- Compiler, Replay, Benchmark and Human Review promotion remain Phase-9 work.

Phase 9 overall remains **IN_PROGRESS**.
Field validation: **NO**.

Next atomic slice: Journey Compiler -> CANDIDATE Journey IR only. The compiler must preserve ReleaseBatch/Requirement/SST/TestObligation lineage, step provenance, variables/oracles/waits and evidence refs; it must reject incomplete/non-CAPTURED source recordings and must not promote output to OFFICIAL/EXECUTABLE.
