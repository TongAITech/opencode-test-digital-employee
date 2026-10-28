# RC7.2 Construction Plan / Checkpoint Ledger

Status: ACTIVE CONSTRUCTION TRUTH

Every construction session MUST first read current `work/rc7.2` HEAD, same-HEAD CI/check-runs, `docs/rc7.2/00-BASELINE-AND-READ-ME.md` through `05-AGENTTEAMS-WORKER-LEASE-CONTRACT.md`, and this ledger. Chat history or stale SHAs never override repository/R1/CI truth.

## 1. Current checkpoint

```yaml
branch: work/rc7.2
design_baseline_sha: a3426e306abf967ab822d44508127c3891c8e91e
latest_phase5_qualified_code_head_sha: f7214d9c6ff7bbd3cb65f2d43b63816b677e75c1
latest_phase5_qualified_ci_run: 40715463547
phase:
  phase0_reality_baseline: COMPLETE
  phase1_canonical_domain_model: CI_PASS
  phase2_n1_n10_state_machine: CI_PASS
  phase3_sufficiency_gates: CI_PASS
  phase4_adaptive_task_decomposer: CI_PASS
  phase5_fresh_worker_reviewer_handoff: CI_PASS
  phase6_diagnosis_recovery_orchestration: NOT_STARTED
field_evidence: NOT_YET_FIELD_VALIDATED
release_status: CONSTRUCTION_ONLY
next_atomic_step: PHASE6_DIAGNOSIS_RECOVERY_CONTRACT_TESTS_FIRST
```

`CI_PASS` means repository-level contract/regression qualification only. It does not mean in-bank Field validation.

## 2. Frozen source contracts

Read in this exact order:

1. `00-BASELINE-AND-READ-ME.md`
2. `01-AUTONOMOUS-TEST-RUNTIME-DESIGN.md`
3. `02-CONSTRUCTION-CONTRACT.md`
4. `03-N1-N10-RUNTIME-STATE-MACHINE-CONTRACT.md`
5. `04-ADAPTIVE-TASK-DECOMPOSER-CONTRACT.md`
6. `05-AGENTTEAMS-WORKER-LEASE-CONTRACT.md`
7. `06-RC7.1-REALITY-BASELINE.md`
8. this ledger

## 3. Phase 0 — Reality Baseline

Status: `COMPLETE`

- commit `6fd2d40323e8872d89c5e165025652d2b69a2018`
- RC7.1 inheritance, eight structural GAPs, ReleaseBatch-root invariant, same-R1/no-shadow-runtime, Session != Truth and Worker STRICT were frozen.

Field validation: `NO`.

## 4. Phase 1 — Canonical Domain Model

Status: `CI_PASS`

Delivered:

- ReleaseBatch is the canonical business root.
- N1-N10 MissionNode, NodeDelivery, NodeGate, BackEdge, ImpactSet and NodeTransition persist as first-class R1 truth.
- TestObligation preserves ReleaseBatch/Requirement/SST/Application/business/risk/test-level/oracle lineage.
- ETU persists planning/cohesion/split lineage.
- existing `rc7_task` remains WorkItem truth; existing `execution_attempt` remains Attempt truth.
- WorkItemAttemptBinding links ETU -> Task -> Attempt -> worker/session/lease refs.
- existing RC7 Gap is reused; no duplicate gap store.
- cross-entity lineage prevents orphan coverage-driven obligations/ETUs.

Key commits include `028460fa...`, `4256819a...`, `712a5220...`, `be66fbf8...`.

Field validation: `NO`.

## 5. Phase 2 — N1-N10 Runtime State Machine

Status: `CI_PASS`

Qualified code head: `0fdd6ef62101ba837bb623091c6ac3bbadef2e5a`
Qualified run: `40693161338`

Delivered:

- exactly N1-N10 persisted MissionNodes.
- direct PASS forbidden; PASS requires NodeDelivery + NodeGate(PASS).
- forward transition requires PASS and non-STALE mandatory upstream truth.
- conflicting same-version deliveries rejected.
- N7 failure -> explicit DIAGNOSIS -> N8.
- N8 persists semantic Gap + BackEdge + Transition.
- provider/capability/resource failures remain separate from SUT defects.
- UNKNOWN never auto-PASS.
- ImpactSet drives explicit/safe-fallback STALE propagation.
- STALE truth blocks N7 dispatch.
- coverage-only cannot produce N10 CONVERGED.
- restart/replay reconstructs runtime from R1, not chat history.

TDD red run `40692350064` exposed and drove fixes for delivery-conflict ordering and explicit DIAGNOSIS semantics.

Field validation: `NO`.

## 6. Phase 3 — N2-N6 Sufficiency / Readiness Gates

Status: `CI_PASS`

Qualified head: `af2de6d8d902647438c5be71b099d2929f0879a9`
Qualified run: `40709689484`

Delivered:

