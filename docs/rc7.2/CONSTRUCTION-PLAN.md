# RC7.2 Construction Plan / Checkpoint Ledger

Status: **REPOSITORY_CONSTRUCTION_CI_PASS / Q1_CI_PASS / Q2_CI_PASS_ENGINEERING_ONLY / Q3_REALITY_CONTRACT_PASS_TARGET_HOLD / FIELD_VALIDATION_PENDING**

Future sessions MUST read current branch HEAD, same-HEAD CI, frozen contracts, this ledger and `CURRENT-CHECKPOINT.md`. Live repository/R1/CI truth overrides stale chat history or stale SHAs.

## 1. Repository construction

Phase 0-9 repository construction is closed at repository CI level.

Original repository functional head before qualification additions:

- `d43f233ace9c691f881a8b5e0d5be23257b9c5f5`
- run `40737549865`
- RC7.2 contracts: `206 passed` on Python 3.8 and Python 3.11
- inherited RC7: `492 passed, 1 skipped`

Latest same-head qualified functional source:

- `55ee7d96e6036fa46b4c171032c934313fd90426`
- Construction run `40803275491`
- RC7.2 contracts Python 3.8: `237 passed`
- RC7.2 contracts Python 3.11: `237 passed`
- inherited RC7: `492 passed, 1 skipped`

The Construction workflow now includes `rc7_release/**` so qualification/release-layer changes cannot bypass full same-head contract validation.

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

## 3. Q1 — Source platform engineering baseline

Status: `CI_PASS_ENGINEERING_ONLY`.

Latest same-head run: `40803275548` on `55ee7d96...`.

- Windows engineering: SUCCESS
- Linux engineering proxy: SUCCESS
- Q1 summary: SUCCESS
- Windows artifact id: `12866069888`
- Windows artifact digest: `sha256:33ecbfaadac690327cd103360f3c87c2a67b29c0f7c7a2e0ec33e9f7c0d44285`
- Linux proxy artifact id: `12867275735`
- Linux proxy artifact digest: `sha256:fcbaedceb4a5d9a4a39ca828cc484f9ddc5bb78efebb14a12721f14b6fe6cc64`

Q1 proves Windows and generic Linux engineering portability only. Generic Linux is not target 信创 Linux Field evidence.

Checkpoint: `checkpoints/Q1-SOURCE-PLATFORM-BASELINE-CI-PASS.md`.

## 4. Q2 — Windows clean-unpack

Status: `CI_PASS_ENGINEERING_ONLY`.

Latest same-head workflow run: `40803275565` on `55ee7d96...`.

### Q2-A

- package identity / clean extraction: PASS
- artifact id: `12866777873`
- artifact digest: `sha256:0ed00e4a1887ff260b8ad7f5f502bed9d14ae458bed283c56a8bbc4a1e6a5206`
- exact RC7.2 identity, ZIP SHA, clean extraction, package-local Python, RC7.2 module imports all verified.

### Q2-B

- clean R1 / Session A -> B -> C / Git Bash entrypoint probe: PASS
- artifact id: `12866393853`
- artifact digest: `sha256:579a7372f64ad755ff9ddde88472460b7bc0e8227ac0357db5953d6886fc4ff7`
- no chat history transferred;
- isolated profile `rc7.2-bank`;
- default startup still delegates to mature RC7 launcher;
- Q2 engineering probe records `offline_payload_verified=false`, `field_verified=false`, `bank_final=false`.

Complete offline DSH/plugin/tool payload qualification remains Q4.

Checkpoint: `checkpoints/Q2-WINDOWS-CLEAN-UNPACK-CI-PASS.md`.

## 5. Q3 — Target 信创 Linux

Status:

```yaml
reality_binding_contract: CI_PASS
generic_linux_negative_control: PASS
target_linux: HOLD_TARGET_ENVIRONMENT_BINDING_REQUIRED
target_linux_verified: false
field_verified: false
bank_final: false
```

Qualified functional head: `55ee7d96e6036fa46b4c171032c934313fd90426`.

Workflow run: `40803275534`, SUCCESS.

Artifact:

- id: `12866722683`
- digest: `sha256:2c84cb8b498dc37737c645aa69b1e9cbf7108c337153c7c5e2084e6d49454f72`

Content-level evidence:

```yaml
platform_family: Ubuntu
platform_release: "24.04"
architecture: x86_64
runner_kind: GITHUB_HOSTED_GENERIC
runner_identity: github-hosted-ubuntu
status: HOLD
reason: GENERIC_LINUX_PROXY_NOT_TARGET
target_linux_verified: false
field_verified: false
bank_final: false
```

This is the intended fail-closed result. Workflow SUCCESS proves the policy gate behaves correctly; it does not mean target Linux qualification passed.

Q3 PASS requires exact-source observation from a real/approved target plus trusted external target attestation. Contract verifier, model assertion, self-reported approval or generic Ubuntu cannot promote Q3.

Checkpoint: `checkpoints/Q3-TARGET-LINUX-REALITY-CONTRACT-HOLD.md`.

### Next Q3 slice

`Q3_TARGET_SIDE_PROBE_AND_ATTESTATION_INGESTION_TESTS_FIRST`

Implement:

1. packageable target-side `Q3-TARGET-LINUX-PROBE.sh` that only observes source/OS/arch/Python/shell/runner identity and never self-approves;
2. external target-attestation ingestion/verifier boundary;
3. contracts for source mismatch, machine mismatch, untrusted verifier, generic proxy and exact trusted target approval;
4. a Field/self-hosted invocation path that can later consume a real target attestation without embedding fake approval in the package.

Do not start Q4 qualification while Q3 remains HOLD.

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

If these differ, live repository/R1/CI truth wins and the ledger must be corrected in the same construction turn.
