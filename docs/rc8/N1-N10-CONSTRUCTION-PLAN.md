# RC8 N1–N10 Construction Plan

> Status: ACTIVE CONSTRUCTION SOURCE OF TRUTH
> Branch: `work/rc8`
> Baseline at plan creation: `965ed36b3558a3fc3ba07ea73beeda3076696956`
> Release status: HOLD until current-head CI, integration, and bank reality gates pass.

## 1. Purpose

This document is the durable construction plan for adopting the frozen RC7.1/RC8 autonomous test semantic contract (`RC-AUTONOMOUS-TEST-LOOP@1.0.0`, N1–N10) into RC8 without replacing the existing RC8 runtime architecture.

The core rule is:

- N1–N10 define **what the autonomous testing mission must accomplish and when it is complete**.
- RC8 defines **how work is orchestrated, scheduled, executed, evidenced, persisted, recovered, and gated**.
- Existing RC8 runtime components are retained: Center, AI Director runtime on dsh-node, ExecutionNode/dsh-node, node-local dsh-agent-teams, MissionGraph stages, WorkItem/Attempt, R1 Event Stream, PostgreSQL, Redis, Evidence, placement/lease/failover, and Center-owned deterministic sufficiency gates.
- Do not create a parallel state machine or a second PASS authority.

## 2. Frozen architecture relationship

```text
Mission
  -> MissionNode (N1..N10)
      -> existing MissionStage(s)
          -> WorkItem
              -> Attempt
                  -> ExecutionNode / dsh-node
                      -> dsh-agent-team
                          -> Agent
                              -> Tool / Skill
                                  -> Evidence
                                      -> R1 + PostgreSQL
                                          -> Center deterministic gate
```

Terminology is frozen to avoid ambiguity:

- `MissionNode`: logical N1–N10 autonomous-test node.
- `ExecutionNode`: physical/virtual dsh-node (office PC / 信创 Linux execution node).

## 3. N1–N10 mapping to existing RC8 stages

| Mission Node | Meaning | Existing RC8 foundation | Change type |
|---|---|---|---|
| N1 | Reality / Environment Recon | SCOPE_INTAKE, capability registry, provider recovery | strengthen |
| N2 | Requirement Analysis | REQUIREMENT_ANALYSIS, REQUIREMENT_SUFFICIENCY | adopt / reuse |
| N3 | Code Analysis | CODE_ANALYSIS, CODE_SUFFICIENCY, TraceGraph/CodeGraph foundations | adopt + strengthen |
| N4 | Test Design | RISK_TEST_MODEL, TEST_DESIGN, DESIGN_SUFFICIENCY | adopt + strengthen |
| N5 | Test Data / Preconditions | PRECONDITION_DATA_PREP | major strengthening |
| N6 | Script Build / Readiness | EXECUTABLE_SPEC | strengthen |
| N7 | Coverage-Driven Execution Closure | APPLICABLE_LAYER_EXECUTION + coverage part of FAILURE_COVERAGE_EVALUATION | refactor semantics |
| N8 | Failure Diagnosis / Recovery | failure part of FAILURE_COVERAGE_EVALUATION + DELTA_REPAIR + TARGETED_REEXECUTION | extract / formalize |
| N9 | Defect Evidence Closure | evidence/defect product goals and persistence foundations | new first-class mission node |
| N10 | Mission Evidence / Global Convergence | MISSION_SUFFICIENCY + REPORT_RELEASE | split convergence from reporting |

## 4. Non-negotiable invariants

