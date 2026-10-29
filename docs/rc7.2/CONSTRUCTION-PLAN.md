# RC7.2 Construction Plan / Checkpoint Ledger

Status: **REPOSITORY_CONSTRUCTION_CI_PASS / Q1_CI_PASS / Q2A_CI_PASS / Q2_IN_PROGRESS / FIELD_VALIDATION_PENDING**

Future sessions MUST read current branch HEAD, same-HEAD CI, frozen contracts, this ledger and `CURRENT-CHECKPOINT.md`. Live repository/R1/CI truth overrides stale chat history or stale SHAs.

## 1. Repository construction

Phase 0-9 repository construction is closed at repository CI level.

- repository functional head before qualification additions: `d43f233ace9c691f881a8b5e0d5be23257b9c5f5`
- run: `40737549865`
- RC7.2 contracts: `206 passed` on Python 3.8 and Python 3.11
- inherited RC7: `492 passed, 1 skipped`
- Phase 9 remains `CI_PASS_FIELD_PENDING`

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

Original qualified source: `77e954558f1fdc933febe2adfeb8a069d3d92c00`, run `40791919277`.

Q1 proves Windows and generic Linux engineering portability. The generic Linux runner is not target 信创 Linux Field qualification.

Checkpoint: `checkpoints/Q1-SOURCE-PLATFORM-BASELINE-CI-PASS.md`.

## 4. Q2 — Windows clean-unpack

Status: `IN_PROGRESS`.

### Q2-A — Package identity / clean extraction

Status: `CI_PASS_ENGINEERING_ONLY`.

Qualified source: `120b16143fd5487706156b75c1c86168f642c024`.

Q2-A workflow: `40794043110`, SUCCESS.

Evidence:

- Q2-A contract tests: `8 passed`;
- exact RC7.2 package identity, not renamed RC7;
- RC7.2 ZIP + SHA sidecar created and verified;
- build root deleted before re-extraction;
- clean extraction into fresh runner directory;
- package-local Python used with source `PYTHONPATH` cleared;
- RC7.2 manifest/checksum/identity verify PASS;
- all `26` current `rc7_runtime/rc72_*.py` modules imported from clean package;
- package file count: `4798`;
- artifact id: `12861954949`;
- artifact digest: `sha256:649caabe2aea50eaca6d11070a49ac48055d9d005efe98b270c2fa101912c56f`;
- `field_verified=false`, `bank_final=false`.

Same HEAD source-regression evidence:

- Q1 Windows engineering: SUCCESS;
- Windows RC7.2 contracts: `218 passed`;
- Windows inherited RC7: `492 passed, 1 skipped`;
- Q1 Linux engineering proxy: SUCCESS;
- Q1 summary: SUCCESS.

Checkpoint: `checkpoints/Q2A-WINDOWS-PACKAGE-IDENTITY-CLEAN-UNPACK-CI-PASS.md`.

### Q2-B — Clean runtime / Git Bash

Status: `NOT_RUN`.

Next atomic step: `Q2B_WINDOWS_CLEAN_RUNTIME_AND_GIT_BASH_TESTS_FIRST`.

Q2-B MUST reuse existing RC7 qualification/runtime continuity logic instead of cloning it. It must prove:

1. RC7.2 verifier and exact source lineage from clean package;
2. package-local Python only;
3. durable R1 truth across runtime recreation;
4. session A→B→C continuity without conversation/transcript transfer;
5. Git Bash entrypoint can run from clean package with a controlled engineering DSH harness;
6. engineering harness never produces Field/BANK_FINAL claims.

Q2 overall cannot PASS until Q2-B is green.

## 5. Later gates

```yaml
q3_target_linux: NOT_RUN
q4_offline_portable: NOT_RUN
q5_real_browser_bsk: NOT_RUN
q6_real_human_approval: NOT_RUN
q7_real_release_batch: NOT_RUN
q8_failure_recovery: NOT_RUN
q9_bank_final: NO
```

Do not begin Q3 until Q2 is checkpointed complete.

## 6. Anti-drift rule

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
