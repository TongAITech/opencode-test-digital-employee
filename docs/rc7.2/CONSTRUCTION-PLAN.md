# RC7.2 Construction Plan / Checkpoint Ledger

Status: **REPOSITORY_CONSTRUCTION_CI_PASS / Q1_CI_PASS / Q2_CI_PASS_ENGINEERING_ONLY / Q3_PACKAGE_BOUND_ATTESTATION_CONTRACT_PASS_TARGET_HOLD / FIELD_VALIDATION_PENDING**

Future sessions MUST read current branch HEAD, same-HEAD CI, frozen contracts, this ledger and `CURRENT-CHECKPOINT.md`. Live repository/R1/CI/Evidence truth overrides stale chat history or stale SHAs.

## 1. Repository construction

Phase 0-9 repository construction is closed at repository CI level.

Original repository functional head before qualification additions:

- `d43f233ace9c691f881a8b5e0d5be23257b9c5f5`
- run `40737549865`
- RC7.2 contracts: `206 passed` on Python 3.8 and Python 3.11
- inherited RC7: `492 passed, 1 skipped`

Latest same-head qualified functional source:

- `495a12f35430443d7f9cfb59ad6691894a8c8125`
- Construction run `40815666704`
- RC7.2 contracts Python 3.8: `253 passed`
- RC7.2 contracts Python 3.11: `253 passed`
- inherited RC7: `492 passed, 1 skipped`

The Construction workflow includes `rc7_release/**`, so qualification/release-layer changes cannot bypass full same-head contract validation. Repository CI is not Field validation and not BANK_FINAL.

## 2. Frozen qualification sequence

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

Qualification contract: `07-PLATFORM-QUALIFICATION-AND-FIELD-ACCEPTANCE-CONTRACT.md`.

Q4 qualification MUST NOT begin while Q3 remains target-environment HOLD.

## 3. Q1 — Source platform engineering baseline

Status: `CI_PASS_ENGINEERING_ONLY`.

Same-head run: `40815666700` on `495a12f35430443d7f9cfb59ad6691894a8c8125`.

- Windows engineering: SUCCESS
- Linux engineering proxy: SUCCESS
- Q1 summary: SUCCESS
- Windows artifact id: `12872207615`
- Windows artifact digest: `sha256:22d39d64264d70032d03e2f100be49306f68ee16ee90ee1f98b3bcea91391183`
- Linux proxy artifact id: `12872466187`
- Linux proxy artifact digest: `sha256:88a4dabafec41ad5790cd53c0ad9368c3c44ad2df5446a9361865600def6d65d`

Q1 proves Windows and generic Linux engineering portability only. Generic Linux is not target 信创 Linux Field evidence.

Checkpoint: `checkpoints/Q1-SOURCE-PLATFORM-BASELINE-CI-PASS.md`.

## 4. Q2 — Windows clean-unpack

Status: `CI_PASS_ENGINEERING_ONLY`.

Same-head workflow run: `40815666705` on `495a12f35430443d7f9cfb59ad6691894a8c8125`.

### Q2-A

- exact-lineage package build: PASS
- delete build root + clean re-extract: PASS
- package-local Python / identity / strict checksum verification: PASS
- artifact id: `12871584284`
- artifact digest: `sha256:e61738fa3ba5b7de283922cacfca8652281447d75656b780fee155757a3e6795`

Content-level transport inspection confirmed:

- embedded `SOURCE_COMMIT` = `495a12f35430443d7f9cfb59ad6691894a8c8125`;
- `packaging/rc7.2/Q3-FIELD-HANDOFF.sh` present;
- `packaging/rc7.2/Q3-TARGET-LINUX-PROBE.sh` present;
- `packaging/rc7.2/AITEST.sh` present;
- `rc7_release/rc72_target_linux_attestation.py` present with package-evidence binding;
- `rc7_release/rc72_target_linux_reality.py` present with the strengthened release path.

### Q2-B

- exact Q2-A transport download: PASS
- second clean extraction: PASS
- clean-package R1 / Session A -> B -> C continuity: PASS
- active session: `SESSION-C`
- chat history transferred: `false`
- business root: `RELEASE_BATCH`
- runtime control backbone: `N1_N10_MISSION_GRAPH`
- real Git Bash entrypoint engineering probe: PASS
- isolated profile: `rc7.2-bank`
- mature RC7 delegate path: `packaging/rc7/AITEST.sh`
- `offline_payload_verified=false`
- `field_verified=false`
- `bank_final=false`
- artifact id: `12872715575`
- artifact digest: `sha256:e874280b8eddd0c10d1e69fc1957ab114f2462d76206c81d169bddf599592706`

