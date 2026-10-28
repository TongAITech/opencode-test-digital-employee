# RC8 N1–N10 Construction Plan

> Status: ACTIVE CONSTRUCTION SOURCE OF TRUTH  
> Branch: `work/rc8`  
> Semantic contract: `RC-AUTONOMOUS-TEST-LOOP@1.0.0`  
> Release status: **HOLD** until integration and bank-reality gates pass.  
> Truth priority: **Git/HEAD/CI/R1/Evidence > this navigation ledger**.

## 1. Frozen relationship

N1–N10 define **what the autonomous testing mission must accomplish and when it is complete**. RC8 defines **how the work is orchestrated, placed, executed, evidenced, persisted, recovered and gated**.

```text
Mission
  -> MissionNode (N1..N10)
      -> existing MissionStage(s)
          -> WorkItem
              -> Attempt
                  -> ExecutionNode / dsh-node
                      -> node-local dsh-agent-team
                          -> Agent
                              -> Tool / Skill
                                  -> Evidence
                                      -> R1 + PostgreSQL
                                          -> Center deterministic gate
```

Terminology is frozen:

- `MissionNode`: logical N1–N10 autonomous-test node.
- `ExecutionNode`: physical/virtual dsh-node (office PC / 信创 Linux node).
- Center has no AI/model dependency.
- Director is an AI-capable dsh-node runtime role and may not execute domain work.
- Existing SINGLE_NODE and DISTRIBUTED modes remain one architecture with different placement policy.

## 2. N1–N10 mapping

| Mission Node | Meaning | Existing / adopted RC8 stage semantics |
|---|---|---|
| N1 | Reality / Environment Recon | SCOPE_INTAKE + RealitySnapshot/CapabilitySnapshot |
| N2 | Requirement Analysis | REQUIREMENT_ANALYSIS + REQUIREMENT_SUFFICIENCY |
| N3 | Code Analysis | CODE_ANALYSIS + CODE_SUFFICIENCY + TraceGraph/CodeGraph |
| N4 | Test Design | RISK_TEST_MODEL + TEST_DESIGN + DESIGN_SUFFICIENCY |
| N5 | Test Data / Preconditions | PRECONDITION_DATA_PREP + PreparedAttempt |
| N6 | Script Build / Readiness | EXECUTABLE_SPEC + ExecutableReadiness |
| N7 | Coverage-Driven Execution Closure | APPLICABLE_LAYER_EXECUTION + CoverageDenominator |
| N8 | Failure Diagnosis / Recovery | FAILURE_COVERAGE_EVALUATION + deterministic GapRouter + repair/re-execution |
| N9 | Defect Evidence Closure | DEFECT_CLOSURE_OBSERVATION + Center defect lifecycle |
| N10 | Mission Evidence / Global Convergence | MISSION_SUFFICIENCY + REPORT_RELEASE + Center convergence |

## 3. Non-negotiable invariants

1. `CENTER_HAS_NO_AI_DEPENDENCY`.
2. `DIRECTOR_IS_A_DSH_NODE_RUNTIME_ROLE`.
3. `DIRECTOR_MUST_NOT_EXECUTE_DOMAIN_WORK` / `DIRECTOR_DOMAIN_EXECUTION_FORBIDDEN`.
4. R1 Event Stream is runtime truth; PostgreSQL is durable truth; Redis is coordination only.
5. WorkItem COMPLETED != Stage COMPLETED != MissionNode PASS.
6. PLAN_COMPLETE != TEST_SUFFICIENT.
7. Agent/Team/Worker/Director cannot self-declare final PASS or SUFFICIENT.
8. MissionNode PASS requires Director review acceptance **and** Center deterministic gate.
9. Missing evidence/dimensions are UNKNOWN; denominator cannot shrink silently.
10. `0/0 != 100%`; N/A requires reason + Evidence.
11. Active blocking Gap prevents sufficiency/convergence where applicable.
12. No fake execution; execution PASS requires real runtime Evidence.
13. Java change requires CodeGraph evidence for N3 completion.
14. Page→API runtime verification requires controlled Browser Network Evidence; no guessed routes.
15. Repo/Mapper→SQL/Table requires explicit source/SQL evidence; no guessed tables.
16. LLM inference is candidate-only and cannot upgrade verification state.
17. N5 uses fresh auth/data/precondition bindings; historical 4A cookie fallback is forbidden.
18. TEST_FAIL != DEFECT; only N8 PRODUCT classification enters N9.
19. Test sufficiency, product quality, and release recommendation are independent outputs.
20. Report generation never manufactures `MISSION_CONVERGED`.
21. Capability-based runtime compatibility; no exact version pinning.
22. Cloud CI never equals `BANK_REALITY_VERIFIED`.

