# RC7.2 Current Construction Checkpoint

Status: **REPOSITORY_CONSTRUCTION_CI_PASS / FIELD_VALIDATION_PENDING**

This file is the short entry point for every future RC7.2 construction/qualification session.
It is a status index, not a replacement for the frozen contracts.

## Mandatory resume order

1. Read current `work/rc7.2` HEAD.
2. Read same-HEAD CI/check-runs.
3. Read `docs/rc7.2/00-BASELINE-AND-READ-ME.md` through `05-AGENTTEAMS-WORKER-LEASE-CONTRACT.md`.
4. Read `docs/rc7.2/02-CONSTRUCTION-CONTRACT.md` exit/DoD clauses.
5. Read `docs/rc7.2/CONSTRUCTION-PLAN.md`.
6. Read this file.
7. Inspect live R1/Field evidence before making any Field/BANK_FINAL claim.

Chat history, stale SHAs and old checkpoint text never override live repository/R1/CI truth.

## Current repository truth

```yaml
branch: work/rc7.2
design_baseline_sha: a3426e306abf967ab822d44508127c3891c8e91e
latest_repository_qualified_code_head: d43f233ace9c691f881a8b5e0d5be23257b9c5f5
latest_repository_qualified_ci_run: 40737549865
latest_repository_qualification:
  rc72_contracts_python_3_8: 206_passed
  rc72_contracts_python_3_11: 206_passed
  inherited_rc7_python_3_8: 492_passed_1_skipped
  runtime_compile: PASS
phase_status:
  phase0_reality_baseline: COMPLETE
  phase1_canonical_domain_model: CI_PASS
  phase2_n1_n10_state_machine: CI_PASS
  phase3_sufficiency_gates: CI_PASS
  phase4_adaptive_task_decomposer: CI_PASS
  phase5_fresh_worker_runtime: CI_PASS
  phase6_diagnosis_recovery: CI_PASS
  phase7_capability_resource_runtime: CI_PASS
  phase8_coverage_convergence: CI_PASS
  phase9_journey_teaching: CI_PASS_FIELD_PENDING
field_validation: NOT_STARTED_FOR_RC7_2
bank_final: NO
next_atomic_step: PLATFORM_QUALIFICATION_AND_FIELD_ACCEPTANCE_BASELINE
```

## Phase 9 completed repository chain

```text
Human Teaching Capture
 -> Journey Compiler / Candidate IR
 -> Replay under canonical Attempt + WRITE BrowserLease
 -> persisted Replay Actual/Evidence
 -> Benchmark with explicit persisted policy
 -> Field-vs-contract replay distinction
 -> trusted Human attestation verification
 -> separate Official Journey Asset
 -> L4/L5 Worker consumption under isolated WRITE BrowserLease
 -> persisted execution Actual/Evidence
```

Repository CI proves the orchestration/contracts only. It does **not** prove:

- real in-bank BSK/CDP capture/replay;
- a real bank Human Approval verifier/attestation source;
- Windows qualification;
- target Linux qualification;
- clean-unpack/offline package qualification;
- a real in-bank ReleaseBatch N1-N10 mission;
- the required injected/real Field gap scenarios;
- BANK_FINAL readiness.

## Phase 9 checkpoints

- `checkpoints/PHASE9-JOURNEY-CAPTURE-CI-PASS.md`
- `checkpoints/PHASE9-JOURNEY-COMPILER-CI-PASS.md`
- `checkpoints/PHASE9-JOURNEY-REPLAY-CI-PASS.md`
- `checkpoints/PHASE9-JOURNEY-BENCHMARK-CI-PASS.md`
- `checkpoints/PHASE9-JOURNEY-HUMAN-PROMOTION-CI-PASS.md`
- `checkpoints/PHASE9-OFFICIAL-JOURNEY-CONSUMPTION-CI-PASS.md`

## Next stage — do not add another architecture phase

The next work is qualification/integration, not Phase 10 feature construction:

1. freeze a platform-qualification matrix;
2. validate Windows runtime;
3. validate target Linux runtime;
4. validate clean-unpack/offline package behavior;
5. connect and verify real Browser/BSK Field adapter;
6. connect and verify real bank Human Approval verifier;
7. run a real ReleaseBatch Field mission through N1-N10;
8. deliberately exercise ANALYSIS_GAP, TEST_DESIGN_GAP, TEST_DATA_GAP, ENVIRONMENT_GAP, CAPABILITY_GAP, Browser conflict, provider quota/auth, genuine product failure and Captain/session handoff;
9. only after evidence is persisted in R1 may Field status be advanced.

Until those steps are complete, the correct status is:

> **RC7.2 repository construction CI_PASS; Field validation pending; BANK_FINAL = NO.**
