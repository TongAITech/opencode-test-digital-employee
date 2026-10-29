# RC7.2 Construction Plan / Checkpoint Ledger

Status: **REPOSITORY_CONSTRUCTION_CI_PASS / Q1_CI_PASS / Q2_CI_PASS_ENGINEERING_ONLY / Q3_NOT_RUN / FIELD_VALIDATION_PENDING**

Future sessions MUST read current branch HEAD, same-HEAD CI, frozen contracts, this ledger and `CURRENT-CHECKPOINT.md`. Live repository/R1/CI truth overrides stale chat history or stale SHAs.

## 1. Repository construction

Phase 0-9 repository construction is closed at repository CI level.

- repository functional head before qualification additions: `d43f233ace9c691f881a8b5e0d5be23257b9c5f5`
- original construction run: `40737549865`
- original RC7.2 contracts: `206 passed` on Python 3.8 and Python 3.11
- original inherited RC7: `492 passed, 1 skipped`
- Phase 9 remains `CI_PASS_FIELD_PENDING`

Latest Q2-qualified implementation source before documentation checkpoint:

- `1b4f8ebb4612660ff07d93cdf6bf5b22c30e1d22`
- construction run `40801951720`
- RC7.2 contracts Python 3.8: `225 passed`
- RC7.2 contracts Python 3.11: `225 passed`
- inherited RC7: `492 passed, 1 skipped`

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

Latest same-Q2-code-head run: `40801951774` on `1b4f8ebb...`.

- Windows engineering: SUCCESS
- Linux engineering proxy: SUCCESS
- Q1 summary: SUCCESS

Q1 proves Windows and generic Linux engineering portability. The generic Linux runner is not target 信创 Linux Field qualification.

Checkpoint: `checkpoints/Q1-SOURCE-PLATFORM-BASELINE-CI-PASS.md`.

## 4. Q2 — Windows clean-unpack

Status: `CI_PASS_ENGINEERING_ONLY`.

Qualified implementation/source commit: `1b4f8ebb4612660ff07d93cdf6bf5b22c30e1d22`.

Workflow run: `40801952853`, SUCCESS.

### Q2-A — Package identity / clean extraction

Status: PASS.

Evidence:

- exact RC7.2 package identity, not renamed RC7;
- RC7.2 ZIP + SHA sidecar created and verified;
- build root deleted before re-extraction;
- clean extraction into fresh Windows runner directory;
- package-local Python used with source `PYTHONPATH` cleared;
- RC7.2 manifest/checksum/identity verify PASS;
- all current `rc7_runtime/rc72_*.py` modules imported from clean package;
- artifact id: `12866442208`;
- artifact digest: `sha256:ec7aff88831c5fdc7efce7919a44612f0d024010c2dbf6d9b5bd053c992e32b0`;
- `field_verified=false`, `bank_final=false`.

### Q2-B — Clean runtime / R1 / Session / Git Bash

Status: PASS.

Artifact:

- id: `12866217593`
- digest: `sha256:1f4539e6e046d3944ceecaed1ddb63a6dbfbbadc3814c48b6062c0a7b36eb232`

Content-level evidence proves:

1. clean package runs with package-local Python;
2. RC7.2 exact source lineage is preserved;
3. Mission Graph v2 boots from clean transport;
4. Reality Recon is runtime-owned and Requirement Analysis routes to Producer Worker;
5. R1 is durable across runtime recreation;
6. the same active task hands off Session A -> B -> C;
7. handoff generations are 1 and 2, final owner is `SESSION-C`;
8. no conversation/transcript is transferred;
9. Git Bash entrypoint performs strict RC7.2 package verify;
10. Q2 Git Bash probe proves isolated profile `rc7.2-bank` and delegate `packaging/rc7/AITEST.sh`;
11. probe explicitly records `field_verified=false`, `bank_final=false`, `offline_payload_verified=false`.

The Q2 probe does not bypass or weaken default startup. Default RC7.2 startup still delegates to the mature RC7 launcher. Complete offline DSH/plugin/tool payload qualification is intentionally deferred to Q4, per the frozen contract.

Checkpoint: `checkpoints/Q2-WINDOWS-CLEAN-UNPACK-CI-PASS.md`.

Q2 is engineering evidence. In-bank Windows confirmation is still part of later Field acceptance.

## 5. Q3 — Target 信创 Linux

Status: `NOT_RUN`.

Next atomic step: `Q3_TARGET_LINUX_REALITY_CONTRACT`.

The first Q3 slice must prove target-environment identity before any target-Linux PASS is possible. Generic GitHub Ubuntu remains only an engineering proxy. If no approved self-hosted/target 信创 Linux runner or equivalent Field evidence is bound, Q3 must return HOLD/fail-closed rather than fabricate PASS.

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
