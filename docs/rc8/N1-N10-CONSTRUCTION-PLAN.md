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
| N8 | Failure Diagnosis / Recovery | Diagnosis + deterministic GapRouter + repair/re-execution |
| N9 | Defect Evidence Closure | first-class defect lifecycle |
| N10 | Mission Evidence / Global Convergence | independent test sufficiency / product quality / release decision |

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

### N1 Reality Snapshot — CODE + CI VERIFIED

Commits `4ecfa51...`, `bd352b9...` implemented immutable `RealitySnapshot`, `CapabilitySnapshot`, `RealityBlocker`, PostgreSQL persistence and cross-platform tests. CONFIGURED/INSTALLED does not imply VERIFIED.

### N2 Requirement adoption — CODE + CI VERIFIED

Existing requirement analysis/sufficiency is adopted into MissionNode delivery semantics. Worker green is recomputed against Center authority. Real HTTP repair tests collapse worker+Center green projections into one final verdict per Stage attempt.

### N3 Code adoption — NODE WORKERS + WINDOWS/LINUX CI VERIFIED

Center-controlled traceability ingestion exists with deterministic Browser Network runtime authority, CodeGraph/source and SQL source policy, LLM candidate-only semantics, and worker verification-upgrade rejection. Commits through `a34ab82...` add fail-closed real `CODE_ANALYSIS` and `CODE_SUFFICIENCY` node workers, wire both into the autonomous dispatcher, require explicit CodeGraph configuration, emit observation/Evidence/R1 only, and preserve Center verification/sufficiency authority. Current-head Windows and Ubuntu `frozen-code-denominator` checks passed. This closes N3 node-runtime adoption, not bank reality.

### N4 Test Design adoption — CODE + CI VERIFIED FOUNDATION

Risk/TestDesign/DesignSufficiency are adopted into MissionNode delivery contracts. Design-denominator strengthening remains part of later end-to-end sufficiency work.

### N5 PreparedAttempt — CODE + WINDOWS/LINUX CI VERIFIED

PreparedAttempt implements SELECTED -> VERIFIED -> RESERVED -> FRESH -> PREPARED with terminal RELEASED/QUARANTINED, one current PreparedAttempt per `(run, case, attempt)`, fresh 4A binding, data freshness, reservation, environment/route binding, execution fail-closed gate and PostgreSQL persistence.

### N6 Executable Readiness — CODE + WINDOWS/LINUX CI VERIFIED

N6 implements N5-bound executable readiness: FrozenCase -> Driver/Script -> Fixture/Binding -> Assertion -> EvidenceCollector. States are BUILT->VERIFIED->READY with invalidation. READY has no business PASS meaning. The Mission Planner now orders N5 `PRECONDITION_DATA_PREP` before N6 `EXECUTABLE_SPEC`; the older ledger ordering warning is retired by Git truth.

### N7 Coverage Denominator — CODE + WINDOWS/LINUX CI VERIFIED

Versioned CoverageDenominatorSnapshot/CoverageObligation/CoverageReceipt/LayerReopen, zero-denominator prohibition and stale-100%-receipt invalidation are implemented. COVERED_FAIL counts as tested while product quality can fail; BLOCKED prevents coverage closure.

### N8 Failure Diagnosis / GapRouter — CODE + WINDOWS/LINUX CI VERIFIED

Center-owned failure diagnosis and deterministic routing are implemented. Center route authority is covered by regression; legacy routing must not supersede Center truth.

### N9 Defect Evidence Closure — CODE + WINDOWS/LINUX CI VERIFIED

PRODUCT-route-only defect entry and evidence-backed defect lifecycle are implemented. TEST_FAIL alone cannot create a defect.

### N10 Global Convergence — CODE + WINDOWS/LINUX CI VERIFIED

Center-owned convergence separates TestSufficiencyDecision, ProductQualityAssessment, ReleaseRecommendation and ResidualRisk. Report generation cannot create convergence.

### SINGLE_NODE N1–N10 autonomous readiness — FAIL-CLOSED GAP EXPOSED

Commits `a09dcfa1...` and `61614885...` added an explicit full N1–N10 Stage denominator to the node runtime. The node reports `RC8_NODE_AUTONOMOUS_PARTIAL`, `n1_n10_autonomous_ready=false`, and the missing Stage list until every required Stage has a real node worker. It must not advertise full autonomy from Center services/adapters alone.

Current real node-worker coverage is now:

- SCOPE_INTAKE
- REQUIREMENT_ANALYSIS
- REQUIREMENT_SUFFICIENCY
- CODE_ANALYSIS
- CODE_SUFFICIENCY
- APPLICABLE_LAYER_EXECUTION

Therefore the next construction work is N4 node-runtime adoption: RISK_TEST_MODEL, TEST_DESIGN and DESIGN_SUFFICIENCY. No SINGLE_NODE PASS may be claimed before the denominator closes with real Evidence.

## 6. Current construction checkpoint ledger

| Item | Checkpoint | Evidence / next action |
|---|---|---|
| Plan persistence | DONE | this file is navigation; Git/CI remain authoritative |
| P0-0 Cross-platform Director baseline | CI_VERIFIED | `287db525...` |
| P0-1 Adoption Spine | CI_VERIFIED | `39811f4...` |
| P0-2 Review + Center Gate | CI_VERIFIED | `00e019b...` |
| N1 RealitySnapshot | CI_VERIFIED | `4ecfa51...` + Windows fix `bd352b9...` |
| N2 Requirement adoption | INTEGRATION_FOUNDATION | broader mission proof pending |
| N3 Code adoption | NODE_WORKERS_CI_VERIFIED | through `a34ab82...`; CODE_ANALYSIS + CODE_SUFFICIENCY autonomous adoption, current-head Windows/Ubuntu targeted PASS |
| N4 Design adoption | CI_VERIFIED_FOUNDATION | **next: RISK_TEST_MODEL/TEST_DESIGN/DESIGN_SUFFICIENCY real node workers** |
| N5 PreparedAttempt | CI_VERIFIED | node-worker/full-loop proof pending |
| N6 Executable Readiness | CI_VERIFIED | N5-before-N6 planner order repaired; node-worker proof pending |
| N7 Coverage Engine | CI_VERIFIED | node worker exists; full-loop proof pending |
| N8 Diagnosis/GapRouter | CI_VERIFIED | Center authority regression exists; node/full-loop proof pending |
| N9 Defect Closure | CI_VERIFIED | full-loop proof pending |
| N10 Global Convergence | CI_VERIFIED | full-loop proof pending |
| SINGLE_NODE runtime foundation | PARTIAL / FAIL-CLOSED | N3 workers adopted; N4/N5/N6/N8/N9/N10 Stage workers still missing |
| DISTRIBUTED runtime foundation | CODE_EXISTS | multi-node N1–N10 proof pending |
| dsh-node runtime adapter | CODE_EXISTS | bank reality pending |
| dsh-agent-teams process adapter | CODE_EXISTS | bank reality pending |
| Director election/failover | CI_VERIFIED_FOUNDATION | bank reality pending |
| BANK_REALITY_VERIFIED | NO | requires actual in-bank probes |
| RELEASE_READY | NO / HOLD | release gates not satisfied |

## 7. Remaining ordered construction sequence

Do **not** manufacture P4/full-loop PASS from Center-only services or adapters. Continue in this order:

1. Wire N4 RISK_TEST_MODEL/TEST_DESIGN/DESIGN_SUFFICIENCY node workers with denominator/evidence gates.
2. Wire N5 PRECONDITION_DATA_PREP node worker using current PreparedAttempt/fresh-auth authority.
3. Wire N6 EXECUTABLE_SPEC node worker bound to current N5 PreparedAttempt.
4. Wire remaining N8/N9/N10 Stage execution/review paths without moving final authority out of Center.
5. `test(rc8): prove n1-n10 single-node autonomous loop` with R1 Evidence and no missing Stage denominator.
6. `test(rc8): prove n1-n10 distributed autonomous loop`.
7. Bank field reality validation: actual DSH/model, actual dsh-agent-teams bridge, controlled Browser Network, fresh 4A login/re-login, CodeGraph, Maven/JUnit, CAT/log where applicable, DB/SQL.

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

> **SINGLE_NODE adoption N4:** wire real `RISK_TEST_MODEL`, `TEST_DESIGN` and `DESIGN_SUFFICIENCY` workers into the autonomous node dispatcher with denominator/evidence gates. Workers may emit candidate observations/Evidence only; Center retains final verification/sufficiency authority. Do not add Stage names to `_AUTONOMOUS_STAGES` until their workers and targeted Windows/Linux tests prove real contracts. Keep `BANK_REALITY_VERIFIED=NO` and Release HOLD.
