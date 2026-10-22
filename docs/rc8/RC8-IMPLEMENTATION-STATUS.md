# RC8 Implementation Status

Branch: `work/rc8`
RC7 source/capability base: `delivery/rc7-default-enhancements@2c2eecbf18dde97ecdb10b65264e8c5c2a88ef72`
RC7 verified transport/toolset reference: `delivery/rc7-internal-transport-0bbb8239@af59027e7227fa1861fea95c6d05ff73aefb8572`
Current construction line: `W1 foundation + first vertical autonomous slice`
Overall status: `IN_PROGRESS`

## Mandatory interpretation correction

Tool Reality Verification MUST NOT be promoted into stage/layer/mission completion.

Current scoped truth:
- `TOOL:MAVEN_JUNIT = BANK_REALITY_VERIFIED`
- `TOOL:CODEGRAPH = BANK_REALITY_VERIFIED` based on target-bank real structural-query execution/evidence supplied in the acceptance session
- `STAGE:CODE_ANALYSIS = IMPLEMENTED/CI_VERIFIED_PARTIAL; BANK_FULL_ANALYSIS_PENDING`
- `LAYER:L1 = AUTONOMOUS_CLOSED_LOOP_NOT_IMPLEMENTED`
- `MISSION:TEST_SUFFICIENT = NO`
- `RELEASE = HOLD`

A green Maven/JUnit attempt, CodeGraph query success, installed plugin, CI contract double, WorkItem completion, or generated report does not imply test sufficiency.

The binding anti-simplification contract is:
- `docs/rc8/RC8-NO-DISCOUNT-DELIVERY-CONTRACT.md`

## Frozen inputs
- `docs/rc8/RC8-MASTER-CONTRACT.md`
- `docs/rc8/RC8-ARCHITECTURE-BASELINE.md`
- `docs/rc8/RC8-PRODUCT-BASELINE.md`
- `docs/rc8/RC7-TO-RC8-GAP-MATRIX.md`
- `docs/rc8/RC8-NO-DISCOUNT-DELIVERY-CONTRACT.md`
- `docs/rc8/RC8-REQUIREMENT-TRACEABILITY-MATRIX.md`
- `docs/rc8/RC8-W1-SINGLE-NODE-VERTICAL-SLICE.md`
- `packaging/rc8/RC7_OFFLINE_TOOLSET_MANIFEST.json`

## RC7 inheritance baseline
RC8 intentionally keeps two RC7 authorities:
1. source/capability lineage: `2c2eecb`;
2. offline transport/toolset completeness reference: `af59027`.

Do not collapse these into one source. Capability code migrates from the newer source line while node offline payload completeness is checked against the verified transport line/manifest.

RC7 certification facts carried into RC8:
- Reality Certification CLOSED
- RC8_ENTRY_READY=YES
- not FULLY_AUTONOMOUS_TEST_COMPLETE
- L1/L2/L3 READY in RC7 certification semantics, but this MUST NOT be copied as RC8 autonomous-loop completion
- L4/L5/L7 PARTIAL
- L6 BASELINE_ONLY
- TEST_PARTIALLY_EXECUTED
- Release HOLD
- 49 raw gaps -> 16 canonical gaps

## W0 status
Implemented and CI-gated:
- canonical Node/TestRun/WorkItem/ProductionBatch/RequirementDeliveryScope identities;
- PLAN and RUNTIME planes separated;
- Director/model claims cannot create runtime truth;
- Evidence contract with hash/provenance/availability/assertion binding;
- capability qualification state machine; VERIFIED requires probe/evidence/time;
- `PLAN_COMPLETE != TEST_SUFFICIENT`;
- canonical R1 runtime ledger with idempotency/conflict/replay/node-sequence gates.

One authoritative-input hold remains: exact final certification wording/severity for `GAP-ADD-03`, `GAP-ADD-06`, `GAP-ADD-10` was not found in current Git sources. Keep `OPEN_INPUT`; never invent it.

