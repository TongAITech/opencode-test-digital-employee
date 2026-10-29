# RC7.2 Platform Qualification & Field Acceptance Contract

Status: **FROZEN QUALIFICATION BASELINE**

This contract begins after repository construction Phase 0-9 has reached CI qualification. It does not create a new architecture phase and it does not redefine the frozen RC7.2 runtime contracts.

## 1. Truth and anti-drift rules

Qualification truth is ordered as follows:

```text
current work/rc7.2 HEAD
+ same-HEAD qualification CI/check-runs
+ qualification evidence artifacts
+ canonical R1 / Field evidence
+ this contract
```

Chat history, stale SHAs, old package names and inherited RC7/RC7.1 qualification results cannot prove RC7.2 Field readiness.

A reused RC7/RC7.1 workflow or tool is an implementation asset only. It is not evidence that RC7.2 has passed the corresponding gate.

## 2. Required qualification gates

| Gate | Scope | Mandatory evidence | Repository runner may satisfy? | Field required? |
|---|---|---|---|---|
| Q0 | Repository construction | Phase 0-9 contracts + inherited regression | yes | no |
| Q1 | Source platform baseline | RC7.2 contracts + inherited RC7 regression on Windows and Linux engineering proxy | yes | no |
| Q2 | Windows clean-unpack | build, checksum, re-extract, package-local runtime, Git Bash entrypoint | yes | later bank-PC confirmation |
| Q3 | Target Linux | target distro/architecture runtime, shell entrypoint, package-local dependencies | no generic Ubuntu substitution | yes or approved self-hosted target |
| Q4 | Offline/portable delivery | no network install at runtime, payload inventory, checksum, clean workspace | partially | yes |
| Q5 | Browser/BSK | real adapter + BrowserLease ownership + real replay evidence | no contract stub | yes |
| Q6 | Human approval | trusted bank verifier + exact attestation scope/version digest | no contract verifier | yes |
| Q7 | Real ReleaseBatch mission | ReleaseBatch-rooted N1-N10 mission with Requirement/SST/Obligation lineage | no fixture mission | yes |
| Q8 | Failure/recovery exercise | semantic back-edge, capability/browser/provider/session recovery and real product failure classification | partially | yes |
| Q9 | BANK_FINAL | all mandatory gates PASS with R1 evidence | no | yes |

## 3. Q1 source-platform baseline

Q1 is an engineering portability gate only.

It MUST run the same RC7.2 source HEAD on:

- Windows engineering runner, Python 3.8;
- Linux engineering proxy runner, Python 3.8.

Each runner MUST:

1. compile `rc6_runtime`, `rc7_runtime`, and `rc7_release`;
2. run all `tests/test_rc72_*.py` contracts;
3. run all inherited `tests/test_rc7_*.py` regressions;
4. emit a structured evidence record bound to the exact source commit;
5. mark `field_verified=false` and `bank_final=false`.

The generic Ubuntu runner MUST be labelled `LINUX_ENGINEERING_PROXY`. It MUST NOT be reported as target 信创 Linux qualification.

## 4. Evidence schema

Every qualification gate evidence record MUST identify at least:

```text
schema
qualification_id
qualification_kind
source_commit
platform_family
platform_release
architecture
python_version
status
started_at / completed_at (where available)
evidence_refs[]
field_verified
bank_final
notes[]
```

Allowed status values:

```text
PASS
FAIL
HOLD
NOT_RUN
```

`field_verified=true` is forbidden for repository contract adapters, GitHub-hosted generic runners, fake browser hosts, fixture Human verifiers or fixture ReleaseBatch missions.

## 5. Reuse policy

The following inherited assets SHOULD be reused rather than reimplemented:

- RC7 field-hardening source regression;
- RC7 Windows clean-package build/re-extract patterns;
- RC7.1 Turnkey checksum and delivery qualification;
- Git Bash launch qualification;
- existing package-local Python/runtime payload verification;
- existing signed Worker lease and R1 truth infrastructure.

Reuse MUST preserve RC7.2 semantics and exact source identity. A package built from an RC7.2 HEAD must not claim RC7.1 identity.

## 6. Qualification sequencing

The mandatory sequence is:

```text
Q1 source platform baseline
 -> Q2 Windows clean-unpack
 -> Q3 target Linux
 -> Q4 offline/portable
 -> Q5 real Browser/BSK
 -> Q6 real Human Approval
 -> Q7 real ReleaseBatch N1-N10
 -> Q8 recovery/failure exercises
 -> Q9 BANK_FINAL decision
```

A later gate may be prepared in parallel, but it cannot be marked PASS by skipping an earlier mandatory gate.

## 7. Fail-closed rules

The following are qualification failures or HOLD conditions, never PASS:

- Windows-only success with no Linux engineering result;
- Ubuntu success presented as target 信创 Linux success;
- package test performed only in the source checkout instead of clean extraction;
- runtime that downloads missing dependencies from the public Internet;
- contract/fake Browser adapter presented as Field BSK evidence;
- contract Human verifier presented as bank approval evidence;
- fixture mission presented as real ReleaseBatch evidence;
- missing R1 evidence for Field claims;
- coverage percentage used as the sole ReleaseBatch readiness proof.

## 8. Current baseline

At contract creation, the expected starting state is:

```text
repository_construction: CI_PASS
q1_source_platform_baseline: NOT_RUN
q2_windows_clean_unpack: NOT_RUN
q3_target_linux: NOT_RUN
q4_offline_portable: NOT_RUN
q5_real_browser_bsk: NOT_RUN
q6_real_human_approval: NOT_RUN
q7_real_release_batch: NOT_RUN
q8_failure_recovery: NOT_RUN
field_validation: PENDING
bank_final: NO
```

Only evidence produced after this contract is attached to the same RC7.2 lineage may advance these gates.
