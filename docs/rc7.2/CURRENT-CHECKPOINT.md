# RC7.2 Current Construction Checkpoint

Status: **REPOSITORY_CONSTRUCTION_CI_PASS / Q1_CI_PASS / Q2_CI_PASS_ENGINEERING_ONLY / Q3_TARGET_PROBE_ATTESTATION_CONTRACT_PASS_TARGET_HOLD / FIELD_VALIDATION_PENDING**

This file is the short entry point for every future RC7.2 construction/qualification session. It is a status index, not a replacement for the frozen contracts.

## Mandatory resume order

1. Read current `work/rc7.2` HEAD.
2. Read same-HEAD CI/check-runs.
3. Read frozen `docs/rc7.2/00` through `05` contracts.
4. Read `docs/rc7.2/07-PLATFORM-QUALIFICATION-AND-FIELD-ACCEPTANCE-CONTRACT.md`.
5. Read `docs/rc7.2/CONSTRUCTION-PLAN.md`.
6. Read this file.
7. Inspect live R1/Field evidence before any Field/BANK_FINAL claim.

Chat history, stale SHAs and old checkpoint text never override live repository/R1/CI/Evidence truth.

## Current truth

```yaml
branch: work/rc7.2
repository_construction: CI_PASS
phase0_9: CLOSED_AT_REPOSITORY_CI_LEVEL
latest_qualified_functional_head: 43f9ec4350b87b257e97ce17b929c6a174951667
same_head_construction_run: 40807619555
same_head_rc72_contracts_python_3_8: 244_passed
same_head_rc72_contracts_python_3_11: 244_passed
same_head_inherited_rc7: 492_passed_1_skipped
qualification:
  q1_source_platform_baseline: CI_PASS_ENGINEERING_ONLY
  q1_same_head_run: 40807619559
  q1_windows: SUCCESS
  q1_linux_engineering_proxy: SUCCESS
  q1_summary: SUCCESS
  q1_windows_artifact_id: 12868493488
  q1_windows_artifact_digest: sha256:306c029f716b5e5f3c78397d00f46d28c658275466b55dde548c43eabfefbf34
  q1_linux_artifact_id: 12869200738
  q1_linux_artifact_digest: sha256:dd18c3493365c177064d27b8f45339e7de49a50b1de6c0291056ef4add576f8b
  q2_windows_clean_unpack: CI_PASS_ENGINEERING_ONLY
  q2_same_head_run: 40807619582
  q2a_package_identity_clean_extract: PASS
  q2a_artifact_id: 12868024787
  q2a_artifact_digest: sha256:ab67834c755119becfa83bd4c63bd0b5d965401a75e32eb5f0a0a8cba4d62331
  q2b_clean_runtime_r1_session_gitbash: PASS
  q2b_artifact_id: 12868862232
  q2b_artifact_digest: sha256:c147da9be86ce13f51df574ba14bfef11f7f3abe52242394a63f29fedc5829e6
  q2b_session_rotation: SESSION_A_TO_B_TO_C_ACTIVE_SESSION_C
  q2b_chat_history_transferred: false
  q2b_business_root: RELEASE_BATCH
  q2b_runtime_control_backbone: N1_N10_MISSION_GRAPH
  q2b_gitbash_profile: rc7.2-bank
  q2b_offline_payload_verified: false
  q3_reality_binding_contract: CI_PASS
  q3_target_probe_contract: CI_PASS
  q3_external_attestation_boundary: CI_PASS
  q3_same_head_run: 40807619551
  q3_contracts: 19_passed
  q3_negative_control: PASS
  q3_target_linux: HOLD_TARGET_ENVIRONMENT_BINDING_REQUIRED
  q3_artifact_id: 12868593591
  q3_artifact_digest: sha256:6ace4b493bb5f5f3935074900ce22c1f624d1f7c0b52a28904f326548d9257f3
  q3_observed_platform: Ubuntu_24.04_x86_64
  q3_hold_reason: GENERIC_LINUX_PROXY_NOT_TARGET
  q3_attestation_state: AWAITING_EXTERNAL_ATTESTATION
  q3_observation_digest: 3b2f250b95a2533b5a2ac518227efd7e26820731e802fb07ce64fc3f19d74a5b
  target_linux_verified: false
  field_verified: false
  q4_offline_portable: NOT_RUN
  q5_real_browser_bsk: NOT_RUN
  q6_real_human_approval: NOT_RUN
  q7_real_release_batch: NOT_RUN
  q8_failure_recovery: NOT_RUN
field_validation: NOT_STARTED_FOR_RC7_2
bank_final: NO
next_atomic_step: Q3_REAL_TARGET_INVOCATION_AND_TRUSTED_ATTESTATION_BINDING
```

## Same-head qualification seal

Functional source `43f9ec4350b87b257e97ce17b929c6a174951667` has same-head SUCCESS for:

- Construction run `40807619555`;
- Q1 run `40807619559`;
- Q2 run `40807619582`;
- Q3 run `40807619551`.

This closes the prior audit gap where different parent SHAs carried different gate evidence.

## Q2 result

Q2 is repository engineering PASS on Windows clean-unpack, not Field/offline PASS.

Evidence from the Q2-B clean package records:

```text
status=PASS
business_root=RELEASE_BATCH
runtime_control_backbone=N1_N10_MISSION_GRAPH
active_session_ref=SESSION-C
chat_history_transferred=false
profile=rc7.2-bank
offline_payload_verified=false
field_verified=false
bank_final=false
```

Complete plugin/tool/offline payload validation remains Q4.

## Q3 result

The Q3 target probe and external-attestation mechanism is now implemented and CI-qualified, while target Linux itself remains deliberately HOLD.

The packageable probe only observes facts; it cannot install dependencies or self-approve. The attestation boundary requires trusted external evidence bound to exact source lineage, observation digest and machine identity.

Generic GitHub Ubuntu remains correctly rejected:

```text
status=HOLD
reason=GENERIC_LINUX_PROXY_NOT_TARGET
target_linux_verified=false
field_verified=false
bank_final=false
```

This is a successful fail-closed engineering outcome, not a target-Linux PASS.

## Next atomic step

Start `Q3_REAL_TARGET_INVOCATION_AND_TRUSTED_ATTESTATION_BINDING`.

Run the packageable Q3 probe on an actual approved target 信创 Linux environment from exact functional source `43f9ec4350b87b257e97ce17b929c6a174951667`; obtain an externally trusted attestation bound to the same source, observation digest and machine identity; then evaluate it through the frozen Q3 trust boundary.

Do not start Q4 qualification while Q3 remains target-environment HOLD.

> **RC7.2 repository construction PASS; Q1/Q2 engineering qualification PASS; Q3 probe/attestation mechanism PASS but real target environment HOLD; Field validation pending; BANK_FINAL = NO.**