## W1 control/runtime foundation
### Center
- Node registration/heartbeat
- capability projection/qualification
- WorkItem register/lease/start/complete
- lease ownership bound to Node, not DSH Session
- late runtime writes rejected after lease release
- central R1 append authorization
- stdlib HTTP transport boundary
- durable Center launcher and smoke check
- restart-persistent W1 fallback for Node/Capability/WorkItem/Artifact metadata

### Node Agent
- stable local Node identity across restart
- outbound-only Center connection
- register/heartbeat/capability/lease/start/runtime/complete clients
- Windows Git Bash + Linux bash launchers
- Windows Chinese/GB18030 output hardening where tool subprocesses require it
- package-external durable node-state direction; versioned package directory must not own permanent node identity

### Artifact Sync
- generic asset protocol for screenshots/logs/scripts/data/skill/knowledge attachments
- manifest -> resumable offset upload -> size/SHA-256 verify -> AVAILABLE
- active WorkItem lease required
- wrong Node rejected
- late completion after WorkItem completion rejected
- zero-byte artifacts supported
- metadata/bytes survive Center restart in the W1 durable fallback

## Maven/JUnit tool capability
### Implemented truth chain
- real `mvn -version` probe; presence alone never VERIFIED
- probe Artifact must reach AVAILABLE before capability VERIFIED
- real Maven subprocess execution
- Actual derives only from fresh Surefire/Failsafe XML plus Maven process result
- stale historical JUnit XML is ignored
- Windows Maven output tolerates UTF-8/GB18030/local encoding without crashing execution
- `maven_returncode != 0` cannot be hidden by green XML
- Actual/stdout/stderr/fresh JUnit XML are uploaded before R1
- WorkItem completes only after evidence and R1 persistence

### Bank Reality result
Target-bank validation proved the execution substrate against the actual bank `cfg-center` project:
- Windows Git Bash execution node
- actual bank Maven
- main/test compile successful after test-source drift was repaired in DSH
- real JUnit/Surefire execution
- `tests=2243`, `failures=0`, `errors=0`, `skipped=8`
- fresh Surefire evidence
- `execution_passed=true`
- capability `VERIFIED`
- R1 `PERSISTENCE_VERIFIED`
- WorkItem `COMPLETED`

Therefore only the scoped tool claim is valid:
`TOOL:MAVEN_JUNIT = BANK_REALITY_VERIFIED`.

This does NOT prove:
- L1 design sufficiency
- ExecutableSpec/script generation
- JaCoCo/coverage.py
- changed-line/branch/method coverage
- coverage gap generation
- failure ownership/RCA
- delta test design
- targeted re-execution
- mutation/assertion strength
- L1 convergence
- TEST_SUFFICIENT

Pure disconnected/offline portability is also still a separate gate because the successful bank run allowed the internal Maven repository.

## CodeGraph tool capability and Code Analysis stage

### Tool-level Bank Reality
Target-bank execution proved real CodeGraph structural work rather than presence/probe only:
- real bank executable
- real Java snapshot/query points
- callers/callees/dependency/impact/context query families
- graph evidence Artifact
- source snapshot/digest binding
- R1 persistence
- WorkItem completion

Valid scoped claim:
`TOOL:CODEGRAPH = BANK_REALITY_VERIFIED`.

### Full Code Analysis is still incomplete
Implemented/under construction:
- Git diff/snapshot authority
- Java change discovery
- iterative structural-query coverage
- structural sufficiency gate
- semantic-request contract
- evidence-reference semantic gate
- DSH headless semantic worker adapter

Still required before `STAGE:CODE_ANALYSIS = BANK_REALITY_VERIFIED`:
- real bank DSH semantic execution over real Git diff + CodeGraph evidence
- semantic change interpretation
- API/service/DB/config/business-state impact where supported by evidence
- risk mapping
- L1-L7 test-impact mapping
- unknown/follow-up query loop
- independent sufficiency evaluation
- additional-query/re-analysis convergence
- final structured code-analysis projection in Center/product

## L1 autonomous closed loop - current truth

