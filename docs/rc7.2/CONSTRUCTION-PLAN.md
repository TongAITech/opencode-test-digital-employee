# RC7.2 Construction Plan / Checkpoint Ledger

Status: **REPOSITORY_CONSTRUCTION_CI_PASS / Q1_SOURCE_PLATFORM_CI_PASS / PLATFORM_QUALIFICATION_IN_PROGRESS / FIELD_VALIDATION_PENDING**

This ledger is the canonical construction status index. Every future session MUST first read current `work/rc7.2` HEAD, same-HEAD CI/check-runs, frozen `docs/rc7.2/00-BASELINE-AND-READ-ME.md` through `05-AGENTTEAMS-WORKER-LEASE-CONTRACT.md`, `07-PLATFORM-QUALIFICATION-AND-FIELD-ACCEPTANCE-CONTRACT.md`, this ledger, and `CURRENT-CHECKPOINT.md`.

Chat history, stale SHAs and old summaries never override repository/R1/CI truth.

## 1. Current checkpoint

```yaml
branch: work/rc7.2
design_baseline_sha: a3426e306abf967ab822d44508127c3891c8e91e
repository_construction_functional_head_sha: d43f233ace9c691f881a8b5e0d5be23257b9c5f5
repository_construction_run: 40737549865
repository_construction:
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
  q1_source_platform_baseline: CI_PASS_ENGINEERING_ONLY
  q1_qualified_source_commit: 77e954558f1fdc933febe2adfeb8a069d3d92c00
  q1_run: 40791919277
  q1_windows: 210_rc72_passed__492_rc7_passed_1_skipped
  q1_linux_proxy: 210_rc72_passed__492_rc7_passed_1_skipped
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
next_atomic_step: Q2_WINDOWS_CLEAN_UNPACK_TESTS_FIRST
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

Latest repository-qualified functional code head before qualification-specific additions:

- `d43f233ace9c691f881a8b5e0d5be23257b9c5f5`
- run `40737549865`
- RC7.2 contracts Python 3.8: `206 passed`
- RC7.2 contracts Python 3.11: `206 passed`
- inherited RC7 regression: `492 passed, 1 skipped`
- runtime compile: PASS

## 4. Qualification stage

Frozen qualification sequence:

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

### Q1 — Source platform engineering baseline

Status: `CI_PASS_ENGINEERING_ONLY`

- qualified source commit: `77e954558f1fdc933febe2adfeb8a069d3d92c00`
- workflow run: `40791919277`
- Windows engineering job: SUCCESS
- Linux engineering proxy job: SUCCESS
- Windows RC7.2 contracts: `210 passed`
- Windows inherited RC7: `492 passed, 1 skipped`
- Linux proxy RC7.2 contracts: `210 passed`
- Linux proxy inherited RC7: `492 passed, 1 skipped`
- Windows evidence artifact: `12862112628`
- Linux proxy evidence artifact: `12861219520`
- both evidence records bind exact source commit
- both evidence records have `field_verified=false` and `bank_final=false`
- Linux evidence additionally has `target_linux_verified=false`

Checkpoint: `checkpoints/Q1-SOURCE-PLATFORM-BASELINE-CI-PASS.md`

Q1 does not satisfy Q2/Q3/Field requirements.

### Q2 — Windows clean-unpack

Status: `NOT_RUN`

Entry criteria are now satisfied because Q1 is green.

Q2 must prove on Windows engineering infrastructure:

1. build from an exact RC7.2 source commit;
2. produce a deterministic RC7.2 package identity/manifest;
3. record SHA-256 for the archive;
4. delete/leave the build/source runtime context and extract into a fresh clean directory;
5. use package-local runtime rather than source-tree imports;
6. verify required RC7.2 runtime modules are present in the delivered payload;
7. run a clean-unpack smoke/qualification path;
8. validate the Git Bash entrypoint if the delivery contract requires it;
9. perform no public-Internet dependency install at runtime;
10. emit Q2 evidence with `field_verified=false` and `bank_final=false`.

Inherited RC7/RC7.1 package builders and qualification scripts SHOULD be reused, but must not preserve a false RC7/RC7.1 release identity for the RC7.2 artifact.

## 5. Next atomic step

`Q2_WINDOWS_CLEAN_UNPACK_TESTS_FIRST`

Before implementing Q2, inspect current package manifest/build overlay to prove whether newly introduced `rc72_*` runtime modules are already included. The tests must fail if the package omits RC7.2 runtime files even when source checkout CI is green.

Do not start target Linux or Field adapter qualification until Q2 has a same-lineage green checkpoint.

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
