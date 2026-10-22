# RC8 Implementation Status

Branch: `work/rc8`
RC7 source/capability base: `delivery/rc7-default-enhancements@2c2eecbf18dde97ecdb10b65264e8c5c2a88ef72`
RC7 verified transport/toolset reference: `delivery/rc7-internal-transport-0bbb8239@af59027e7227fa1861fea95c6d05ff73aefb8572`
Overall status: `IN_PROGRESS`
Current phase: `NO-DISCOUNT DESIGN FREEZE COMPLETE / NEXT = W-A + W-B IMPLEMENTATION`

## Mandatory interpretation correction

Tool Reality Verification MUST NOT be promoted into stage/layer/mission completion.

Current scoped truth:
- `TOOL:MAVEN_JUNIT = BANK_REALITY_VERIFIED`
- `TOOL:CODEGRAPH = BANK_REALITY_VERIFIED`
- `STAGE:CODE_ANALYSIS = IMPLEMENTED/CI_VERIFIED_PARTIAL; BANK_FULL_ANALYSIS_PENDING`
- `LAYER:L1 = AUTONOMOUS_CLOSED_LOOP_NOT_IMPLEMENTED`
- `LAYER:L2..L7 = RC8_AUTONOMOUS_CLOSED_LOOP_NOT_IMPLEMENTED`
- `MISSION:TEST_SUFFICIENT = NO`
- `RELEASE = HOLD`

A green Maven/JUnit attempt, CodeGraph query success, installed plugin, CI contract double, WorkItem completion, or generated report does not imply test sufficiency.

## Frozen no-discount design set

Upper baselines:
- `docs/rc8/RC8-MASTER-CONTRACT.md`
- `docs/rc8/RC8-ARCHITECTURE-BASELINE.md`
- `docs/rc8/RC8-PRODUCT-BASELINE.md`
- `docs/rc8/RC7-TO-RC8-GAP-MATRIX.md`
- `docs/rc8/RC8-NO-DISCOUNT-DELIVERY-CONTRACT.md`

Construction-grade contracts frozen before next implementation:
- `docs/rc8/RC8-IMPLEMENTATION-BLUEPRINT-v2.md`
- `docs/rc8/RC8-CAPABILITY-CLOSURE-MATRIX.md`
- `docs/rc8/RC8-L1-L7-ACCEPTANCE-CONTRACT.md`
- `docs/rc8/RC8-MISSION-GRAPH-CONTRACT.md`
- `docs/rc8/RC8-PRODUCT-PROJECTION-MAP.md`
- `docs/rc8/RC8-RC7-REGRESSION-CATALOG.md`
- `docs/rc8/RC8-WAVE-DELIVERY-GATES.md`
- `docs/rc8/RC8-REQUIREMENT-TRACEABILITY-MATRIX.md`

These documents are binding. Requirements cannot be deleted or weakened to make implementation easier.

## No-discount closure model

Every implementation slice closes four independent lines:
1. Architecture
2. Testing Intelligence / Autonomous Loop
3. Product Projection / UX
4. Reality / Deployment

Missing any applicable line -> PARTIAL/IMPLEMENTED only.

Statuses are separately scoped:
- TOOL
- STAGE
- LAYER
- MISSION
- RELEASE

## RC7 inheritance baseline

RC8 intentionally keeps two RC7 authorities:
1. source/capability lineage: `2c2eecb`;
2. offline transport/toolset completeness reference: `af59027`.

RC7 certification facts carried into RC8:
- Reality Certification CLOSED
- RC8_ENTRY_READY=YES
- not FULLY_AUTONOMOUS_TEST_COMPLETE
- L1/L2/L3 READY in RC7 certification semantics only
- L4/L5/L7 PARTIAL
- L6 BASELINE_ONLY
- TEST_PARTIALLY_EXECUTED
- Release HOLD
- 49 raw gaps -> 16 canonical gaps

Inherited labels do not automatically promote RC8 layer closure.

## W0 / W1 reusable foundation

Implemented/reusable:
- canonical Node/TestRun/WorkItem/ProductionBatch/RequirementDeliveryScope identities
- PLAN/RUNTIME separation
- R1 runtime-only ledger with idempotency/conflict/replay/sequence gates
- Evidence/Artifact foundations
- capability qualification state machine
- Center Node registration/heartbeat/lease/control foundation
- Node outbound Center client
- Artifact Sync resumable/hash/AVAILABLE path
- Windows Git Bash + Linux bash launchers
- Windows output decoding hardening
- package-external durable Node state direction

These are foundations, not autonomous test completion.

## Maven/JUnit tool capability

Target-bank Reality proved actual Windows Git Bash + bank Maven + real `cfg-center` + fresh Surefire/JUnit execution:
- tests=2243
- failures=0
- errors=0
- skipped=8
- capability VERIFIED
- R1 persistence verified
- WorkItem completed

Valid scoped claim only:
`TOOL:MAVEN_JUNIT = BANK_REALITY_VERIFIED`.

Does NOT prove:
- ExecutableSpec/script generation
- JaCoCo/coverage.py
- changed method/line/branch coverage
- requirement/risk/VP coverage
- failure ownership/RCA
- delta design/re-execution
- mutation/assertion strength
- L1 convergence
- TEST_SUFFICIENT