Complete offline DSH/plugin/tool payload qualification remains Q4. No Q4 payload claim was used to close Q2.

Checkpoint: `checkpoints/Q2-WINDOWS-CLEAN-UNPACK-CI-PASS.md`.

## 5. Q3 — Target 信创 Linux

Status:

```yaml
reality_binding_contract: CI_PASS
target_probe_contract: CI_PASS
field_handoff_contract: CI_PASS
external_attestation_boundary: CI_PASS
generic_linux_negative_control: PASS
target_linux: HOLD_TARGET_ENVIRONMENT_BINDING_REQUIRED
target_linux_verified: false
field_verified: false
bank_final: false
```

Qualified functional head: `495a12f35430443d7f9cfb59ad6691894a8c8125`.

Workflow run: `40815666715`, SUCCESS.

Artifact:

- id: `12872261627`
- name: `rc72-q3-generic-linux-negative-control-495a12f35430443d7f9cfb59ad6691894a8c8125`
- digest: `sha256:099237561300c9e049a2d4dbf8972e6fdccd2219a1294fbd103199cec38548f1`
- Q3 contracts: `28 passed`

Implemented and qualified on the same functional SHA:

1. packageable `packaging/rc7.2/Q3-TARGET-LINUX-PROBE.sh`;
2. packageable `packaging/rc7.2/Q3-FIELD-HANDOFF.sh`;
3. observation-only OS/arch/Python/shell/source/runner identity capture;
4. transported-package evidence with critical-file SHA-256 digests;
5. no network install and no self-approval in probe/handoff;
6. attestation request bound to exact observation digest and transported-package evidence digest;
7. trusted external verifier boundary restricted to approved verifier kinds;
8. fail-closed source, dual-digest and machine identity matching;
9. local-file/self-reported/model approval remains untrusted;
10. the legacy reality positive path delegates to the same strong attestation evaluator, so no weaker PASS bypass remains;
11. Q3 can never set `bank_final=true`.

The engineering handoff generated on generic Ubuntu remains deliberately awaiting external attestation. Its transported-package evidence digest was:

`fca93c2bf518ee524d2edd0a98f4d58bfcc8746358c3e169e16c7a11ff718154`

Content-level generic Linux evidence remains deliberately HOLD:

```yaml
source_commit: 495a12f35430443d7f9cfb59ad6691894a8c8125
platform_family: Ubuntu
platform_release: "24.04"
architecture: x86_64
runner_kind: GITHUB_HOSTED_GENERIC
status: HOLD
reason: GENERIC_LINUX_PROXY_NOT_TARGET
target_linux_verified: false
field_verified: false
bank_final: false
```

Workflow SUCCESS proves the Q3 mechanism, package handoff and negative-control policy behave correctly. It does **not** mean a real target 信创 Linux environment passed qualification.

Trusted verifier kinds remain restricted to:

- `APPROVED_SELF_HOSTED_TARGET_LINUX`
- `BANK_FIELD_TARGET_LINUX`

Generic hosted Ubuntu, local file approval, model assertion, self-reported approval, missing package evidence, source mismatch, observation-digest mismatch, package-evidence-digest mismatch or machine mismatch cannot promote Q3.

Checkpoint: `checkpoints/Q3-TARGET-LINUX-REALITY-CONTRACT-HOLD.md`.

### Next Q3 slice

`Q3_REAL_TARGET_INVOCATION_AND_TRUSTED_ATTESTATION_BINDING`

Next execution must use an actual approved target 信创 Linux environment and the packageable field handoff from exact source lineage. The real target handoff must create observation + transported-package evidence + request + manifest. A trusted external attestation must bind to the same source, observation digest, package-evidence digest and machine identity before Q3 may PASS.

Until that real target evidence exists:

- `target_linux_verified=false`
- `field_verified=false`
- Q3 remains HOLD
- Q4 qualification remains blocked

## 6. Later gates

```yaml
q4_offline_portable: NOT_RUN
q5_real_browser_bsk: NOT_RUN
q6_real_human_approval: NOT_RUN
q7_real_release_batch: NOT_RUN
q8_failure_recovery: NOT_RUN
q9_bank_final: NO
```

## 7. Anti-drift rule

Always verify:

```text
current work/rc7.2 HEAD
+ same-HEAD source
+ same-HEAD CI/check-runs
+ frozen 00-05 and 07 contracts
+ CURRENT-CHECKPOINT.md
+ this ledger
+ R1/evidence where applicable
```

If these differ, live repository/R1/CI/Evidence truth wins and the ledger must be corrected in the same construction turn.
