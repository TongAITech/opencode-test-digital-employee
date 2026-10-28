# RC7.2 Construction Plan / Checkpoint Ledger

Status: **REPOSITORY_CONSTRUCTION_CI_PASS / FIELD_VALIDATION_PENDING**

This ledger is the canonical construction status index. Every future session MUST first read current `work/rc7.2` HEAD, same-HEAD CI/check-runs, frozen `docs/rc7.2/00-BASELINE-AND-READ-ME.md` through `05-AGENTTEAMS-WORKER-LEASE-CONTRACT.md`, this ledger, and `CURRENT-CHECKPOINT.md`.

Chat history, stale SHAs and old summaries never override repository/R1/CI truth.

## 1. Current checkpoint

```yaml
branch: work/rc7.2
design_baseline_sha: a3426e306abf967ab822d44508127c3891c8e91e
latest_repository_qualified_code_head_sha: d43f233ace9c691f881a8b5e0d5be23257b9c5f5
latest_repository_qualified_ci_run: 40737549865
latest_repository_qualification:
  rc72_contracts_python_3_8: 206_passed
  rc72_contracts_python_3_11: 206_passed
  inherited_rc7_python_3_8: 492_passed_1_skipped
  runtime_compile: PASS
phase:
  phase0_reality_baseline: COMPLETE
  phase1_canonical_domain_model: CI_PASS
  phase2_n1_n10_state_machine: CI_PASS
  phase3_sufficiency_gates: CI_PASS
  phase4_adaptive_task_decomposer: CI_PASS
  phase5_fresh_worker_reviewer_handoff: CI_PASS
  phase6_diagnosis_recovery_orchestration: CI_PASS
  phase7_resource_capability_runtime: CI_PASS
  phase8_coverage_release_convergence: CI_PASS
  phase9_journey_teaching: CI_PASS_FIELD_PENDING
field_evidence: NOT_YET_FIELD_VALIDATED
release_status: REPOSITORY_CONSTRUCTION_CI_PASS_FIELD_PENDING
bank_final: NO
next_atomic_step: PLATFORM_QUALIFICATION_AND_FIELD_ACCEPTANCE_BASELINE
```

`CI_PASS` proves repository/runtime contracts only. It does not mean in-bank Field validation or BANK_FINAL.

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
9. `CURRENT-CHECKPOINT.md`

## 3. Phase ledger

### Phase 0 — RC7.1 Reality Baseline

Status: `COMPLETE`

- baseline commit: `6fd2d40323e8872d89c5e165025652d2b69a2018`
- froze RC7.1 inheritance, structural GAPs, ReleaseBatch business-root semantics, same-R1/no-shadow-runtime, Session != Truth and Worker STRICT boundaries.
- Field validation: `NO`.

### Phase 1 — Canonical Domain Model

Status: `CI_PASS`

Delivered canonical ReleaseBatch, N1-N10 MissionNode/NodeDelivery/NodeGate/BackEdge/Transition/ImpactSet, TestObligation, ETU, WorkItem/Attempt linkage and R1 lineage checks. Existing `rc7_task`, `execution_attempt` and RC7 Gap were reused instead of duplicated.

Key implementation chain includes `028460fa...`, `4256819a...`, `712a5220...`, `be66fbf8...`.

Field validation: `NO`.

### Phase 2 — N1-N10 Runtime State Machine

Status: `CI_PASS`

- qualified code head: `0fdd6ef62101ba837bb623091c6ac3bbadef2e5a`
- qualified run: `40693161338`

Delivered persisted N1-N10 lifecycle, Delivery/Gate enforcement, forward transitions, diagnosis transition, semantic BackEdge, provider/resource separation, UNKNOWN fail-closed, ImpactSet STALE propagation, N7 stale blocking and N10 non-coverage-only convergence.

Field validation: `NO`.

### Phase 3 — N2-N6 Sufficiency / Readiness Gates

Status: `CI_PASS`

- qualified code head: `af2de6d8d902647438c5be71b099d2929f0879a9`
- qualified run: `40709689484`

