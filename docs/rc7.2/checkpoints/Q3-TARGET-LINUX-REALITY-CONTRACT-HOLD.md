# RC7.2 Q3 Target Linux Reality Binding — Contract PASS / Target HOLD Checkpoint

Status: **REALITY_BINDING_CONTRACT_CI_PASS / TARGET_LINUX_HOLD / FIELD_VALIDATION_PENDING / BANK_FINAL_NO**

Qualified functional head: `55ee7d96e6036fa46b4c171032c934313fd90426`

## Same-HEAD evidence set

All qualification evidence below is from the same functional source SHA `55ee7d96e6036fa46b4c171032c934313fd90426`.

### Construction

Workflow run: `40803275491`

- RC7.2 contracts Python 3.8: `237 passed`
- RC7.2 contracts Python 3.11: `237 passed`
- inherited RC7 regression: `492 passed, 1 skipped`
- runtime/release compile: PASS

The Construction workflow now includes `rc7_release/**` in its trigger surface so release/qualification-layer changes cannot bypass the same-head Py3.8/Py3.11 contract gate.

### Q1 source-platform baseline

Workflow run: `40803275548`

- Windows engineering: SUCCESS
- Linux engineering proxy: SUCCESS
- Q1 summary: SUCCESS
- Windows artifact id: `12866069888`
- Windows artifact digest: `sha256:33ecbfaadac690327cd103360f3c87c2a67b29c0f7c7a2e0ec33e9f7c0d44285`
- Linux proxy artifact id: `12867275735`
- Linux proxy artifact digest: `sha256:fcbaedceb4a5d9a4a39ca828cc484f9ddc5bb78efebb14a12721f14b6fe6cc64`

Q1 remains engineering-only. Generic Linux is not target 信创 Linux evidence.

### Q2 Windows clean-unpack

Workflow run: `40803275565`

- Q2-A package identity / clean extraction: SUCCESS
- Q2-B clean R1 / Session A->B->C / Git Bash entrypoint probe: SUCCESS
- Q2-A artifact id: `12866777873`
- Q2-A artifact digest: `sha256:0ed00e4a1887ff260b8ad7f5f502bed9d14ae458bed283c56a8bbc4a1e6a5206`
- Q2-B artifact id: `12866393853`
- Q2-B artifact digest: `sha256:579a7372f64ad755ff9ddde88472460b7bc0e8227ac0357db5953d6886fc4ff7`

Q2 remains `CI_PASS_ENGINEERING_ONLY`; `offline_payload_verified=false`, `field_verified=false`, `bank_final=false`.

### Q3 target Linux reality binding

Workflow run: `40803275534`

Policy/negative-control job: SUCCESS.

Artifact:

- id: `12866722683`
- name: `rc72-q3-generic-linux-negative-control-55ee7d96e6036fa46b4c171032c934313fd90426`
- digest: `sha256:2c84cb8b498dc37737c645aa69b1e9cbf7108c337153c7c5e2084e6d49454f72`

Content-level evidence was inspected. The observed hosted machine is:

```yaml
source_commit: 55ee7d96e6036fa46b4c171032c934313fd90426
platform_family: Ubuntu
platform_release: "24.04"
architecture: x86_64
python_version: 3.8.18
runner_kind: GITHUB_HOSTED_GENERIC
runner_identity: github-hosted-ubuntu
status: HOLD
reason: GENERIC_LINUX_PROXY_NOT_TARGET
target_linux_verified: false
field_verified: false
bank_final: false
```

Evidence refs include `probe://os-release` and `probe://uname`.

This is the intended result. Workflow SUCCESS means the fail-closed policy worked; it does **not** mean target Linux qualification passed.

## Q3 decision

```yaml
q3_reality_binding_contract: CI_PASS
q3_generic_linux_negative_control: PASS
q3_target_linux: HOLD_TARGET_ENVIRONMENT_BINDING_REQUIRED
target_linux_verified: false
field_verified: false
bank_final: false
```

Q3 cannot become PASS until an exact-source target Linux observation is paired with an externally trusted target attestation whose machine identity and source lineage match.

Trusted verifier kinds are deliberately restricted to:

- `APPROVED_SELF_HOSTED_TARGET_LINUX`
- `BANK_FIELD_TARGET_LINUX`

A contract verifier, GitHub-hosted Ubuntu, model assertion, self-reported `approved=true`, or unmatched attestation cannot promote Q3.

## Next atomic step

`Q3_TARGET_SIDE_PROBE_AND_ATTESTATION_INGESTION_TESTS_FIRST`

Build the target-side mechanism needed to unblock this HOLD:

1. a packageable `packaging/rc7.2/Q3-TARGET-LINUX-PROBE.sh` that collects exact source lineage, `/etc/os-release`, `uname -m`, Python, shell and runner identity without installing anything and without self-approving;
2. an attestation ingestion/verifier boundary that consumes externally approved target evidence and feeds `evaluate_target_linux_reality`;
3. tests proving probe output cannot claim PASS/approval, source/machine mismatches fail closed, and only trusted external target attestation can change HOLD to PASS.

Do **not** start Q4 qualification while Q3 remains HOLD. Q4 design/work may be read-only prepared, but qualification sequencing remains blocked by Q3.