Pure disconnected Maven portability remains separately unproven because the successful bank run could use the internal Maven repository.

## CodeGraph tool capability / Code Analysis

Target-bank Reality proved actual CodeGraph structural work against real Java snapshot:
- context/callers/callees/dependency/impact
- source snapshot/digest binding
- graph Artifact
- R1 persistence
- WorkItem completion

Valid scoped claim:
`TOOL:CODEGRAPH = BANK_REALITY_VERIFIED`.

Full Code Analysis remains incomplete. Existing/partial implementation includes Git snapshot authority, iterative structural queries, semantic-request contract and DSH headless semantic worker groundwork.

Still required for `STAGE:CODE_ANALYSIS = BANK_REALITY_VERIFIED/SUFFICIENT`:
- real bank DSH semantic execution
- semantic change interpretation
- API/service/DB/config/business-state impact where evidenced
- risk mapping
- L1-L7 test-impact mapping
- unknown/follow-up query loop
- independent sufficiency evaluation
- re-query/re-analysis convergence
- structured Center/product projection

## L1 autonomous closed loop current truth

`LAYER:L1 = AUTONOMOUS_CLOSED_LOOP_NOT_IMPLEMENTED`.

Required by W-B:
1. Risk/VP driven L1 design
2. ExecutableSpec
3. JUnit/TestNG/pytest script builder
4. script validation
5. real runner
6. JaCoCo / coverage.py
7. Git + CodeGraph + coverage changed-code mapper
8. requirement/risk/VP/oracle coverage
9. failure classifier/ownership router
10. RCA/repair routing
11. durable Coverage Gap
12. delta test design
13. delta script generation
14. targeted re-execution
15. coverage recalculation
16. mutation/assertion-strength where configured
17. L1 sufficiency evaluator
18. convergence controller
19. Attempt/Evidence/Gap/Defect projections
20. product UI
21. real bank multi-attempt mission proof

`mvn returncode == 0 && JUnit failures/errors == 0` means only `EXECUTION_RESULT_GREEN`.

## L2-L7 current truth

Professional layer contracts are frozen in `RC8-L1-L7-ACCEPTANCE-CONTRACT.md`.

- L2: Repository/DB/transaction/readback closed loop required
- L3: verified route/auth/API/backend-oracle closed loop required
- L4: real Browser steps/network/evidence; zero-step/awaiting-worker blocked
- L5: one coherent correlated business journey required
- L6: workload/NFR/performance semantics; absent NFR => BASELINE_ONLY
- L7: authz/privilege/negative/security scope; scanner is only one capability

All remain RC8 autonomous-loop OPEN until dedicated Reality proof.

## Permanent RC7 regression gate

Every `RC7-REG-*` item in `RC8-RC7-REGRESSION-CATALOG.md` is a permanent acceptance input.

Critical clusters:
- Director self-execution/runtime contamination
- session/context loss
- Node identity/package upgrade
- Maven false block/stale Surefire/all-green != L1
- CodeGraph not invoked/stale/one-query != analysis
- one-pass requirement/design insufficiency
- test data/precondition weakness
- stale-cookie/manual-history 4A
- guessed route/404
- weak L2/L3 evidence
- L4 zero-step/awaiting-worker fake PASS
- fragmented L5 fake E2E
- L6 NFR ambiguity
- L7 scanner-all-blocked mistake
- product/evidence/projection drift
- knowledge loss across sessions
- autonomous route-back/invalidation failure

## Product requirement

The 13 primary pages remain mandatory and are mapped in `RC8-PRODUCT-PROJECTION-MAP.md`.

Product is part of Definition of Done. If users must read DSH logs to understand what was tested, why PASS/FAIL occurred, coverage, gaps, route-back or evidence, the slice is incomplete.

## Current next implementation target

Do NOT resume breadth-first `Browser -> 4A -> DB -> ...` tool migration as the main line.

Next implementation is:
`W-A Mission Kernel prerequisites + W-B First Autonomous L1 Vertical Slice`.

The slice must prove:
Requirement/Code Risk -> Test Design -> ExecutableSpec -> Script -> Preconditions/Data -> Real Execution -> JaCoCo/Coverage -> Gap/Failure -> Delta Design -> Targeted Re-run -> Recalculate -> L1 Sufficiency -> Convergence -> Product Projection -> Bank Reality.

Mandatory Reality behavior: Attempt 1 exposes at least one real insufficiency/gap; the platform routes, repairs/delta-designs, creates a later Attempt and recalculates sufficiency. A one-shot green run cannot close W-B.

## Construction evidence discipline

Every functional commit must update applicable rows in:
- `RC8-CAPABILITY-CLOSURE-MATRIX.md`
- `RC8-REQUIREMENT-TRACEABILITY-MATRIX.md`

with:
- code paths/commit
- automated tests/CI
- bank Reality evidence when available
- product projection/page
- RC7 regression IDs

No broad PASS without scoped evidence.

## Authoritative-input hold

Exact final wording/severity for `GAP-ADD-03`, `GAP-ADD-06`, `GAP-ADD-10` remains unavailable in Git. Keep `OPEN_INPUT`; never fabricate it.