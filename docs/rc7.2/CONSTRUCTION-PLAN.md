# RC7.2 Construction Plan / Checkpoint Ledger

Status: **REPOSITORY_CONSTRUCTION_CI_PASS / Q1_CI_PASS / Q2_CI_PASS_ENGINEERING_ONLY / Q3_TARGET_PROBE_ATTESTATION_CONTRACT_PASS_TARGET_HOLD / FIELD_VALIDATION_PENDING**

Future sessions MUST read current branch HEAD, same-HEAD CI, frozen contracts, this ledger and `CURRENT-CHECKPOINT.md`. Live repository/R1/CI/Evidence truth overrides stale chat history or stale SHAs.

## 1. Repository construction

Phase 0-9 repository construction is closed at repository CI level.

Original repository functional head before qualification additions:

- `d43f233ace9c691f881a8b5e0d5be23257b9c5f5`
- run `40737549865`
- RC7.2 contracts: `206 passed` on Python 3.8 and Python 3.11
- inherited RC7: `492 passed, 1 skipped`

Latest same-head qualified functional source:

- `43f9ec4350b87b257e97ce17b929c6a174951667`
- Construction run `40807619555`
- RC7.2 contracts Python 3.8: `244 passed`
- RC7.2 contracts Python 3.11: `244 passed`
- inherited RC7: `492 passed, 1 skipped`

The Construction workflow includes `rc7_release/**`, so qualification/release-layer changes cannot bypass full same-head contract validation.

Repository CI is not Field validation and not BANK_FINAL.

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

Same-head run: `40807619559` on `43f9ec4350b87b257e97ce17b929c6a174951667`.

- Windows engineering: SUCCESS
- Linux engineering proxy: SUCCESS
- Q1 summary: SUCCESS
- Windows artifact id: `12868493488`
- Windows artifact digest: `sha256:306c029f716b5e5f3c78397d00f46d28c658275466b55dde548c43eabfefbf34`
- Linux proxy artifact id: `12869200738`
- Linux proxy artifact digest: `sha256:dd18c3493365c177064d27b8f45339e7de49a50b1de6c0291056ef4add576f8b`

Q1 proves Windows and generic Linux engineering portability only. Generic Linux is not target 信创 Linux Field evidence.

Checkpoint: `checkpoints/Q1-SOURCE-PLATFORM-BASELINE-CI-PASS.md`.

## 4. Q2 — Windows clean-unpack

Status: `CI_PASS_ENGINEERING_ONLY`.

Same-head workflow run: `40807619582` on `43f9ec4350b87b257e97ce17b929c6a174951667`.

### Q2-A

- exact-lineage package build: PASS
- delete build root + clean re-extract: PASS
- package-local Python / identity / strict checksum verification: PASS
- artifact id: `12868024787`
- artifact digest: `sha256:ab67834c755119becfa83bd4c63bd0b5d965401a75e32eb5f0a0a8cba4d62331`

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
- artifact id: `12868862232`
- artifact digest: `sha256:c147da9be86ce13f51df574ba14bfef11f7f3abe52242394a63f29fedc5829e6`

Complete offline DSH/plugin/tool payload qualification remains Q4. No Q4 payload claim was used to close Q2.

Checkpoint: `checkpoints/Q2-WINDOWS-CLEAN-UNPACK-CI-PASS.md`.

## 5. Q3 — Target 信创 Linux

Status:

```yaml
reality_binding_contract: CI_PASS
target_probe_contract: CI_PASS
external_attestation_boundary: CI_PASS
generic_linux_negative_control: PASS
target_linux: HOLD_TARGET_ENVIRONMENT_BINDING_REQUIRED
target_linux_verified: false
field_verified: false
bank_final: false
```

Qualified functional head: `43f9ec4350b87b257e97ce17b929c6a174951667`.

Workflow run: `40807619551`, SUCCESS.

Artifact:

- id: `12868593591`
- name: `rc72-q3-generic-linux-negative-control-43f9ec4350b87b257e97ce17b929c6a174951667`
- digest: `sha256:6ace4b493bb5f5f3935074900ce22c1f624d1f7c0b52a28904f326548d9257f3`
- Q3 contracts: `19 passed`

Implemented and qualified on the same functional SHA:

1. packageable `packaging/rc7.2/Q3-TARGET-LINUX-PROBE.sh`;
2. observation-only OS/arch/Python/shell/source/runner identity capture;
3. no network install and no self-approval in the probe;
4. digest-bound target attestation request;
5. trusted external verifier boundary;
6. fail-closed source, observation-digest and machine identity matching;
7. local-file/self-reported approval remains untrusted;
8. Q3 can never set `bank_final=true`.

Content-level generic Linux evidence remains deliberately HOLD:

```yaml
source_commit: 43f9ec4350b87b257e97ce17b929c6a174951667
platform_family: Ubuntu
platform_release: "24.04"
architecture: x86_64
python_version: 3.8.18
runner_kind: GITHUB_HOSTED_GENERIC
status: HOLD
reason: GENERIC_LINUX_PROXY_NOT_TARGET
target_linux_verified: false
field_verified: false
bank_final: false
```

The attestation request is `AWAITING_EXTERNAL_ATTESTATION` and is bound to observation digest:

`3b2f250b95a2533b5a2ac518227efd7e26820731e802fb07ce64fc3f19d74a5b`

Workflow SUCCESS proves the Q3 mechanism and negative-control policy behave correctly. It does **not** mean a real target 信创 Linux environment passed qualification.

Trusted verifier kinds remain restricted to:

- `APPROVED_SELF_HOSTED_TARGET_LINUX`
- `BANK_FIELD_TARGET_LINUX`

Generic hosted Ubuntu, local file approval, model assertion, self-reported approval, source mismatch, digest mismatch or machine mismatch cannot promote Q3.

Checkpoint: `checkpoints/Q3-TARGET-LINUX-REALITY-CONTRACT-HOLD.md`.

### Next Q3 slice

`Q3_REAL_TARGET_INVOCATION_AND_TRUSTED_ATTESTATION_BINDING`

Next execution must use an actual approved target 信创 Linux environment and the packageable probe from exact source lineage. Capture a real observation, obtain trusted external attestation bound to the same source/digest/machine identity, then feed that evidence through the Q3 verifier.

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