Current status:
`LAYER:L1 = AUTONOMOUS_CLOSED_LOOP_NOT_IMPLEMENTED`.

Required implementation before any L1 completion claim:
1. TestCase -> ExecutableSpec contract
2. JUnit/TestNG/pytest script builder
3. script validation
4. Maven/JUnit/pytest real execution
5. JaCoCo / coverage.py adapters
6. Git Diff + CodeGraph + coverage changed-code mapper
7. requirement/risk/verification-point coverage evaluation
8. failure classifier/ownership router
9. RCA and repair routing
10. delta test design
11. delta script generation
12. targeted re-execution
13. coverage recalculation
14. mutation/assertion-strength gate for configured high-risk scope
15. L1 sufficiency evaluator
16. convergence controller
17. Attempt/Evidence/Gap/Defect durable projection
18. product UI visibility
19. real bank mission proof

`mvn returncode == 0 && JUnit failures/errors == 0` is only `EXECUTION_RESULT_GREEN` and must never be used as `L1_PASS`.

## L2-L7 current acceptance posture

Definitions are frozen in `RC8-NO-DISCOUNT-DELIVERY-CONTRACT.md`.

- L2: dedicated Component/Repository/DB loop required; RC7 history exposed weak binding/readback/transaction evidence.
- L3: dedicated API/service loop required; route must be verified, auth/runtime and request/response/assertion/back-end evidence bound.
- L4: dedicated UI/Browser loop required; zero-step/fake execution and awaiting-worker behavior are regression blockers.
- L5: coherent E2E journey required; fragmented L2/L3/L4 green cannot substitute for one traceable business flow.
- L6: performance/capacity/stability; `BASELINE_ONLY` when no authoritative NFR, never fabricate PASS threshold.
- L7: security/authz; scanner availability is only one capability and cannot replace permission/role/security-negative testing.

None of these layers may be globally promoted from inherited RC7 labels without RC8 vertical-loop Reality proof.

## RC7 gaps/regressions that remain mandatory

The 16 canonical gaps remain OPEN until their specific RC8 closure criteria are met. In addition, field regressions must remain explicit tests:
- local self-loop not provably closed
- later-stage gap route-back failure
- unclear 'what was actually tested'
- weak product pages
- knowledge lost with DSH session
- context inflation/session stall/loss
- Director self-execution
- plugin/tool presence mistaken for capability
- CodeGraph not invoked when required
- stale-cookie/manual-history 4A regression
- guessed routes/repeated 404
- weak test data/preconditions
- L4/L5/L7 partial, L6 baseline-only
- incomplete/weak evidence
- backend/product projection drift
- bank package/upgrade/restart failures

## Current implementation priority

Do not continue breadth-first tool verification as the main line.

Priority A: complete one truthful autonomous L1 vertical slice:
`Requirement/Code Risk -> Design -> ExecutableSpec -> Script -> Real Execution -> Coverage -> Evaluate -> Gap/Failure -> Repair/Delta -> Targeted Re-run -> Recalculate -> Converge -> TEST_SUFFICIENT/Defect/HOLD`.

Priority B: complete iterative Requirement Analysis and Code Analysis loops feeding that L1 slice.

Priority C: implement professional L2/L3/L4 loops with DB/API/Browser/4A/route/data realities.

Priority D: L5 coherent E2E.

Priority E: L6/L7 dedicated sufficiency semantics.

Priority F: full L1-L7 mission convergence, product/report/defect/knowledge, multi-node/session recovery and deployment gates.

## Status semantics
- OPEN / OPEN_INPUT: no implementation proof or authoritative input unavailable
- IMPLEMENTED: code exists
- CI_VERIFIED: automated gates pass
- REALITY_VERIFIED / BANK_REALITY_VERIFIED: target-bank real execution/evidence proves the explicitly scoped behavior only
- SUFFICIENT: dedicated evaluator says required coverage/gaps meet policy
- CLOSED: requirement/gap trace complete and no acceptance blocker

Every future status statement MUST include its scope (`TOOL`, `STAGE`, `LAYER`, `MISSION`, `RELEASE`).