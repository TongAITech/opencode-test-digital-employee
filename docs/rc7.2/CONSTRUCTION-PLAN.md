# RC7.2 Construction Plan / Checkpoint Ledger

Status: ACTIVE CONSTRUCTION TRUTH

This file is the handoff ledger for RC7.2 implementation. Every construction session MUST first read the current branch HEAD and then re-read `docs/rc7.2/00-BASELINE-AND-READ-ME.md` through `05-AGENTTEAMS-WORKER-LEASE-CONTRACT.md` plus this ledger. Chat history and stale SHAs never override repository truth.

## 1. Current checkpoint

```yaml
branch: work/rc7.2
design_baseline_sha: a3426e306abf967ab822d44508127c3891c8e91e
latest_phase2_qualified_code_head_sha: 0fdd6ef62101ba837bb623091c6ac3bbadef2e5a
latest_phase2_qualified_ci_run: 40693161338
ledger_commit_sha: SELF
phase:
  phase0_reality_baseline: COMPLETE
  phase1_canonical_domain_model: CI_PASS
  phase2_n1_n10_state_machine: CI_PASS
  phase3_sufficiency_gates: NOT_STARTED
field_evidence: NOT_YET_FIELD_VALIDATED
release_status: CONSTRUCTION_ONLY
next_atomic_step: PHASE3_SUFFICIENCY_GATE_CONTRACT_TESTS
```

The qualified code HEAD above passed RC7.2 contracts on Python 3.8 and 3.11 and the inherited RC7 source suite on Python 3.8 in the same workflow run. This ledger commit is documentation-only and must not be interpreted as Field qualification. Future sessions must always re-read the actual branch HEAD and same-HEAD CI/check-runs.

## 2. Frozen source contracts

Read in this exact order before modifying runtime behavior:

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

Commit:

- `6fd2d40323e8872d89c5e165025652d2b69a2018` — `docs(rc7.2): capture RC7.1 reality baseline`

Delivered truth:

- RC7.1 inheritance and compatibility boundary recorded.
- 8 structural GAPs recorded.
- ReleaseBatch business-root invariant recorded.
- No-shadow-runtime / same-R1 requirement recorded.
- Session != Truth and Worker STRICT invariants recorded.

Field claim: none. This phase records observed reality; it does not claim RC7.2 field qualification.

## 4. Phase 1 — Canonical Domain Model

Status: `CI_PASS`

### 4.1 Implemented clauses

- ReleaseBatch is a persisted canonical business root.
- N1-N10 are persisted canonical MissionNode semantics and remain distinct from Agent roles/sessions.
- `MissionNodeRecord`, `NodeDelivery`, `NodeGate` are first-class R1 entities.
- Gate records explicit reviewer worker/session identity.
- `TestObligation` requires ReleaseBatch/Requirement/SST/Application/business/risk/test-level/oracle lineage.
- `ExecutionTaskUnit` is a persisted schedulable unit with planning snapshot, cohesion score/explanation and split lineage.
- 3-8 cases is implemented as a default target, not a blind hard constant: >8 requires explicit justification; 1-2 remains legal for expensive/high-risk work.
- Existing canonical RC7 `Gap` is reused; no second RC7.2 gap store exists.
- `BackEdge` is persisted and binds source delivery, Gap, return node and invalidation refs.
- `ImpactSet` is persisted in the same R1 and records explicit or safe-fallback downstream invalidation scope.
- `NodeTransition` is persisted and explicitly distinguishes forward/diagnosis/back-edge/blocked/human-gate/resume semantics.
- Existing `rc7_task` is reused as WorkItem; no duplicate WorkItem store was created.
- Existing inherited `execution_attempt` remains Attempt truth; no duplicate Attempt store was created.
- `WorkItemAttemptBinding` durably links ETU -> existing Task -> existing Attempt -> worker/session -> task/capability/resource lease refs.
- All RC7.2 entities append/query/replay through the inherited canonical R1 event stream/projection.
- Cross-entity lineage is checked before R1 persistence to prevent orphan coverage-driven obligations/ETUs.

### 4.2 Main implementation files

