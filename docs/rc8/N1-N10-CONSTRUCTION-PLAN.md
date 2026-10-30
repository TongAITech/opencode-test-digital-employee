# RC8 N1–N10 Construction Plan

> Status: ACTIVE CONSTRUCTION SOURCE OF TRUTH  
> Branch: `work/rc8`  
> Semantic contract: `RC-AUTONOMOUS-TEST-LOOP@1.0.0`  
> Release status: **HOLD** until integration and bank-reality gates pass.  
> Truth priority: **Git/HEAD/CI/R1/Evidence > this navigation ledger**.

## 1. Frozen relationship

N1–N10 define **what the autonomous testing mission must accomplish and when it is complete**. RC8 defines **how the work is orchestrated, placed, executed, evidenced, persisted, recovered and gated**.

```text
Mission -> MissionNode (N1..N10) -> MissionStage(s) -> WorkItem -> Attempt
 -> ExecutionNode / dsh-node -> dsh-agent-team -> Agent -> Tool / Skill
 -> Evidence -> R1 + PostgreSQL -> Center deterministic gate
```

Terminology is frozen: `MissionNode` is logical N1–N10; `ExecutionNode` is a physical/virtual dsh-node. Center has no AI/model dependency. Director is an AI-capable dsh-node runtime role and may not execute domain work. SINGLE_NODE and DISTRIBUTED remain one architecture with different placement policy.

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

`CODE_EXISTS -> UNIT_VERIFIED -> WINDOWS_CI_VERIFIED -> LINUX_CI_VERIFIED -> INTEGRATION_VERIFIED -> R1_EVIDENCE_VERIFIED -> REALITY_VERIFIED -> BANK_REALITY_VERIFIED`.

Never use parent/old CI to claim current-head PASS. A plan, UI, adapter, mock or cloud test is not bank reality.

## 5. Implemented construction waves

P0-0 Cross-platform Director baseline, P0-1 N1–N10 Adoption Spine and P0-2 Director Review + Center MissionNode Gate are DONE/CI_VERIFIED. N1–N10 required Stage denominator is frozen at 15 stages and real autonomous dispatcher workers exist for all 15. `db528fad...` freezes the denominator so readiness cannot become green by deleting a required Stage from both runtime sets. This closes worker/adoption readiness only.

SINGLE_NODE proof infrastructure now drives the production `AutonomousWorkerDispatcher` boundary and fails closed unless one `test_run_id` observes the frozen 15 stages in order with distinct WorkItem IDs, distinct Attempt IDs and canonical `artifact:` Evidence references. `4e70eb4...` repaired the Python 3.8 CI harness; its Ubuntu and Windows 2022 current-head proof-contract checks both passed. `adf5372...` added the Center/R1 truth gate and its Windows/Linux checks passed. `abc99ebe...` further closes stale-truth holes by requiring ArtifactManifest and R1 terminal-event identities to bind to the same TestRun/WorkItem/Attempt and by rejecting reused artifact/R1 identities.

Production durable truth is wired through the Center PostgreSQL repositories plus canonical R1 ledger. The 15-stage durable-truth fixture and composed dispatcher-observation + durable-truth gate are covered by the SINGLE_NODE Windows 2022 and Ubuntu workflow. Later hardening separated production-component identity from production causality, so a boundary double or pre-seeded durable fixture cannot be promoted to production proof. The Center claim-provenance slice preserves Center claim provenance through `DispatchOutcome` and makes the production full-loop gate fail closed unless each executed claim carries Center's PostgreSQL/capability/Redis-lease/PostgreSQL-mirror provenance and the terminal idle observation carries Center's no-compatible-ready-work provenance. Current-head Windows 2022 and Ubuntu proof checks passed at `537073bb...`. This advances the production-causality boundary but **does not yet prove production claim/lease caused all 15 real Stage workers to generate the durable records**; that remains the next boundary and SINGLE_NODE full-loop remains NOT_PROVEN.

