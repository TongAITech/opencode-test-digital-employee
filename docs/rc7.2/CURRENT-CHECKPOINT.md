# RC7.2 Current Construction Checkpoint

Status: **REPOSITORY_CONSTRUCTION_CI_PASS / Q1_CI_PASS / Q2_CI_PASS_ENGINEERING_ONLY / Q3_NOT_RUN / FIELD_VALIDATION_PENDING**

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
latest_q2_qualified_code_sha: 1b4f8ebb4612660ff07d93cdf6bf5b22c30e1d22
same_head_construction_run: 40801951720
same_head_rc72_contracts_python_3_8: 225_passed
same_head_rc72_contracts_python_3_11: 225_passed
same_head_inherited_rc7: 492_passed_1_skipped
qualification:
  q1_source_platform_baseline: CI_PASS_ENGINEERING_ONLY
  q1_same_head_run: 40801951774
  q1_windows: SUCCESS
  q1_linux_engineering_proxy: SUCCESS
  q1_summary: SUCCESS
  q2_windows_clean_unpack: CI_PASS_ENGINEERING_ONLY
  q2_run: 40801952853
  q2a_package_identity_clean_extract: PASS
  q2a_artifact_id: 12866442208
  q2a_artifact_digest: sha256:ec7aff88831c5fdc7efce7919a44612f0d024010c2dbf6d9b5bd053c992e32b0
  q2b_clean_runtime_r1_session_gitbash: PASS
  q2b_artifact_id: 12866217593
  q2b_artifact_digest: sha256:1f4539e6e046d3944ceecaed1ddb63a6dbfbbadc3814c48b6062c0a7b36eb232
  q2b_session_rotation: SESSION_A_TO_B_TO_C_GENERATION_2
  q2b_chat_history_transferred: false
  q2b_gitbash_profile: rc7.2-bank
  q2b_offline_payload_verified: false
  q2_field_verified: false
  q2_bank_final: false
  q3_target_linux: NOT_RUN
  q4_offline_portable: NOT_RUN
  q5_real_browser_bsk: NOT_RUN
  q6_real_human_approval: NOT_RUN
  q7_real_release_batch: NOT_RUN
  q8_failure_recovery: NOT_RUN
field_validation: NOT_STARTED_FOR_RC7_2
bank_final: NO
next_atomic_step: Q3_TARGET_LINUX_REALITY_CONTRACT
```

## Checkpoints

- `checkpoints/Q1-SOURCE-PLATFORM-BASELINE-CI-PASS.md`
- `checkpoints/Q2A-WINDOWS-PACKAGE-IDENTITY-CLEAN-UNPACK-CI-PASS.md`
- `checkpoints/Q2-WINDOWS-CLEAN-UNPACK-CI-PASS.md`

## Q2 result

Q2 is complete at engineering-CI level on source commit `1b4f8ebb...`.

The proof includes exact RC7.2 transport identity, SHA verification, fresh extraction, package-local Python, RC7.2 module completeness, durable R1 truth, Session A -> B -> C handoff without chat-history transfer, and a strict RC7.2 Git Bash entrypoint probe using isolated profile `rc7.2-bank`.

Q2 deliberately does **not** claim complete offline payload readiness. The launcher proof records `offline_payload_verified=false`; full offline DSH/plugin/tool delivery belongs to Q4.

## Next atomic step

Start `Q3_TARGET_LINUX_REALITY_CONTRACT` tests-first.

Q3 must not accept generic Ubuntu/GitHub-hosted Linux as target 信创 Linux. The first Q3 slice must establish a target-environment binding/evidence contract and return HOLD/fail-closed when no approved target/self-hosted runner identity exists.

Until Q3 and all later Field gates complete:

> **RC7.2 repository construction PASS; Q1/Q2 engineering qualification PASS; Field validation pending; BANK_FINAL = NO.**