- N2 deterministic Requirement/SST/BR/SR/TR/business-rule/role/state/negative/boundary/permission/data-rule sufficiency.
- explicit not-applicable requires reason + evidence; unresolved unknowns block PASS.
- N3 deterministic Requirement/SST -> changed code -> API/DTO/Service/DB/dependency/reverse mapping with Git + CodeGraph evidence.
- N4 rejects orphan cases, lineage mismatches, TBD/UNKNOWN, missing precondition/steps/oracle/evidence and shallow HIGH-risk design.
- N5 requires resolved/verified/reserved data strategy and cleanup semantics.
- N6 requires executable target/tool/input/data/assertion/oracle/evidence/capability/resource contract; executor guessing is blocked.
- SufficiencySnapshot persists in same R1.
- deterministic failures create canonical RC7 Gap.
- reviewer identity is audited but reviewer prose cannot override deterministic failure.

TDD RED:
- head `e48957695a368eed9499cbaa36326b8e6709dff3`, run `40693906157`.

Key fixes:
- `cd1d0d08...` initial gate service.
- `8c8fe758...` canonical `rc7_evidence` binding.
- `af2de6d8...` isolated tests use real upstream Delivery + PASS Gate, no production bypass.

Field validation: `NO`.

## 7. Phase 4 — Adaptive Task Decomposer

Status: `CI_PASS`

Qualified code head: `74946709560b85cef03f01a594a873901712bc71`
Qualified run: `40712471496`

Same-head qualification:

- RC7.2 contracts Python 3.8: PASS
- RC7.2 contracts Python 3.11: PASS
- inherited RC7 regression Python 3.8: PASS
- runtime compile: PASS
- structured JUnit diagnostics retained as workflow artifacts.

### 7.1 First slice — canonical obligation-to-ETU decomposition

Tests-first commit: `e62884a4...`
Implementation commit: `409f6824...`
Qualified run: `40710514513`

Implemented:

- ReleaseBatch/Requirement/SST/TestObligation remains the planning root.
- unrelated SSTs never merge merely because API/tool/data are the same.
- homogeneous same-obligation work can merge.
- 20+ heterogeneous cases split into small lineage-preserving ETUs rather than one large Round.
- mixed L3/L4 separates by level/tool/browser semantics.
- completed Case IDs are not rescheduled by default.
- same frozen input/config produces deterministic ETU identity/order.
- unmapped coverage produces investigation routing, never orphan Case/ETU.
- mapped coverage repairs/reprioritizes the existing canonical obligation.

### 7.2 Second slice — runtime feedback and resource isolation semantics

Tests-first commit: `29fd59b0...`
Implementation commit: `9a1ff61b...`
Qualified run: `40711052921`

Implemented:

- exclusive mutable data resource conflicts force isolated ETUs.
- shared reference data does not force artificial splitting.
- auth role and browser context are explicit cohesion dimensions.
- high-cost, near-zero coverage yield creates `LOW_COVERAGE_YIELD` replan signal and priority penalty.
- PRODUCT_DEFECT/VALID_TEST_FAILURE/environment/provider failures are not misclassified as brute-force low-yield.
- browser ETUs declare browser-context/auth-role capability requirements.

### 7.3 Third slice — multidimensional priority and R1 explainability

Tests-first commit: `82c8f701...`
Implementation chain:

- `b039f36e...` explicit multi-dimensional planning signals and per-obligation priority explanation.
- `f6bf9f22...` canonical R1 decomposition snapshot persistence.
- `28f584de...` Python 3.8 compatibility correction.
- `47a5635b...` CI JUnit diagnostic artifact retention.
- `74946709...` replay compatibility fix: planning snapshot field `cases` renamed to `planning_cases` because inherited R1 treats `cases` as a legacy TEST_CASE batch field.

Real failure evidence from run `40712263302`:

- 52 RC7.2 contract tests executed; 51 PASS, 1 FAIL.
- exact failure: R1 replay interpreted planning snapshot `cases` as legacy `TEST_CASE_UPSERTED`, then failed `MISSING_OR_INVALID_TC_ID`.
- fix preserved legacy replay semantics and moved RC7.2 planner data to a non-reserved field rather than weakening old compatibility.

Implemented priority dimensions are explicit and explainable:

```text
business_risk
requirement_priority
sst_criticality
change_impact
historical_defect_density
uncovered_changed_code
coverage_yield_estimate
production_blast_radius
blocked_downstream_work
execution_cost
resource_contention
uncertainty_reduction
```

Additionally:

- coverage_gap and historical low-yield penalty remain visible feedback components.
- planning snapshot persists config version, planning inputs, weights, per-obligation priority explanation, routes, replan reasons and emitted ETU IDs.
- generated ETUs persist through CanonicalRC72Repository in the same R1.
- planning truth survives replay without session/chat history.

### 7.4 Phase 4 exit decision

`PHASE4 = CI_PASS`

The decomposer defines *what work units exist*. It still does not schedule Workers or acquire leases; those belong to Phase 5/7.

Field validation: `NO`. No real in-bank ReleaseBatch has yet exercised RC7.2 adaptive decomposition.