## 4. Definition of Done

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

Never use parent/old CI to claim current-head PASS. A plan, UI, adapter, mock or cloud test is not bank reality.

## 5. Implemented construction waves

### P0-0 — Cross-platform Director baseline — DONE

Commit `287db525...` fixed the Windows `:memory:` R1 test portability defect without weakening the append-only runtime-truth contract. Director lifecycle Windows/Linux targeted CI passed.

### P0-1 — N1–N10 Adoption Spine — DONE

Commit `39811f4...` added first-class MissionNode N1–N10 semantics above existing Stage/WorkItem runtime. Stage execution is retained; no second state machine/PASS authority was created. Windows/Linux targeted CI passed.

### P0-2 — Director Review + Center MissionNode Gate — DONE

Commit `00e019b...` implemented AgentTeams -> READY_FOR_DIRECTOR_REVIEW -> DirectorReviewAccepted -> CenterDeterministicGate -> MissionNode PASS. Worker/Team/Director cannot directly set final MissionNode PASS.

### N1–N10 node-runtime adoption — CODE + WINDOWS/LINUX CI VERIFIED

N1–N10 required Stage denominator is now explicitly frozen at 15 stages. Real autonomous dispatcher workers exist for SCOPE_INTAKE, REQUIREMENT_ANALYSIS, REQUIREMENT_SUFFICIENCY, CODE_ANALYSIS, CODE_SUFFICIENCY, RISK_TEST_MODEL, TEST_DESIGN, DESIGN_SUFFICIENCY, PRECONDITION_DATA_PREP, EXECUTABLE_SPEC, APPLICABLE_LAYER_EXECUTION, FAILURE_COVERAGE_EVALUATION, DEFECT_CLOSURE_OBSERVATION, MISSION_SUFFICIENCY and REPORT_RELEASE. `db528fad...` freezes the full denominator so readiness cannot become green by deleting a required Stage from both runtime sets. Current-head Windows/Linux denominator/readiness CI passed.

This closes **worker/adoption readiness only**. It does not prove one mission traverses N1–N10 end-to-end with canonical R1/Evidence, does not prove distributed placement, and does not prove bank reality. N8/N9/N10 observation workers retain Center-only route/defect/convergence/release authority; REPORT_RELEASE remains HOLD-only on the node.

## 6. Current construction checkpoint ledger

