# RC7.2 Current Construction Checkpoint

Status: **REPOSITORY_CONSTRUCTION_CI_PASS / Q1_CI_PASS / Q2_CI_PASS_ENGINEERING_ONLY / Q3_PACKAGE_BOUND_ATTESTATION_CONTRACT_PASS_TARGET_HOLD / FIELD_VALIDATION_PENDING**

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
latest_qualified_functional_head: 495a12f35430443d7f9cfb59ad6691894a8c8125
same_head_construction_run: 40815666704
same_head_rc72_contracts_python_3_8: 253_passed
same_head_rc72_contracts_python_3_11: 253_passed
same_head_inherited_rc7: 492_passed_1_skipped
qualification:
  q1_source_platform_baseline: CI_PASS_ENGINEERING_ONLY
  q1_same_head_run: 40815666700
  q1_windows: SUCCESS
  q1_linux_engineering_proxy: SUCCESS
  q1_summary: SUCCESS
  q1_windows_artifact_id: 12872207615
  q1_windows_artifact_digest: sha256:22d39d64264d70032d03e2f100be49306f68ee16ee90ee1f98b3bcea91391183
  q1_linux_artifact_id: 12872466187
  q1_linux_artifact_digest: sha256:88a4dabafec41ad5790cd53c0ad9368c3c44ad2df5446a9361865600def6d65d
  q2_windows_clean_unpack: CI_PASS_ENGINEERING_ONLY
  q2_same_head_run: 40815666705
  q2a_package_identity_clean_extract: PASS
  q2a_artifact_id: 12871584284
  q2a_artifact_digest: sha256:e61738fa3ba5b7de283922cacfca8652281447d75656b780fee155757a3e6795
  q2b_clean_runtime_r1_session_gitbash: PASS
  q2b_artifact_id: 12872715575
  q2b_artifact_digest: sha256:e874280b8eddd0c10d1e69fc1957ab114f2462d76206c81d169bddf599592706
  q2b_session_rotation: SESSION_A_TO_B_TO_C_ACTIVE_SESSION_C
  q2b_chat_history_transferred: false
  q2b_business_root: RELEASE_BATCH
  q2b_runtime_control_backbone: N1_N10_MISSION_GRAPH
  q2b_gitbash_profile: rc7.2-bank
  q2b_offline_payload_verified: false
  q3_reality_binding_contract: CI_PASS
  q3_target_probe_contract: CI_PASS
  q3_field_handoff_contract: CI_PASS
  q3_external_attestation_boundary: CI_PASS
  q3_same_head_run: 40815666715
  q3_contracts: 28_passed
  q3_negative_control: PASS
  q3_target_linux: HOLD_TARGET_ENVIRONMENT_BINDING_REQUIRED
  q3_artifact_id: 12872261627
  q3_artifact_digest: sha256:099237561300c9e049a2d4dbf8972e6fdccd2219a1294fbd103199cec38548f1
  q3_observed_platform: Ubuntu_24.04_x86_64
  q3_hold_reason: GENERIC_LINUX_PROXY_NOT_TARGET
  q3_attestation_state: AWAITING_EXTERNAL_ATTESTATION
  q3_package_evidence_bound: true
  q3_engineering_handoff_package_evidence_digest: fca93c2bf518ee524d2edd0a98f4d58bfcc8746358c3e169e16c7a11ff718154
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

Functional source `495a12f35430443d7f9cfb59ad6691894a8c8125` has same-head SUCCESS for:

- Construction run `40815666704`;
- Q1 run `40815666700`;
- Q2 run `40815666705`;
- Q3 run `40815666715`.

Q2-A transport content was also inspected after clean-unpack. Its embedded `SOURCE_COMMIT` is exactly `495a12f35430443d7f9cfb59ad6691894a8c8125`, and the package contains the Q3 handoff/probe, AITEST entrypoint, attestation module and reality module used by the strengthened trust chain.

## Q2 result

Q2 is repository engineering PASS on Windows clean-unpack, not Field/offline PASS. Q2-B proves clean-package R1/Session A→B→C continuity and Git Bash entrypoint behavior while preserving:

```text
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

The Q3 target-side handoff and trust boundary are now package-qualified and fail closed. Positive Q3 release has one strong path only: a trusted external verifier must bind approval to all of the following at once:

1. exact source lineage;
2. exact target observation SHA-256 digest;
3. exact transported package-evidence SHA-256 digest;
4. exact target machine identity.

`packaging/rc7.2/Q3-FIELD-HANDOFF.sh` creates observation, transported-package evidence, an attestation request and a handoff manifest. It does not install dependencies, self-approve target Linux, set Field verified or set BANK_FINAL.

The transported package evidence hashes the critical files used to make the Q3 decision. The legacy `rc72_target_linux_reality.py` positive path now delegates to the same digest-bound attestation evaluator, so there is no weaker PASS bypass.

Generic GitHub Ubuntu remains correctly rejected:

```text
status=HOLD
reason=GENERIC_LINUX_PROXY_NOT_TARGET
target_linux_verified=false
field_verified=false
bank_final=false
```

Workflow SUCCESS proves the engineering mechanism and fail-closed policy. It does **not** mean a real target 信创 Linux environment passed qualification.

## Next atomic step

Start `Q3_REAL_TARGET_INVOCATION_AND_TRUSTED_ATTESTATION_BINDING` only on an actual approved target 信创 Linux environment using the exact `495a12f35430443d7f9cfb59ad6691894a8c8125` transport lineage.

Run `packaging/rc7.2/Q3-FIELD-HANDOFF.sh` on that target, preserve its observation/package-evidence/request/manifest outputs, then obtain a trusted external attestation whose observation digest and package-evidence digest both match the handoff output and whose source/machine identity also match. Evaluate that evidence through the frozen Q3 boundary.

Do not start Q4 qualification while Q3 remains target-environment HOLD.

> **RC7.2 repository construction PASS; Q1/Q2 engineering qualification PASS; Q3 package-bound handoff/attestation mechanism PASS but real target environment HOLD; Field validation pending; BANK_FINAL = NO.**