Production-causality preflight now fails closed before traversal if the target `test_run_id` already has any durable Attempt in Center PostgreSQL. `623401a9...` added the production truth-reader preflight, `09ed1086...` made the production integration runner require it, `aae0c6d9...` added positive/negative regression coverage, and `88bfbadd...` placed that coverage in the SINGLE_NODE Windows/Linux workflow. Both current-head checks passed. This prevents a pre-seeded Attempt from being stitched to a later Center claim, but it is still only a necessary causality condition: the production-driven 15-worker full-loop itself remains NOT_PROVEN.

Durable causality hardening now also exposes the complete PostgreSQL Attempt identity set for a TestRun. `7cc4143c...` added the production truth-reader primitive, `2c0cfc37...` froze positive/fail-closed regression behavior, and `7a84424d...` placed the regression in the SINGLE_NODE Windows/Linux workflow. Both current-head checks passed. The primitive rejects empty TestRun IDs and duplicate durable Attempt identities so the forthcoming production-driven harness can require exact equality between Center-issued/observed lease identities and the complete durable Attempt set rather than merely proving that expected Attempts exist. This is a necessary anti-stitching condition only; production causality and the SINGLE_NODE full-loop remain NOT_PROVEN.

The composed production integration runner now invokes that exact Attempt/lease-set binding after dispatcher traversal and before durable Evidence promotion. `5c902c12...` wires the production-only call and `49b09d90...` adds regression coverage proving the preflight and post-traversal binding are both invoked while `production_causality_verified` remains false. At `ee7c1168...`, both current-head Windows 2022 and Ubuntu `single-node-full-loop-proof` checks completed successfully. This closes the integration-binding CI checkpoint only; it does not prove that production Center claim/lease caused the 15 real workers to create durable truth, so SINGLE_NODE full-loop remains NOT_PROVEN.

## 6. Current construction checkpoint ledger

| Item | Checkpoint | Evidence / next action |
|---|---|---|
| Plan persistence | DONE | this file is navigation; Git/CI remain authoritative |
| P0-0 Cross-platform Director baseline | CI_VERIFIED | `287db525...` |
| P0-1 Adoption Spine | CI_VERIFIED | `39811f4...` |
| P0-2 Review + Center Gate | CI_VERIFIED | `00e019b...` |
| N1 RealitySnapshot | CI_VERIFIED | immutable reality/capability foundation; bank reality pending |
| N2 Requirement adoption | NODE_WORKERS_CI_VERIFIED | analysis + sufficiency workers adopted |
| N3 Code adoption | NODE_WORKERS_CI_VERIFIED | CodeGraph remains bank-reality gated |
| N4 Design adoption | NODE_WORKERS_CI_VERIFIED | risk/model/design/sufficiency adopted |
| N5 PreparedAttempt | NODE_WORKER_CI_VERIFIED | fresh 4A bank proof pending |
| N6 Executable Readiness | NODE_WORKER_CI_VERIFIED | real Maven/JUnit bank proof pending |
| N7 Coverage Engine | NODE_WORKER_CI_VERIFIED | full-loop proof pending |
| N8 Diagnosis/GapRouter | NODE_WORKER_CI_VERIFIED | Center route authority retained |
| N9 Defect Closure | NODE_WORKER_CI_VERIFIED | Center defect authority retained |
| N10 Global Convergence | NODE_WORKERS_CI_VERIFIED | Center convergence/release authority retained |
| SINGLE_NODE runtime denominator | CLOSED / CI_VERIFIED | `db528fad...` |
| SINGLE_NODE proof contract | WINDOWS/LINUX CI_VERIFIED | contract only, not full-loop proof |
| SINGLE_NODE Center/R1 truth gate | WINDOWS/LINUX CI_VERIFIED | strict TestRun/WorkItem/Attempt/Artifact/R1 identity binding; stale/reused truth fails closed |
| SINGLE_NODE production durable truth reader | WINDOWS/LINUX CI_VERIFIED | Center PostgreSQL + canonical R1 reader; no plan/UI/mock truth fallback |
| SINGLE_NODE composed durable integration gate | WINDOWS/LINUX CI_VERIFIED | dispatcher observation must match durable Center/R1 truth; production causality remains separate |
| SINGLE_NODE Center claim provenance | WINDOWS/LINUX CI_VERIFIED | `64d4e4f...`→`537073bb...`; current-head Windows 2022 + Ubuntu proof checks passed; provenance is verified but production causality is still not proven |
| SINGLE_NODE production causality preflight | WINDOWS/LINUX CI_VERIFIED | `623401a9...`→`88bfbadd...`; target TestRun must have zero durable Attempts before production traversal; necessary condition only, not full-loop proof |
| SINGLE_NODE durable Attempt-set causality primitive | WINDOWS/LINUX CI_VERIFIED | `7cc4143c...`→`7a84424d...`; exact complete durable Attempt identity set is available for post-run equality checks; necessary condition only, not full-loop proof |
| SINGLE_NODE Attempt/lease-set integration binding | WINDOWS/LINUX CI_VERIFIED | `5c902c12...`→`49b09d90...`→`ee7c1168...`; exact post-run durable Attempt-set equality is enforced before Evidence promotion; current-head Windows 2022 + Ubuntu proof checks passed; full-loop still NOT_PROVEN |
| SINGLE_NODE N1–N10 full-loop | NOT_PROVEN | next: production claim/lease must drive the 15 real Stage workers and create the verified durable records; no pre-seeded fixture promotion |
| DISTRIBUTED N1–N10 full-loop | NOT_PROVEN | after SINGLE_NODE proof |
| dsh-node runtime adapter | CODE_EXISTS | bank reality pending |
| dsh-agent-teams process adapter | CODE_EXISTS | bank reality pending |
| Director election/failover | CI_VERIFIED_FOUNDATION | bank reality pending |
| BANK_REALITY_VERIFIED | NO | requires actual in-bank probes |
| RELEASE_READY | NO / HOLD | release gates not satisfied |

