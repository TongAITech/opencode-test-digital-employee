# RC7.2 Construction Plan / Checkpoint Ledger

Status: ACTIVE CONSTRUCTION TRUTH

This file is the handoff ledger for RC7.2 implementation. Every construction session MUST first read the current branch HEAD and then re-read `docs/rc7.2/00-BASELINE-AND-READ-ME.md` through `05-AGENTTEAMS-WORKER-LEASE-CONTRACT.md` plus this ledger. Chat history and stale SHAs never override repository truth.

## 1. Current checkpoint

```yaml
branch: work/rc7.2
design_baseline_sha: a3426e306abf967ab822d44508127c3891c8e91e
qualified_code_head_sha: 712a522026902b0c43ced3f667028c8d051744e5
ledger_commit_sha: SELF
phase:
  phase0_reality_baseline: COMPLETE
  phase1_canonical_domain_model: CI_PASS
  phase2_n1_n10_state_machine: NOT_STARTED
field_evidence: NOT_YET_FIELD_VALIDATED
release_status: CONSTRUCTION_ONLY
next_atomic_step: PHASE2_CONTRACT_TESTS_THEN_STATE_MACHINE_IMPLEMENTATION
```

The `qualified_code_head_sha` above is the code HEAD that passed Phase 1 CI before this ledger-only commit. The ledger commit itself must also pass construction CI; later sessions must always re-read the actual branch HEAD instead of assuming this SHA remains current.

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
- `NodeTransition` is persisted and explicitly distinguishes forward/back-edge/blocked/human-gate/resume transitions.
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
- `tests/test_rc72_phase1_domain_contract.py`
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

### 4.4 CI evidence

Workflow: `RC7.2 Construction Qualification`

- run `40689797894` on `028460fa...`: `SUCCESS`
- run `40690976915` on `4256819a...`: `SUCCESS`
- run `40691059287` on `712a522...`: `SUCCESS`

Latest qualified run `40691059287` proved on the same code HEAD:

- RC7.2 phase contract suite on Python 3.8: PASS
- RC7.2 phase contract suite on Python 3.11: PASS
- inherited RC7 source suite on Python 3.8: PASS
- compile qualification: PASS

CI PASS is not FIELD VALIDATION.

### 4.5 Phase 1 exit decision

`PHASE1 = CI_PASS`

Reason:

- canonical entities exist;
- they persist/replay through the same R1;
- ReleaseBatch/Requirement/SST lineage is enforced;
- N1-N10 node/delivery/gate/back-edge/transition objects exist;
- ETU is bound to existing WorkItem/Attempt truth rather than a parallel runtime;
- inherited RC7 regression remains green.

Open qualification:

- real in-bank ReleaseBatch mission has not yet exercised these new RC7.2 entities;
- therefore `FIELD_VALIDATED = NO`.

## 5. Phase 2 — N1-N10 Runtime State Machine

Status: `NOT_STARTED`

The next implementation MUST start with executable contract tests derived from `03-N1-N10-RUNTIME-STATE-MACHINE-CONTRACT.md`, then implement runtime behavior.

Minimum first slice:

1. legal MissionNode lifecycle transitions;
2. PASS reachable only through a persisted PASS NodeGate;
3. forward transition blocked when mandatory upstream delivery/node is STALE or non-PASS;
4. N7 execution failure transitions into N8 rather than allowing N7 to silently redesign/retry forever;
5. N8 failure classification creates semantic routing to N1/N2/N3/N4/N5/N6/N9 as applicable;
6. semantic back-edge persists Gap + BackEdge + NodeTransition;
7. ImpactResolver marks affected downstream NodeDelivery/TestObligation/ETU or executable refs STALE;
8. STALE nodes/assets cannot dispatch new execution work;
9. Agent text such as "completed" cannot create PASS without Gate/Evidence truth;
10. restart/replay recovers current node state from R1 without chat history.

Implementation should be additive, preferably in a dedicated RC7.2 state-machine service layered over `CanonicalRC72Repository`, while preserving inherited RC7.1 `state_machine.py` compatibility.

## 6. Open construction gaps

These are expected future phases, not Phase 1 failures:

- Phase 2: N1-N10 state-machine behavior and stale propagation.
- Phase 3: executable N2-N6 sufficiency/readiness gates.
- Phase 4: adaptive TestObligation -> ETU decomposition/scoring/split/merge/reprioritization.
- Phase 5: Fresh Worker/Fresh Reviewer/session rotation/Captain handoff.
- Phase 6: independent diagnosis and recovery orchestration.
- Phase 7: CapabilityBroker, BrowserPool/BrowserLease, DataLease, model failover.
- Phase 8: Libra feedback routing through Requirement/SST/TestObligation and N10 convergence.
- Phase 9: Journey Teaching/Compiler/Replay/Benchmark.
- final: Windows + Linux + clean-unpack + real in-bank Field Acceptance.

## 7. Anti-drift rule

A future session MUST NOT infer completion from this file alone. It must inspect:

```text
current work/rc7.2 HEAD
+ same-HEAD source
+ same-HEAD CI/check-runs
+ this ledger
+ R1/evidence where applicable
```

If any differ, live repository/R1/CI truth wins and this ledger must be updated in the same construction turn.