1. `CENTER_HAS_NO_AI_DEPENDENCY`.
2. `DIRECTOR_IS_A_DSH_NODE_RUNTIME_ROLE`.
3. `DIRECTOR_MUST_NOT_EXECUTE_DOMAIN_WORK`.
4. R1 Event Stream is runtime truth; PostgreSQL is durable truth; Redis is coordination only.
5. WorkItem COMPLETED != Stage COMPLETED != MissionNode PASS.
6. PLAN_COMPLETE != TEST_SUFFICIENT.
7. Agent/Team/Worker/Director cannot self-declare final PASS or SUFFICIENT.
8. MissionNode PASS requires Director review acceptance **and** Center deterministic gate.
9. Missing evidence/dimensions are UNKNOWN, never silently dropped from denominator.
10. 0/0 != 100%.
11. N/A requires reason + Evidence.
12. Active blocking Gap prevents MissionNode PASS.
13. No fake execution; real execution requires execution evidence.
14. Java change requires CodeGraph evidence for N3 completion.
15. Page->API runtime verification requires controlled browser Network evidence; no guessed routes.
16. N5 uses fresh auth/data/precondition bindings; historical 4A cookie fallback is forbidden.
17. TEST_FAIL != DEFECT. PRODUCT-classified failures enter N9 only after N8 diagnosis.
18. Test sufficiency, product quality, and release recommendation are separate outputs.
19. Existing SINGLE_NODE and DISTRIBUTED execution modes remain one architecture with different placement policies.
20. Capability-based runtime compatibility; do not hard-pin exact tool versions.

## 5. Definition of Done for every construction slice

A slice may advance only through evidence-backed states:

```text
CODE_EXISTS
  -> UNIT_VERIFIED
  -> WINDOWS_CI_VERIFIED
  -> LINUX_CI_VERIFIED
  -> INTEGRATION_VERIFIED
  -> R1_EVIDENCE_VERIFIED
  -> REALITY_VERIFIED (where applicable)
  -> BANK_REALITY_VERIFIED (bank-only capabilities)
```

Rules:

- Never use parent/old CI to claim current HEAD PASS.
- Never use GitHub CI to claim bank reality.
- A plan, design note, UI button, adapter interface, or mocked test is not REALITY_VERIFIED.
- Release remains HOLD until release gates explicitly pass.

## 6. Construction waves

### P0-0 — Restore a clean cross-platform baseline

Goal: make the pre-adoption runtime baseline trustworthy before N1–N10 structural changes.

Current known blocker at plan creation:

- HEAD `965ed36...`
- Director lifecycle Ubuntu check: PASS.
- Director lifecycle Windows check: FAIL because tests use `CentralR1RuntimeLedger(":memory:")`, which is an invalid Windows path.

Scope:

- Fix the cross-platform test/runtime path handling without weakening runtime truth behavior.
- Run targeted Director lifecycle regression on Windows and Linux.
- Freeze the resulting green commit as `RC8_N1N10_ADOPTION_BASELINE`.

Acceptance:

- Current-head Windows targeted CI PASS.
- Current-head Linux targeted CI PASS.
- No architecture behavior change hidden in the portability fix.

### P0-1 — N1–N10 Adoption Spine

Add a first-class semantic layer above existing MissionStages; do not replace stages.

Required model:

- `MissionNodeType` (N1..N10)
- `MissionNodeState`
- `MissionNodeInstance`
- `MissionNodeStageBinding`
- `NodeDeliveryPackage`
- `DirectorReviewReceipt`
- `MissionNodeGateDecision`

Required R1 provenance additions:

- `mission_node_id`
- `mission_node_type`
- `execution_node_id` (physical dsh-node identity; keep distinct from MissionNode)

Acceptance:

- Existing Stage/WorkItem execution still works.
- Every Stage maps deterministically to one MissionNode or an explicitly documented cross-node transition.
- Evidence can be traced: Evidence -> Attempt -> WorkItem -> Stage -> MissionNode -> Mission.
- No duplicate state machine or duplicate final PASS field.

### P0-2 — Unified review and PASS authority

Frozen flow:

```text
AgentTeams
  -> READY_FOR_DIRECTOR_REVIEW
  -> DirectorReviewAccepted
  -> CenterDeterministicGate
  -> MissionNode PASS
```

