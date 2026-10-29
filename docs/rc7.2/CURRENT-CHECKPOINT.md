# RC7.2 Current Construction Checkpoint

Status: **REPOSITORY_CONSTRUCTION_CI_PASS / Q1_CI_PASS / Q2A_CI_PASS / Q2_IN_PROGRESS / FIELD_VALIDATION_PENDING**

This file is the short entry point for every future RC7.2 construction/qualification session. It is a status index, not a replacement for the frozen contracts.

## Mandatory resume order

1. Read current `work/rc7.2` HEAD.
2. Read same-HEAD CI/check-runs.
3. Read frozen `docs/rc7.2/00` through `05` contracts.
4. Read `docs/rc7.2/07-PLATFORM-QUALIFICATION-AND-FIELD-ACCEPTANCE-CONTRACT.md`.
5. Read `docs/rc7.2/CONSTRUCTION-PLAN.md`.
6. Read this file.
7. Inspect live R1/Field evidence before any Field/BANK_FINAL claim.

Chat history, stale SHAs and old checkpoint text never override live repository/R1/CI truth.

## Current truth

```yaml
branch: work/rc7.2
repository_construction: CI_PASS
phase0_9: CLOSED_AT_REPOSITORY_CI_LEVEL
qualification:
  q1_source_platform_baseline: CI_PASS_ENGINEERING_ONLY
  q1_original_qualified_commit: 77e954558f1fdc933febe2adfeb8a069d3d92c00
  q2_windows_clean_unpack: IN_PROGRESS
  q2a_package_identity_clean_extract: CI_PASS_ENGINEERING_ONLY
  q2a_qualified_commit: 120b16143fd5487706156b75c1c86168f642c024
  q2a_run: 40794043110
  q2a_artifact_id: 12861954949
  q2a_contracts: 8_passed
  q2a_required_rc72_runtime_modules: 26
  q2a_package_local_imports: 26_passed
  q2a_field_verified: false
  q2a_bank_final: false
  same_head_q1_windows_rc72_contracts: 218_passed
  same_head_q1_windows_inherited_rc7: 492_passed_1_skipped
  same_head_q1_linux_proxy: SUCCESS
  q2b_clean_runtime_git_bash: NOT_RUN
  q3_target_linux: NOT_RUN
  q4_offline_portable: NOT_RUN
  q5_real_browser_bsk: NOT_RUN
  q6_real_human_approval: NOT_RUN
  q7_real_release_batch: NOT_RUN
  q8_failure_recovery: NOT_RUN
field_validation: NOT_STARTED_FOR_RC7_2
bank_final: NO
next_atomic_step: Q2B_WINDOWS_CLEAN_RUNTIME_AND_GIT_BASH_TESTS_FIRST
```

## Checkpoints

- `checkpoints/Q1-SOURCE-PLATFORM-BASELINE-CI-PASS.md`
- `checkpoints/Q2A-WINDOWS-PACKAGE-IDENTITY-CLEAN-UNPACK-CI-PASS.md`

## Q2-A result

The exact RC7.2 source commit `120b1614...` produced a distinct RC7.2 Windows package, verified its ZIP SHA, deleted the built root, cleanly extracted into a fresh directory, verified package identity/checksum using package-local Python, and imported all 26 current `rc72_*` runtime modules from the clean package. The same HEAD retained green Windows/Linux source qualification and inherited RC7 regression.

This is engineering evidence only. It is not in-bank Windows Field evidence.

## Next atomic step

Q2-B must reuse the mature RC7 Windows clean qualification/runtime continuity implementation rather than clone it. It must prove from the clean RC7.2 package:

- package-local Python enforcement;
- RC7.2 verifier and exact source lineage;
- durable R1 truth across runtime recreation;
- Mission/session A→B→C continuity without chat history transfer;
- Git Bash entrypoint execution using a controlled engineering DSH harness;
- `field_verified=false` and `bank_final=false`.

Do not begin Q3 until Q2-B is green and Q2 overall is checkpointed.