Delivered deterministic requirement/code/design/data/executable sufficiency gates. N7 cannot dispatch when mandatory upstream truth is absent, stale or insufficient. Reviewer text cannot override deterministic contract failure.

Field validation: `NO`.

### Phase 4 — Adaptive Task Decomposer

Status: `CI_PASS`

- qualified code head: `74946709560b85cef03f01a594a873901712bc71`
- qualified run: `40712471496`

Delivered Requirement/SST/TestObligation-rooted ETU decomposition, heterogeneous split, safe merge, L1-L7/tool/data/browser cohesion, multidimensional priority, low-yield feedback, deterministic planning snapshots and unmapped-coverage investigation routing. Coverage cannot directly create orphan Case/ETU truth.

Field validation: `NO`.

### Phase 5 — Fresh Worker / Reviewer / Session Rotation / Captain Handoff

Status: `CI_PASS`

- qualified code head: `f7214d9c6ff7bbd3cb65f2d43b63816b677e75c1`
- qualified run: `40715463547`
- qualification: `64 passed` RC7.2 contracts on Python 3.8/3.11 + inherited `492 passed, 1 skipped`.

Delivered Role != Worker != Session semantics, ETU-scoped Fresh Worker, R1 checkpoint/rotation, fresh reviewer, signed DSH assignment binding, real DSH session binding and same-Mission Captain handoff.

Field validation: `NO`.

### Phase 6 — Independent Diagnosis / Recovery

Status: `CI_PASS`

- qualified code head: `5678a081e6ff4d622c20b403895ae80dff6ce8f1`
- qualified run: `40717980037`
- qualification: `78 passed` RC7.2 contracts on Python 3.8/3.11 + inherited `492 passed, 1 skipped`.

Delivered Fresh Diagnosis Worker, failure classification, N8 semantic routing to N3/N4/N5/N6/N9, provider/resource separation, repair ImpactSet/STALENESS and mandatory replacement child Attempt rather than executor-side mutation.

Field validation: `NO`.

### Phase 7 — Capability / Resource Runtime

Status: `CI_PASS`

Final qualified slice:

- qualified code head: `6a132d28930dd79c938a8694dfd5a4778cd9b402`
- qualified run: `40726069936`
- qualification: `116 passed` RC7.2 contracts on Python 3.8/3.11 + inherited `492 passed, 1 skipped`.

Delivered as separate slices:

- `checkpoints/PHASE7-CAPABILITY-BROKER-CI-PASS.md`
- `checkpoints/PHASE7-BROWSER-LEASE-CI-PASS.md`
- `checkpoints/PHASE7-DATA-LEASE-CI-PASS.md`
- `checkpoints/PHASE7-MODEL-FAILOVER-CI-PASS.md`

Implemented Worker STRICT capability request/temporary lease/delegation, BrowserPool with exclusive WRITE BrowserLease, DataLease conflict/ownership semantics and attempt-scoped provider/model failover using Fresh Worker/new Attempt rather than hot-swapping a long-lived member.

Field validation: `NO`.

### Phase 8 — Coverage Feedback / Release Convergence

Status: `CI_PASS`

- qualified code head: `7648738529af2d14526f291b4bf9ebd7e7b1e7a3`
- qualified run: `40730275157`
- qualification: `153 passed` RC7.2 contracts on Python 3.8/3.11 + inherited `492 passed, 1 skipped`.

Checkpoints:

- `checkpoints/PHASE8-COVERAGE-MAPPING-CI-PASS.md`
- `checkpoints/PHASE8-RELEASE-SCOPE-DENOMINATOR-CI-PASS.md`
- `checkpoints/PHASE8-N10-R1-CONVERGENCE-CI-PASS.md`
- `checkpoints/PHASE8-CI-PASS.md`

Delivered Libra-like observation -> CodeSlice -> ReleaseBatch/Requirement/SST/TestObligation mapping, evidence-backed GapReason routing, frozen Requirement/SST/L1-L7 denominator, R1-native N10 aggregation, coverage-gap lifecycle and exact terminal states. 92% alone cannot mark the ReleaseBatch converged.

Field validation: `NO`.

### Phase 9 — Journey Teaching / Official L4/L5 Journey

