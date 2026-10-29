# RC7.2 Construction Plan / Checkpoint Ledger

Status: **REPOSITORY_CONSTRUCTION_CI_PASS / PLATFORM_QUALIFICATION_IN_PROGRESS / FIELD_VALIDATION_PENDING**

This ledger is the canonical construction status index. Every future session MUST first read current `work/rc7.2` HEAD, same-HEAD CI/check-runs, frozen `docs/rc7.2/00-BASELINE-AND-READ-ME.md` through `05-AGENTTEAMS-WORKER-LEASE-CONTRACT.md`, `07-PLATFORM-QUALIFICATION-AND-FIELD-ACCEPTANCE-CONTRACT.md`, this ledger, and `CURRENT-CHECKPOINT.md`.

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
qualification:
  contract: FROZEN
  q1_source_platform_baseline: TDD_RED_PENDING_IMPLEMENTATION
  q2_windows_clean_unpack: NOT_RUN
  q3_target_linux: NOT_RUN
  q4_offline_portable: NOT_RUN
  q5_real_browser_bsk: NOT_RUN
  q6_real_human_approval: NOT_RUN
  q7_real_release_batch: NOT_RUN
  q8_failure_recovery: NOT_RUN
field_evidence: NOT_YET_FIELD_VALIDATED
release_status: REPOSITORY_CONSTRUCTION_CI_PASS_PLATFORM_QUALIFICATION_IN_PROGRESS
bank_final: NO
next_atomic_step: IMPLEMENT_RC72_PLATFORM_QUALIFICATION_EVIDENCE_AND_GREEN_Q1
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
8. `07-PLATFORM-QUALIFICATION-AND-FIELD-ACCEPTANCE-CONTRACT.md`
9. this ledger
10. `CURRENT-CHECKPOINT.md`

## 3. Repository construction result

Phase 0-9 repository construction is closed at repository CI level.

- Phase 0: COMPLETE
- Phase 1: CI_PASS
- Phase 2: CI_PASS
- Phase 3: CI_PASS
- Phase 4: CI_PASS
- Phase 5: CI_PASS
- Phase 6: CI_PASS
- Phase 7: CI_PASS
- Phase 8: CI_PASS
- Phase 9: CI_PASS_FIELD_PENDING

Latest repository-qualified functional code head:

- `d43f233ace9c691f881a8b5e0d5be23257b9c5f5`
- run `40737549865`
- RC7.2 contracts Python 3.8: `206 passed`
- RC7.2 contracts Python 3.11: `206 passed`
- inherited RC7 regression: `492 passed, 1 skipped`
- runtime compile: PASS

Repository CI proves the runtime/orchestration contracts only. It does not prove platform packaging or bank Field execution.

## 4. Qualification stage

The qualification contract is now frozen in `07-PLATFORM-QUALIFICATION-AND-FIELD-ACCEPTANCE-CONTRACT.md`.

Qualification gates:

```text
Q1 source-platform engineering baseline
 -> Q2 Windows clean-unpack
 -> Q3 target Linux
 -> Q4 offline/portable delivery
 -> Q5 real Browser/BSK
 -> Q6 real Human Approval verifier
 -> Q7 real ReleaseBatch N1-N10 mission
 -> Q8 recovery/failure exercises
 -> Q9 BANK_FINAL decision
```

Current qualification state:

- Q1: tests/workflow frozen; implementation intentionally RED until `rc7_release.rc72_platform_qualification` exists and same-HEAD Windows/Linux engineering jobs pass.
- Q2-Q8: NOT_RUN.
- Q9: BANK_FINAL=NO.

The generic Ubuntu GitHub runner is an engineering proxy and MUST NOT be reported as target 信创 Linux qualification.

## 5. Next atomic step

Implement the Q1 structured evidence module without altering RC7.2 runtime semantics, then require same-HEAD success for:

- Windows engineering runner + Python 3.8 + all `test_rc72_*.py` + inherited `test_rc7_*.py`;
- Linux engineering proxy + Python 3.8 + the same suites;
- structured Q1 evidence bound to exact source commit;
- `field_verified=false` and `bank_final=false`.

Only after Q1 is GREEN may Q2 Windows clean-unpack qualification begin.

## 6. Anti-drift rule

Future sessions MUST NOT infer completion from this ledger alone. Always inspect:

```text
current work/rc7.2 HEAD
+ same-HEAD source
+ same-HEAD CI/check-runs
+ frozen 00-05 and 07 contracts
+ CURRENT-CHECKPOINT.md
+ this ledger
+ R1/evidence where applicable
```

If they differ, live repository/R1/CI truth wins and the ledger must be corrected in the same construction turn.
