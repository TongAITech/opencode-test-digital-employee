# RC7.2 Current Construction Checkpoint

Status: **REPOSITORY_CONSTRUCTION_CI_PASS / PLATFORM_QUALIFICATION_BASELINE_FROZEN / FIELD_VALIDATION_PENDING**

This file is the short entry point for every future RC7.2 construction/qualification session.
It is a status index, not a replacement for the frozen contracts.

## Mandatory resume order

1. Read current `work/rc7.2` HEAD.
2. Read same-HEAD CI/check-runs.
3. Read `docs/rc7.2/00-BASELINE-AND-READ-ME.md` through `05-AGENTTEAMS-WORKER-LEASE-CONTRACT.md`.
4. Read `docs/rc7.2/02-CONSTRUCTION-CONTRACT.md` exit/DoD clauses.
5. Read `docs/rc7.2/07-PLATFORM-QUALIFICATION-AND-FIELD-ACCEPTANCE-CONTRACT.md`.
6. Read `docs/rc7.2/CONSTRUCTION-PLAN.md`.
7. Read this file.
8. Inspect live R1/Field evidence before making any Field/BANK_FINAL claim.

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
qualification_status:
  contract: FROZEN
  q1_source_platform_baseline: TDD_RED_PENDING_IMPLEMENTATION
  q2_windows_clean_unpack: NOT_RUN
  q3_target_linux: NOT_RUN
  q4_offline_portable: NOT_RUN
  q5_real_browser_bsk: NOT_RUN
  q6_real_human_approval: NOT_RUN
  q7_real_release_batch: NOT_RUN
  q8_failure_recovery: NOT_RUN
field_validation: NOT_STARTED_FOR_RC7_2
bank_final: NO
next_atomic_step: IMPLEMENT_RC72_PLATFORM_QUALIFICATION_EVIDENCE_AND_GREEN_Q1
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
- Windows clean-unpack qualification for RC7.2;
- target Linux qualification;
- clean-unpack/offline package qualification;
- a real in-bank ReleaseBatch N1-N10 mission;
- the required injected/real Field gap scenarios;
- BANK_FINAL readiness.

## Qualification baseline

The qualification contract is now frozen in:

- `07-PLATFORM-QUALIFICATION-AND-FIELD-ACCEPTANCE-CONTRACT.md`
- `.github/workflows/rc7.2-platform-qualification.yml`
- `tests/test_rc72_platform_qualification_contract.py`

The first gate is Q1 source-platform engineering qualification on:

- Windows + Python 3.8;
- Linux engineering proxy + Python 3.8.

The Linux GitHub-hosted runner is explicitly **not** target 信创 Linux Field evidence.

## Next stage — do not add another architecture phase

The next work is qualification/integration, not Phase 10 feature construction:

1. implement the Q1 structured evidence module and turn the frozen Q1 RED contract GREEN;
2. run same-HEAD Windows/Linux engineering source qualification;
3. qualify Windows clean-unpack package;
4. validate target Linux runtime;
5. validate clean-unpack/offline package behavior;
6. connect and verify real Browser/BSK Field adapter;
7. connect and verify real bank Human Approval verifier;
8. run a real ReleaseBatch Field mission through N1-N10;
9. deliberately exercise ANALYSIS_GAP, TEST_DESIGN_GAP, TEST_DATA_GAP, ENVIRONMENT_GAP, CAPABILITY_GAP, Browser conflict, provider quota/auth, genuine product failure and Captain/session handoff;
10. only after evidence is persisted in R1 may Field status be advanced.

Until those steps are complete, the correct status is:

> **RC7.2 repository construction CI_PASS; platform qualification in progress; Field validation pending; BANK_FINAL = NO.**