## 7. Remaining ordered construction sequence

1. Complete the SINGLE_NODE real integration fixture around production Center claim/lease, `AutonomousWorkerDispatcher`, real Stage workers, ArtifactManifest/Evidence upload and R1 event persistence. Production claim/lease and workers—not test pre-seeding—must create the durable records subsequently accepted by the production truth reader. Require the post-run complete durable Attempt identity set to equal the 15 Center-issued/observed lease identities exactly. The proof must retain exact TestRun/WorkItem/Attempt/Artifact/R1 identity continuity and Center claim provenance; stale/missing/reused/extra truth and active blockers fail closed. Preserve Director review + Center deterministic MissionNode authority.
2. Run targeted Windows/Linux CI and repair current-head failures before promotion.
3. Prove the same semantic denominator/Evidence authority in DISTRIBUTED placement/recovery; no second state machine.
4. Bank field reality validation: actual DSH/model, dsh-agent-teams bridge, controlled Browser Network, fresh 4A login/re-login, CodeGraph, Maven/JUnit, CAT/log and DB/SQL where applicable.

## 8. Resume protocol

Every session/guard run must read latest `work/rc8` HEAD, read this plan from that same HEAD, read commits after the latest checkpoint, and read current-head CI/check-runs. Fix red CI first. Pick the earliest unfinished dependency-satisfied item. Modify real code/tests, commit/push lease-safely, inspect current-head CI, update this ledger after meaningful progress, and keep `BANK_REALITY_VERIFIED=NO` until real bank evidence exists. If the same construction slice is already actively progressing, do not start duplicate competing work.

## 9. Immediate next action

> **SINGLE_NODE production-driven full-loop proof:** Center claim-provenance, production-causality preflight, complete durable Attempt-set primitive, and composed Attempt/lease-set integration binding are Windows/Linux CI verified. Now use production Center claim/lease to drive the frozen 15 real Stage workers for one fresh Mission/TestRun. Those workers must themselves create the Attempt, ArtifactManifest/Evidence and canonical R1 terminal records that the existing production durable-truth reader and composed integration gate verify. Do not pre-seed durable truth in the fixture and do not promote a boundary double. Retain Director review and Center deterministic authority; missing/stale/reused/extra Evidence, active blockers or unavailable runtime capability fail closed. Only current-head Windows/Linux CI may promote the full-loop checkpoint. Keep `BANK_REALITY_VERIFIED=NO` and Release HOLD.