- `rc7_runtime/rc72_domain.py`
- `rc7_runtime/rc72_linkage.py`
- `rc7_runtime/rc72_truth.py`
- `rc7_runtime/rc72_repository.py`
- `rc7_runtime/rc72_impact.py`
- `rc7_runtime/rc72_impact_truth.py`
- `tests/test_rc72_phase1_domain_contract.py`
- `tests/test_rc72_phase1_impact_contract.py`
- `.github/workflows/rc7.2-construction.yml`

### 4.3 Construction commits

- `b7ed8cc97f82e9f5cfce742260f4c711f6c40b42` — canonical domain skeleton
- `6c116f268803929264ad13807f4c8580efa577e8` — R1 persistence integration
- `e4d280dc868a5af4862b938f1783bb6142f067e1` — ReleaseBatch lineage repository
- `433f42fbe9fd9872bb17a5c12621069623be2761` — Phase 1 contract tests
- `244e923c6cc9e75181d0bdcc1090799303b70db3` — RC7.2 construction qualification workflow
- `451e08ed4e86747cb72694e8170967233beb93e8` — initial public API exposure
- `028460fa9b21ee406af55e4e1f9838c2bf250f8b` — frozen N1-N10 contract alignment
- `4256819a37a3c31946a974a31a93121809d25559` — Transition and existing Task/Attempt linkage model
- `712a522026902b0c43ced3f667028c8d051744e5` — public Transition/Attempt-linkage API
- `be66fbf86994a02ef86a7f69067159a45c32adca` — persisted ImpactSet contract and replay qualification

### 4.4 Phase 1 exit decision

`PHASE1 = CI_PASS`

Reason:

- canonical entities exist and persist/replay through the same R1;
- ReleaseBatch/Requirement/SST lineage is enforced;
- N1-N10 node/delivery/gate/gap/back-edge/impact/transition objects exist;
- ETU is bound to existing WorkItem/Attempt truth rather than a parallel runtime;
- inherited RC7 regression remains green at latest Phase 2 qualified HEAD, which contains all Phase 1 code.

Open qualification:

- real in-bank ReleaseBatch mission has not yet exercised these RC7.2 entities;
- therefore `FIELD_VALIDATED = NO`.

## 5. Phase 2 — N1-N10 Runtime State Machine

Status: `CI_PASS`

### 5.1 Implemented clauses

- Bootstrapping a ReleaseBatch creates exactly ten persisted N1-N10 MissionNodes; N1 starts READY and remaining nodes start NOT_STARTED.
- MissionNode lifecycle is explicit and persisted.
- Direct `PASS` is forbidden; PASS is reachable only through a persisted `NodeDelivery + NodeGate(PASS)` path.
- Active delivery version and conflicting same-version producer detection are enforced.
- Forward N1-N7 transitions require source PASS plus persisted PASS gate and mandatory upstream PASS truth.
- STALE/non-PASS mandatory upstream nodes block downstream execution readiness.
- N7 execution failure no longer allows inline redesign to masquerade as execution; it persists an explicit `DIAGNOSIS` transition to N8.
- N8 diagnosis requires its own accepted delivery/gate before semantic routing.
- N8 classification persists canonical `Gap + BackEdge + NodeTransition` for N1/N2/N3/N4/N5/N6/N9 routes.
- Provider/capability/resource classes are distinguished as runtime recovery/broker/resource-manager actions rather than SUT defects.
- `UNKNOWN` diagnosis cannot auto-pass.
- Explicit ImpactSet propagation marks dependent MissionNode/TestObligation/ETU truth STALE.
- Safe fallback invalidation exists when explicit dependency edges are incomplete and is recorded as `SAFE_FALLBACK` rather than silently guessed.
- STALE upstream/ETU truth blocks N7 dispatch.
- Release convergence requires all mandatory business/runtime/evidence conditions; coverage target alone cannot produce CONVERGED.
- Restart/replay reconstructs current node state from R1 without chat/session history.
- Existing RC7.1 state-machine code remains intact; RC7.2 logic is additive in its own service over the same R1.

### 5.2 Main implementation files

- `rc7_runtime/rc72_state_machine.py`
- `rc7_runtime/rc72_phase2_truth.py`
- `tests/test_rc72_phase2_state_machine_contract.py`