## 8. Phase 5 — Fresh Worker / Fresh Reviewer / Session Rotation / Captain Handoff

Status: `CI_PASS`

Qualified code head: `f7214d9c6ff7bbd3cb65f2d43b63816b677e75c1`
Qualified run: `40715463547`

Same-head qualification:

- RC7.2 contracts Python 3.8: PASS — `64 passed`.
- RC7.2 contracts Python 3.11: PASS — `64 passed`.
- inherited RC7 regression Python 3.8: PASS — `492 passed, 1 skipped`.
- runtime compile: PASS.
- JUnit diagnostics retained as workflow artifacts.

Tests-first commits:

- `11fd135a...` freezes fresh worker/session rotation/reviewer/captain-handoff contracts.
- `f3d73db3...` freezes signed runtime worker + real DSH session binding contracts.

Implementation commits:

- `c4aa4391...` implements fresh worker lifecycle, rotation/checkpoint, fresh reviewer and Captain handoff.
- `112a391a...` binds lifecycle identity to signed DSH worker assignment, Attempt and real DSH session truth.
- `f7214d9c...` normalizes attempt lease references at the canonical boundary.

Delivered:

1. Role remains durable semantic identity while Worker/Session are disposable execution identities.
2. Default execution is one ETU -> one fresh Worker/Session; closed sessions cannot silently bind another ETU.
3. Fresh worker context is built only from canonical R1 refs; chat history/transcript is explicitly absent.
4. Rotation policy evaluates workitem/step/token/tool-call/compaction/retry/runtime/context-pressure thresholds.
5. Rotation persists R1 checkpoint truth before closing the old session and creating the fresh session.
6. Fresh Reviewer is a distinct worker/session and receives NodeDelivery + criteria + evidence rather than executor transcript.
7. Captain handoff persists checkpoint truth, reuses the same Mission/Team and fails closed on identity mismatch.
8. Worker checkpoint, Captain handoff and takeover survive R1 replay.
9. Signed `DshHeadlessWorkerLauncher` assignment is bound to lifecycle session, existing `rc7_task`, Attempt and TaskLease.
10. Real DSH session identity upgrades the WorkItemAttemptBinding to RUNNING; worker/session/lease identity mismatch fails closed.
11. All worker, rotation, reviewer, handoff, runtime-assignment and attempt-binding truth remains queryable from the same R1.

Phase 5 does not broaden Worker permissions and does not implement Browser/Model/Data resource leasing; those remain Phase 7 responsibilities.

Field validation: `NO`. No real in-bank AgentTeams/DSH mission has yet exercised RC7.2 Fresh Worker/session rotation/Captain handoff.

## 9. Phase 6 — Independent Diagnosis / Recovery Orchestration

Status: `NOT_STARTED`

Next step MUST be tests-first and must reuse the Phase 2 failure taxonomy/back-edge semantics rather than create a second diagnosis state machine.

First slice must prove:

1. N7 failure produces immutable failure evidence and dispatches a fresh diagnosis Worker rather than allowing executor self-repair.
2. diagnosis Worker receives Attempt/Execution/Evidence/ExecutableContract refs only; it does not inherit executor chat history.
3. deterministic diagnosis classifies at least `ENVIRONMENT_GAP`, `REQUIREMENT_GAP`, `ANALYSIS_GAP`, `TEST_DESIGN_GAP`, `TEST_DATA_GAP`, `EXECUTABLE_GAP`, `PRODUCT_DEFECT`, provider/capability/resource failures and `UNKNOWN`.
4. classified analysis/design/data/executable gaps create canonical Gap + BackEdge and return to N3/N4/N5/N6 respectively.
5. PRODUCT_DEFECT routes to N9 without mutating the original execution Attempt.
6. provider/capability/resource failures stay infrastructure/runtime failures and are not recorded as SUT defects.
7. UNKNOWN cannot auto-PASS and must remain blocked/diagnosis-pending with evidence.
8. after upstream repair, affected downstream delivery/case/data/executable assets become STALE and a new Attempt is required for re-execution.
9. diagnosis/recovery decisions and replacement Attempt lineage survive R1 replay.

## 10. Remaining phases

- Phase 6: independent diagnosis/recovery orchestration.
- Phase 7: CapabilityBroker, BrowserPool/BrowserLease, DataLease, model failover.
- Phase 8: Libra feedback through Requirement/SST/TestObligation and N10 convergence.
- Phase 9: Journey Teaching/Compiler/Replay/Benchmark.
- final: Windows + Linux + clean-unpack + real in-bank Field Acceptance.

## 11. Anti-drift rule

Future sessions MUST NOT infer completion from this file alone. Always inspect:

```text
current work/rc7.2 HEAD
+ same-HEAD source
+ same-HEAD CI/check-runs
+ frozen 00-05 contracts
+ this ledger
+ R1/evidence where applicable
```

If they differ, live repository/R1/CI truth wins and the ledger must be corrected in the same construction turn.