MissionNode PASS formula:

```text
DirectorReviewAccepted
AND CenterGatePassed
AND EvidenceComplete
AND DenominatorSatisfied
AND NoBlockingGap
AND CurrentAttemptOnly
AND PrerequisitesSatisfied
```

Acceptance:

- Director-generated domain execution evidence is rejected/fail-closed.
- Worker/Team/Director cannot directly set MissionNode PASS.
- Stale attempt evidence cannot satisfy the gate.

### P1-1 — N1 Reality Snapshot Gate

Add:

- `RealitySnapshot`
- `CapabilitySnapshot`
- `RealityBlocker`

N1 verifies current mission reality rather than configuration presence.

Probe examples:

- DSH/model invocation
- dsh-agent-teams smoke
- Browser runtime
- fresh 4A login ability
- CodeGraph
- Maven/JUnit harness
- API route discovery
- DB query capability
- CAT/log access where applicable

Acceptance:

- CONFIGURED/INSTALLED never automatically means VERIFIED.
- Snapshot is versioned/immutable and referenced by downstream N2–N10 work.
- material reality change invalidates/reopens affected downstream state.

### P1-2 — Adopt and strengthen N2/N3/N4

Reuse current stages; do not rewrite them.

N2:

- requirement obligation denominator
- ambiguity/gap evidence
- independent review receipt

N3:

- changed revision binding
- Java change -> CodeGraph required
- controlled Browser Network evidence for Page->API runtime verification
- CodeGraph/source evidence for API->Controller->Service->Repository/Mapper
- explicit mapper/JDBC/ORM/SQL evidence for SQL/Table
- Center Controlled Ingestion -> TraceGraph -> CODE_SUFFICIENCY

N4:

- formal `TestDesignDenominator`
- obligations from requirement, code, risk, layer, interaction
- case contracts carry obligation/risk refs, applicable layers, preconditions, data requirements, steps, oracle/assertions, evidence requirements

Acceptance:

- Existing Center frozen-denominator anti-shrink behavior remains authoritative.
- No CodeGraph evidence => N3 cannot PASS when CodeGraph is required.
- LLM inference remains candidate-only and cannot upgrade verification.

### P1-3 — N5 PreparedAttempt

Add first-class `PreparedAttempt` and lifecycle:

```text
Select -> Verify -> Reserve -> FreshnessCheck -> Bind -> CASE_PREPARED_ATTEMPT
```

Bindings include:

- case_id / attempt_id
- test data
- environment
- fresh auth/4A state
- route binding
- reservation/occupation
- freshness evidence
- cleanup/release/quarantine state

Hard gate:

- no current `PreparedAttempt` => no `TEST_EXECUTION_STARTED`.

Acceptance:

- retries cannot silently reuse stale auth/data from older attempts.
- data reservation/release is auditable.
- fresh 4A policy is enforced at runtime boundary.

### P1-4 — N6 Executable Readiness

Strengthen `EXECUTABLE_SPEC` into an execution contract:

```text
FrozenCase -> Script/Driver -> Fixture/Binding -> Assertion -> EvidenceCollector
```

Acceptance:

- technical build/compile readiness is separated from business assertion PASS.
- executable spec maps back to N4 obligations and N5 PreparedAttempt requirements.

### P2-1 — N7 Coverage Denominator Engine

Add:

- `CoverageDenominatorSnapshot`
- `CoverageObligation`
- `CoverageReceipt`
- `CoverageExpansion`
- `LayerReopen`

Coverage states:

- UNEXECUTED
- READY
- EXECUTING
- COVERED_PASS
- COVERED_FAIL
- BLOCKED
- EXCLUDED_WITH_EVIDENCE

Rules:

- N7 is coverage-driven execution closure, not merely case execution.
- COVERED_FAIL counts as tested coverage but affects product quality.
- denominator expansion invalidates stale 100% receipts and reopens affected layers.