### 5.3 Construction commits and red/green evidence

- `8eee85411fbb90a696a9a06b7463a3b2e5c108ba` — Phase 2 contract tests first (intentional TDD red before implementation)
- `161b64ab3f1a648dbbdd316d0460db7a69550526` — initial persisted N1-N10 state-machine implementation
- run `40692350064` — real red qualification: 25/27 Phase contracts passed; exactly two failures found:
  1. conflicting same-version Delivery was masked by lifecycle state check;
  2. N7->N8 was typed as generic BLOCKED instead of explicit DIAGNOSIS.
- `c325626943edebb9d5bb3ab5e64701a1bb81e9a4` — add explicit DIAGNOSIS transition kind
- `e4b31de1a5d74ba116ef08ca9f0052f2dd2dca8b` — register Phase 2 DIAGNOSIS semantics in the same canonical transition validator
- `0fdd6ef62101ba837bb623091c6ac3bbadef2e5a` — fix delivery conflict ordering and N7->N8 DIAGNOSIS transition

### 5.4 Same-HEAD CI evidence

Workflow: `RC7.2 Construction Qualification`

Run `40693161338`, head `0fdd6ef62101ba837bb623091c6ac3bbadef2e5a`: `SUCCESS`

Same-head jobs:

- RC7.2 construction contracts Python 3.8: PASS
- RC7.2 construction contracts Python 3.11: PASS
- inherited RC7 source suite Python 3.8: PASS
- runtime compile qualification: PASS

This proves repository-level Phase 2 behavior and inherited RC7 compatibility. It does not prove in-bank Field behavior.

### 5.5 Phase 2 exit decision

`PHASE2 = CI_PASS`

`FIELD_VALIDATED = NO`

No claim is made yet that a real in-bank ReleaseBatch has exercised N1-N10 semantic back-edges or stale propagation.

## 6. Phase 3 — Sufficiency / Readiness Gates

Status: `NOT_STARTED`

The next implementation must start with executable contract tests and then implement deterministic/evidence-backed gates for N2-N6.

Required first slice:

1. N2 Requirement sufficiency cannot PASS with missing mandatory Requirement/SST business-rule/role/state/negative/boundary/permission/data-rule evidence.
2. N3 Code Analysis cannot PASS without Requirement/SST -> change -> API/DTO/Service/DB/dependency mapping and CodeGraph `graph_evidence` for affected code.
3. N4 Test Design cannot PASS with orphan cases, missing Requirement/SST/TestObligation lineage, missing Oracle, unresolved TBD/UNKNOWN, or missing negative/boundary/risk obligations where applicable.
4. N5 Test Data cannot PASS until each executable case has a resolved DataRef/precondition strategy and required discovery/construct/verify/reserve state.
5. N6 Executable Readiness cannot PASS until endpoint/tool route/input/data/assertion/oracle/evidence requirements are executable and capability/resource requirements are declared.
6. Gate failure must create deterministic gap facts/return-node guidance; it must not rely on reviewer prose alone.
7. N7 dispatch must continue to be impossible while any mandatory N2-N6 gate is non-PASS/STALE.

## 7. Remaining construction phases

- Phase 3: executable N2-N6 sufficiency/readiness gates.
- Phase 4: adaptive TestObligation -> ETU decomposition/scoring/split/merge/reprioritization.
- Phase 5: Fresh Worker/Fresh Reviewer/session rotation/Captain handoff.
- Phase 6: independent diagnosis and recovery orchestration.
- Phase 7: CapabilityBroker, BrowserPool/BrowserLease, DataLease, model failover.
- Phase 8: Libra feedback routing through Requirement/SST/TestObligation and N10 convergence.
- Phase 9: Journey Teaching/Compiler/Replay/Benchmark.
- final: Windows + Linux + clean-unpack + real in-bank Field Acceptance.

## 8. Anti-drift rule

A future session MUST NOT infer completion from this file alone. It must inspect:

```text
current work/rc7.2 HEAD
+ same-HEAD source
+ same-HEAD CI/check-runs
+ frozen 00-05 contracts
+ this ledger
+ R1/evidence where applicable
```

If any differ, live repository/R1/CI truth wins and this ledger must be updated in the same construction turn.
