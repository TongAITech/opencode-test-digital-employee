# RC7.2 Current Construction Checkpoint

Status: **REPOSITORY_CONSTRUCTION_CI_PASS / Q1_SOURCE_PLATFORM_CI_PASS / PLATFORM_QUALIFICATION_IN_PROGRESS / FIELD_VALIDATION_PENDING**

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

## Current repository and qualification truth

```yaml
branch: work/rc7.2
design_baseline_sha: a3426e306abf967ab822d44508127c3891c8e91e
repository_construction_functional_head: d43f233ace9c691f881a8b5e0d5be23257b9c5f5
repository_construction_run: 40737549865
repository_construction:
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
  q1_source_platform_baseline: CI_PASS_ENGINEERING_ONLY
  q1_qualified_source_commit: 77e954558f1fdc933febe2adfeb8a069d3d92c00
  q1_workflow_run: 40791919277
  q1_windows:
    rc72_contracts: 210_passed
    inherited_rc7: 492_passed_1_skipped
    field_verified: false
  q1_linux_engineering_proxy:
    rc72_contracts: 210_passed
    inherited_rc7: 492_passed_1_skipped
    target_linux_verified: false
    field_verified: false
  q2_windows_clean_unpack: NOT_RUN
  q3_target_linux: NOT_RUN
  q4_offline_portable: NOT_RUN
  q5_real_browser_bsk: NOT_RUN
  q6_real_human_approval: NOT_RUN
  q7_real_release_batch: NOT_RUN
  q8_failure_recovery: NOT_RUN
field_validation: NOT_STARTED_FOR_RC7_2
bank_final: NO
next_atomic_step: Q2_WINDOWS_CLEAN_UNPACK_TESTS_FIRST
```

## Q1 evidence

Checkpoint: `checkpoints/Q1-SOURCE-PLATFORM-BASELINE-CI-PASS.md`

Q1 proves source/runtime engineering portability on Windows and a generic Linux proxy. It does **not** prove:

- Windows clean-unpack package behavior;
- in-bank Windows PC behavior;
- target 信创 Linux behavior;
- clean offline/portable delivery;
- real BSK/CDP Field execution;
- real bank Human Approval;
- a real ReleaseBatch N1-N10 Field mission;
- BANK_FINAL readiness.

## Next atomic step

Start Q2 Windows clean-unpack tests-first.

Q2 must reuse mature RC7/RC7.1 packaging mechanics where valid, but must preserve RC7.2 identity and exact source lineage. It must prove that a fresh archive built from an RC7.2 HEAD can be checksum-verified, extracted into a clean directory outside the source checkout, run using package-local runtime/entrypoint, and contains the RC7.2 runtime modules needed by the delivered capability.

Until Q2 and later Field gates complete:

> **RC7.2 repository construction CI_PASS; Q1 engineering platform baseline PASS; Field validation pending; BANK_FINAL = NO.**