Acceptance:

- Case loop, Layer coverage loop, Cross-layer convergence loop are represented separately.
- L1–L7 execution can be SINGLE_NODE or capability-aware DISTRIBUTED without changing semantics.

### P2-2 — N8 Failure Diagnosis and Deterministic Gap Routing

Add:

- `FailureObservation`
- `FailureClassification`
- `DiagnosticEvidence`
- `GapRouter`
- `RepairWorkOrder`
- `RepairReceipt`
- `SuccessorAttempt`

Classification:

- SCRIPT
- SPEC_DESIGN
- ORACLE
- DATA
- PRECONDITION
- AUTH
- ROUTE
- TOOL
- ENVIRONMENT
- DEPENDENCY
- TRANSIENT
- FLAKY
- PRODUCT
- UNKNOWN

Deterministic routing:

- SCRIPT -> N6
- SPEC_DESIGN / ORACLE -> N4
- DATA / PRECONDITION / AUTH -> N5
- ROUTE source truth -> N3
- ROUTE execution binding -> N6
- TOOL / ENVIRONMENT -> N1 or runtime recovery
- TRANSIENT / FLAKY -> N7 controlled re-execution
- PRODUCT -> N9
- UNKNOWN -> remain in N8 until evidence improves

Acceptance:

- Director may decide repair tactics but cannot arbitrarily redefine Gap ownership.
- PRODUCT failures cannot be retried until green as a substitute for N9 defect handling.

### P2-3 — N9 Defect Evidence Closure

Add first-class lifecycle:

```text
DefectCandidate
 -> IndependentReproduction
 -> Qualification
 -> RCA
 -> Dedup
 -> Impact
 -> Severity
 -> Review
 -> Confirm/File
 -> FixDetected
 -> FixVerification
 -> ImpactRegression
 -> Close/Reopen
```

Acceptance:

- TEST_FAIL != DEFECT.
- only N8 PRODUCT classification can enter N9.
- defect closure requires current fix-verification evidence and impact regression evidence when applicable.

### P3 — N10 Global Convergence

Add `MissionConvergenceService` driven only by R1/durable truth.

Inputs:

- N1–N9 delivery state
- coverage denominators/receipts
- TraceGraph completeness
- execution evidence
- active gaps
- defect disposition
- residual risk

Independent outputs:

- `TestSufficiencyDecision`
- `ProductQualityAssessment`
- `ReleaseRecommendation`
- `ResidualRisk`

Rules:

- `TEST_SUFFICIENCY=SUFFICIENT` may coexist with `PRODUCT_QUALITY=FAIL` and `RELEASE_RECOMMENDATION=NO_GO`.
- `REPORT_RELEASE` occurs only after `MISSION_CONVERGED`; report generation never creates convergence.

### P4 — Reality validation and release gating

Prove both placement policies using the same architecture.

1. SINGLE_NODE reality test
   - Director + N1–N10 logical actors on one AI-capable dsh-node.
   - logical WorkItem/Team/Agent/Attempt/Evidence identities remain separate.

2. DISTRIBUTED reality test
   - Director on an AI-capable node.
   - N1–N10 WorkItems placed capability-aware across at least two execution nodes.
   - node loss -> lease expiry -> re-placement -> stale-attempt rejection.
   - Director loss -> Center re-election in DISTRIBUTED mode.

3. Bank reality probes
   - DSH/model
   - dsh-agent-teams actual interface
   - Browser + controlled Network
   - fresh 4A
   - CodeGraph
   - Maven/JUnit
   - CAT/log where required
   - DB/SQL

Release remains HOLD until required reality receipts are present.

## 7. Ordered commit sequence

Use small evidence-backed commits. Default sequence:

1. `fix(rc8): restore cross-platform director lifecycle baseline`
2. `feat(rc8): add n1-n10 mission node adoption spine`
3. `feat(rc8): add director review and center mission-node gate`
4. `feat(rc8): add n1 reality snapshot gate`
5. `feat(rc8): adopt n2-n4 into mission node delivery contracts`
6. `feat(rc8): add n5 prepared attempt contract`
7. `feat(rc8): strengthen n6 executable readiness contract`
8. `feat(rc8): add n7 coverage denominator engine`
9. `feat(rc8): add n8 diagnostic gap router`
10. `feat(rc8): add n9 defect evidence closure`
11. `feat(rc8): add n10 mission convergence`
12. `test(rc8): prove n1-n10 single-node autonomous loop`
13. `test(rc8): prove n1-n10 distributed autonomous loop`

Do not combine large unrelated waves into one commit.

## 8. Construction checkpoint ledger

Update this section after every meaningful commit. Git/HEAD and CI remain authoritative; this ledger is a navigation aid, not a replacement for evidence.

| Item | Status at plan creation | Evidence / next action |
|---|---|---|
| P0-0 Cross-platform Director baseline | IN_PROGRESS | Windows current-head test failing on `:memory:` path; fix first |
| P0-1 Adoption Spine | NOT_STARTED | next after green baseline |
| P0-2 Review + Center Gate | NOT_STARTED | depends on Adoption Spine |
| N1 RealitySnapshot | NOT_STARTED | existing capability/provider foundations reusable |
| N2 Requirement adoption | PARTIAL_FOUNDATION | reuse existing stages/gates |
| N3 Code adoption | PARTIAL_FOUNDATION | TraceGraph/CodeGraph foundations; controlled ingestion still required |
| N4 Design adoption | PARTIAL_FOUNDATION | existing risk/design stages reusable |
| N5 PreparedAttempt | NOT_STARTED | major new first-class object |
| N6 Executable Readiness | PARTIAL_FOUNDATION | strengthen EXECUTABLE_SPEC |
| N7 Coverage Engine | NOT_STARTED | formal denominator/receipt/reopen missing |
| N8 Diagnosis/GapRouter | PARTIAL_FOUNDATION | recovery runtime exists; semantics missing |
| N9 Defect Closure | NOT_STARTED | first-class mission node/lifecycle missing |
| N10 Global Convergence | PARTIAL_FOUNDATION | mission sufficiency exists; convergence separation required |
| SINGLE_NODE runtime foundation | CODE_EXISTS | preserve |
| DISTRIBUTED runtime foundation | CODE_EXISTS | preserve |
| dsh-node runtime adapter | CODE_EXISTS | preserve; bank reality pending |
| dsh-agent-teams process adapter | CODE_EXISTS | bank reality pending |
| Director election/failover | CODE_EXISTS | current Windows CI must be fixed |
| BANK_REALITY_VERIFIED | NO | P4 |
| RELEASE_READY | NO / HOLD | requires release gates |

## 9. Resume protocol for every future construction session

Every new session/automation run must follow this exact sequence:

1. Read `work/rc8` latest HEAD.
2. Read this plan from the same HEAD.
3. Read recent commits after the checkpoint recorded here.
4. Read current-head CI/check runs; never infer PASS from older commits.
5. Identify the earliest unfinished item whose dependencies are satisfied.
6. Continue only that coherent slice; do not re-plan completed work.
7. Commit/push code and tests.
8. Check current-head CI and fix failures before claiming CI_VERIFIED.
9. Update this checkpoint ledger when the slice materially advances.
10. Keep `BANK_REALITY_VERIFIED=NO` until real bank evidence exists.

If construction is already actively progressing on the same slice, do not create duplicate competing work.

## 10. Immediate next action

At creation of this plan, the next action is fixed:

> **P0-0: repair Windows Director lifecycle portability (`CentralR1RuntimeLedger(":memory:")`), obtain current-head Windows + Linux targeted PASS, then freeze the resulting SHA as the N1–N10 adoption baseline and begin P0-1 Adoption Spine.**