| Item | Checkpoint | Evidence / next action |
|---|---|---|
| Plan persistence | DONE | this file is navigation; Git/CI remain authoritative |
| P0-0 Cross-platform Director baseline | CI_VERIFIED | `287db525...` |
| P0-1 Adoption Spine | CI_VERIFIED | `39811f4...` |
| P0-2 Review + Center Gate | CI_VERIFIED | `00e019b...` |
| N1 RealitySnapshot | CI_VERIFIED | immutable reality/capability foundation; bank reality pending |
| N2 Requirement adoption | NODE_WORKERS_CI_VERIFIED | analysis + sufficiency workers adopted |
| N3 Code adoption | NODE_WORKERS_CI_VERIFIED | CODE_ANALYSIS + CODE_SUFFICIENCY; CodeGraph remains bank-reality gated |
| N4 Design adoption | NODE_WORKERS_CI_VERIFIED | RISK_TEST_MODEL + TEST_DESIGN + DESIGN_SUFFICIENCY adopted |
| N5 PreparedAttempt | NODE_WORKER_CI_VERIFIED | PRECONDITION_DATA_PREP adopted; fresh 4A bank proof pending |
| N6 Executable Readiness | NODE_WORKER_CI_VERIFIED | EXECUTABLE_SPEC adopted; real Maven/JUnit bank proof pending |
| N7 Coverage Engine | NODE_WORKER_CI_VERIFIED | APPLICABLE_LAYER_EXECUTION adopted; full-loop proof pending |
| N8 Diagnosis/GapRouter | NODE_WORKER_CI_VERIFIED | FAILURE_COVERAGE_EVALUATION adopted; Center route authority retained |
| N9 Defect Closure | NODE_WORKER_CI_VERIFIED | DEFECT_CLOSURE_OBSERVATION adopted; Center defect authority retained |
| N10 Global Convergence | NODE_WORKERS_CI_VERIFIED | MISSION_SUFFICIENCY + REPORT_RELEASE adopted; Center convergence/release authority retained |
| SINGLE_NODE runtime denominator | CLOSED / CI_VERIFIED | `db528fad...`; next: one-mission N1–N10 R1/Evidence full-loop proof |
| SINGLE_NODE N1–N10 full-loop | NOT_PROVEN | **next construction slice**; no synthetic/happy-path PASS |
| DISTRIBUTED N1–N10 full-loop | NOT_PROVEN | after SINGLE_NODE proof |
| dsh-node runtime adapter | CODE_EXISTS | bank reality pending |
| dsh-agent-teams process adapter | CODE_EXISTS | bank reality pending |
| Director election/failover | CI_VERIFIED_FOUNDATION | bank reality pending |
| BANK_REALITY_VERIFIED | NO | requires actual in-bank probes |
| RELEASE_READY | NO / HOLD | release gates not satisfied |

## 7. Remaining ordered construction sequence

Do **not** manufacture full-loop PASS from Center-only services, adapters, static worker registration, mocks, or synthetic handlers. Continue in this order:

1. `test(rc8): prove n1-n10 single-node autonomous loop`: one Mission must traverse the frozen 15-Stage denominator through real dispatcher/worker contracts, produce Attempt-bound canonical R1 events and Evidence/ArtifactManifest references, preserve Director review + Center deterministic MissionNode authority, and fail closed on missing/stale Evidence. Synthetic stage-complete handlers are not sufficient.
2. Add targeted Windows/Linux CI for the SINGLE_NODE proof and repair any current-head failures before promotion.
3. `test(rc8): prove n1-n10 distributed autonomous loop`: same semantic denominator/Evidence authority with multi-node placement and recovery; no second state machine.
4. Bank field reality validation: actual DSH/model, actual dsh-agent-teams bridge, controlled Browser Network, fresh 4A login/re-login, CodeGraph, Maven/JUnit, CAT/log where applicable, DB/SQL.

## 8. Resume protocol

Every session/guard run must:

1. Read latest `work/rc8` HEAD.
2. Read this plan from the same HEAD.
3. Read commits after the latest checkpoint.
4. Read current-head CI/check-runs; never infer PASS from older commits.
5. Fix red CI before adding features.
6. Pick the earliest unfinished item whose dependencies are satisfied.
7. Modify real code/tests; commit/push to `work/rc8` lease-safely.
8. Check current-head CI and fix failures before claiming CI_VERIFIED.
9. Update this ledger after meaningful progress.
10. Keep `BANK_REALITY_VERIFIED=NO` until real bank evidence exists.

If the same construction slice is already actively progressing, do not start duplicate competing work.

## 9. Immediate next action

> **SINGLE_NODE N1–N10 full-loop proof:** build a real integration proof around the production autonomous dispatcher and worker contracts. The proof must demonstrate one mission's WorkItem→Attempt→Evidence→R1 chain across the frozen 15-Stage denominator and must exercise Center/Director authority boundaries rather than replacing them with a synthetic always-green handler. Missing Evidence, stale scope, active blockers, or unavailable runtime capability must remain fail-closed. Only after current-head Windows/Linux CI passes may SINGLE_NODE full-loop be promoted. Keep `BANK_REALITY_VERIFIED=NO` and Release HOLD.