Status: `CI_PASS_FIELD_PENDING`

Latest repository-qualified code head:

- `d43f233ace9c691f881a8b5e0d5be23257b9c5f5`
- run `40737549865`
- RC7.2 contracts Python 3.8: `206 passed`
- RC7.2 contracts Python 3.11: `206 passed`
- inherited RC7 regression: `492 passed, 1 skipped`
- runtime compile: PASS

Completed chain:

```text
Human Teaching Capture
 -> Compiler / Candidate IR
 -> Replay under canonical Attempt + WRITE BrowserLease
 -> per-step Actual/Evidence truth
 -> persisted Benchmark policy/result
 -> repository-vs-Field replay distinction
 -> trusted Human attestation verification
 -> separate Official Journey Asset
 -> L4/L5 Worker Consumption under isolated WRITE BrowserLease
 -> per-step Actual/Evidence truth
```

Phase-9 checkpoints:

- `checkpoints/PHASE9-JOURNEY-CAPTURE-CI-PASS.md`
- `checkpoints/PHASE9-JOURNEY-COMPILER-CI-PASS.md`
- `checkpoints/PHASE9-JOURNEY-REPLAY-CI-PASS.md`
- `checkpoints/PHASE9-JOURNEY-BENCHMARK-CI-PASS.md`
- `checkpoints/PHASE9-JOURNEY-HUMAN-PROMOTION-CI-PASS.md`
- `checkpoints/PHASE9-OFFICIAL-JOURNEY-CONSUMPTION-CI-PASS.md`

Important boundaries:

- Contract/CI browser adapters cannot self-claim Field execution.
- Repository Benchmark PASS is not Field Benchmark verification.
- Human promotion API accepts only `attestation_ref`; no caller-supplied `approved=true` exists.
- Worker/Agent cannot self-approve.
- promotion requires PASSED Field Benchmark plus trusted Field human attestation bound to exact Candidate/Benchmark lineage, versions and scope digest.
- Candidate remains Candidate/nonofficial/nonexecutable; approval creates a separate Official asset.
- Official asset execution is L4/L5-only, bound to ETU/WorkItem/Attempt/Worker/Session + ACTIVE WRITE BrowserLease, and does not mutate the Official asset.

Field validation: `NO`.

## 4. Repository construction close decision

All frozen Phase 0-9 repository construction phases have now reached repository-level completion/CI qualification.

Correct status:

```text
RC7.2 repository construction = CI_PASS
RC7.2 Field validation = PENDING
RC7.2 BANK_FINAL = NO
```

This is **not** RC7.2 Definition of Done. The frozen construction contract additionally requires platform qualification and real Field evidence.

## 5. Next stage — Platform Qualification and Field Acceptance

Do not create a new architecture Phase 10 merely to continue feature construction. The next work is qualification/integration against the existing frozen architecture.

Required next sequence:

1. freeze a platform-qualification / Field-acceptance matrix and evidence schema;
2. Windows qualification;
3. target Linux qualification;
4. clean-unpack/offline-package qualification;
5. real in-bank Browser/BSK adapter qualification with BrowserLease ownership;
6. real bank Human Approval verifier/attestation integration;
7. real ReleaseBatch mission through N1-N10 and ReleaseBatch-rooted Requirement/SST assets;
8. deliberate Field exercise of ANALYSIS_GAP, TEST_DESIGN_GAP, TEST_DATA_GAP, ENVIRONMENT_GAP, CAPABILITY_GAP, Browser conflict, provider quota/auth, genuine product failure and Captain/session handoff;
9. persist all evidence in R1 and only then advance Field status.

No BANK_FINAL claim is allowed before all mandatory platform and Field gates pass.

## 6. Anti-drift rule

Future sessions MUST NOT infer completion from this ledger alone. Always inspect:

```text
current work/rc7.2 HEAD
+ same-HEAD source
+ same-HEAD CI/check-runs
+ frozen 00-05 contracts
+ CURRENT-CHECKPOINT.md
+ this ledger
+ R1/evidence where applicable
```

If they differ, live repository/R1/CI truth wins and the ledger must be corrected in the same construction turn.
