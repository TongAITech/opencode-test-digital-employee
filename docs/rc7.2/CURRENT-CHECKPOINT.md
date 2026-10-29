# RC7.2 Current Construction Checkpoint

Status: **REPOSITORY_CONSTRUCTION_CI_PASS / Q1_CI_PASS / Q2_CI_PASS_ENGINEERING_ONLY / Q3_REALITY_CONTRACT_PASS_TARGET_HOLD / FIELD_VALIDATION_PENDING**

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
latest_qualified_functional_head: 55ee7d96e6036fa46b4c171032c934313fd90426
same_head_construction_run: 40803275491
same_head_rc72_contracts_python_3_8: 237_passed
same_head_rc72_contracts_python_3_11: 237_passed
same_head_inherited_rc7: 492_passed_1_skipped
qualification:
  q1_source_platform_baseline: CI_PASS_ENGINEERING_ONLY
  q1_same_head_run: 40803275548
  q1_windows: SUCCESS
  q1_linux_engineering_proxy: SUCCESS
  q1_summary: SUCCESS
  q1_windows_artifact_id: 12866069888
  q1_linux_artifact_id: 12867275735
  q2_windows_clean_unpack: CI_PASS_ENGINEERING_ONLY
  q2_same_head_run: 40803275565
  q2a_package_identity_clean_extract: PASS
  q2a_artifact_id: 12866777873
  q2b_clean_runtime_r1_session_gitbash: PASS
  q2b_artifact_id: 12866393853
  q2b_session_rotation: SESSION_A_TO_B_TO_C_GENERATION_2
  q2b_chat_history_transferred: false
  q2b_gitbash_profile: rc7.2-bank
  q2b_offline_payload_verified: false
  q3_reality_binding_contract: CI_PASS
  q3_same_head_run: 40803275534
  q3_negative_control: PASS
  q3_target_linux: HOLD_TARGET_ENVIRONMENT_BINDING_REQUIRED
  q3_artifact_id: 12866722683
  q3_observed_platform: Ubuntu_24.04_x86_64
  q3_hold_reason: GENERIC_LINUX_PROXY_NOT_TARGET
  target_linux_verified: false
  field_verified: false
  q4_offline_portable: NOT_RUN
  q5_real_browser_bsk: NOT_RUN
  q6_real_human_approval: NOT_RUN
  q7_real_release_batch: NOT_RUN
  q8_failure_recovery: NOT_RUN
field_validation: NOT_STARTED_FOR_RC7_2
bank_final: NO
next_atomic_step: Q3_TARGET_SIDE_PROBE_AND_ATTESTATION_INGESTION_TESTS_FIRST
```

## Checkpoints

- `checkpoints/Q1-SOURCE-PLATFORM-BASELINE-CI-PASS.md`
- `checkpoints/Q2A-WINDOWS-PACKAGE-IDENTITY-CLEAN-UNPACK-CI-PASS.md`
- `checkpoints/Q2-WINDOWS-CLEAN-UNPACK-CI-PASS.md`
- `checkpoints/Q3-TARGET-LINUX-REALITY-CONTRACT-HOLD.md`

## Q3 result

The Q3 **policy/reality-binding contract is green**, but target Linux itself is deliberately **HOLD**.

Same-head evidence on `55ee7d96...` proves generic GitHub Ubuntu is correctly rejected as target 信创 Linux:

```text
status=HOLD
reason=GENERIC_LINUX_PROXY_NOT_TARGET
target_linux_verified=false
field_verified=false
bank_final=false
```

This is a successful fail-closed qualification outcome, not a target-Linux PASS.

## Next atomic step

Start `Q3_TARGET_SIDE_PROBE_AND_ATTESTATION_INGESTION_TESTS_FIRST`.

Add a packageable target-side probe plus external target-attestation ingestion. The target probe may observe machine/source facts only; it may not self-approve. Only trusted external target attestation with exact source and machine identity can release Q3 from HOLD.

Do not start Q4 qualification while Q3 remains HOLD.

> **RC7.2 repository construction PASS; Q1/Q2 engineering qualification PASS; Q3 policy gate PASS but target environment HOLD; Field validation pending; BANK_FINAL = NO.**
