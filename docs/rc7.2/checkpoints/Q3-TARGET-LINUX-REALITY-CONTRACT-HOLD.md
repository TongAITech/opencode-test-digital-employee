# RC7.2 Q3 Target Linux Reality Binding — Mechanism PASS / Real Target HOLD Checkpoint

Status: **REALITY_BINDING_CONTRACT_CI_PASS / TARGET_PROBE_CI_PASS / EXTERNAL_ATTESTATION_BOUNDARY_CI_PASS / TARGET_LINUX_HOLD / FIELD_VALIDATION_PENDING / BANK_FINAL_NO**

Qualified functional head: `43f9ec4350b87b257e97ce17b929c6a174951667`

## Same-HEAD evidence set

All qualification evidence below is from the same functional source SHA `43f9ec4350b87b257e97ce17b929c6a174951667`.

### Construction

Workflow run: `40807619555`

- RC7.2 contracts Python 3.8: `244 passed`
- RC7.2 contracts Python 3.11: `244 passed`
- inherited RC7 regression: `492 passed, 1 skipped`
- runtime/release compile: PASS

### Q1 source-platform baseline

Workflow run: `40807619559`

- Windows engineering: SUCCESS
- Linux engineering proxy: SUCCESS
- Q1 summary: SUCCESS
- Windows artifact id: `12868493488`
- Windows artifact digest: `sha256:306c029f716b5e5f3c78397d00f46d28c658275466b55dde548c43eabfefbf34`
- Linux proxy artifact id: `12869200738`
- Linux proxy artifact digest: `sha256:dd18c3493365c177064d27b8f45339e7de49a50b1de6c0291056ef4add576f8b`

Q1 remains engineering-only. Generic Linux is not target 信创 Linux Field evidence.

### Q2 Windows clean-unpack

Workflow run: `40807619582`

Q2-A:

- exact-lineage package build: SUCCESS
- delete build root + clean re-extract: SUCCESS
- strict identity/checksum + package-local runtime: SUCCESS
- artifact id: `12868024787`
- artifact digest: `sha256:ab67834c755119becfa83bd4c63bd0b5d965401a75e32eb5f0a0a8cba4d62331`

Q2-B:

- exact Q2-A transport download + second clean extract: SUCCESS
- clean R1 / Session A->B->C continuity: SUCCESS
- active session: `SESSION-C`
- chat history transferred: `false`
- business root: `RELEASE_BATCH`
- runtime backbone: `N1_N10_MISSION_GRAPH`
- real Git Bash engineering entrypoint probe: SUCCESS
- profile: `rc7.2-bank`
- mature delegate: `packaging/rc7/AITEST.sh`
- `offline_payload_verified=false`
- `field_verified=false`
- `bank_final=false`
- artifact id: `12868862232`
- artifact digest: `sha256:c147da9be86ce13f51df574ba14bfef11f7f3abe52242394a63f29fedc5829e6`

Q2 remains `CI_PASS_ENGINEERING_ONLY`. No Q4 payload claim was used.

### Q3 target Linux reality binding and target-side mechanism

Workflow run: `40807619551`, SUCCESS.

Artifact:

- id: `12868593591`
- name: `rc72-q3-generic-linux-negative-control-43f9ec4350b87b257e97ce17b929c6a174951667`
- digest: `sha256:6ace4b493bb5f5f3935074900ce22c1f624d1f7c0b52a28904f326548d9257f3`
- contract tests: `19 passed`

The target-side engineering mechanism is now present:

- `packaging/rc7.2/Q3-TARGET-LINUX-PROBE.sh`
- `rc7_release/rc72_target_linux_attestation.py`

The probe is observation-only. It captures exact source, `/etc/os-release`, `uname -m`, Python, shell, runner kind and runner identity. It contains no package installation path and no self-approval path.

The attestation boundary:

- produces an `AWAITING_EXTERNAL_ATTESTATION` request;
- binds the request to exact observation SHA-256 digest;
- accepts only trusted external verifier kinds;
- fails closed on source, digest or machine mismatch;
- treats local-file/self-reported approval as untrusted;
- never promotes Q9/BANK_FINAL.

Content-level generic hosted runner evidence remains deliberately HOLD:

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

Attestation request state:

```yaml
state: AWAITING_EXTERNAL_ATTESTATION
observation_digest: 3b2f250b95a2533b5a2ac518227efd7e26820731e802fb07ce64fc3f19d74a5b
target_linux_verified: false
field_verified: false
bank_final: false
```

This is the intended result. Workflow SUCCESS means the fail-closed policy and target-side mechanism work; it does **not** mean target Linux qualification passed.

## Q3 decision

```yaml
q3_reality_binding_contract: CI_PASS
q3_target_probe_contract: CI_PASS
q3_external_attestation_boundary: CI_PASS
q3_generic_linux_negative_control: PASS
q3_target_linux: HOLD_TARGET_ENVIRONMENT_BINDING_REQUIRED
target_linux_verified: false
field_verified: false
bank_final: false
```

Trusted verifier kinds remain deliberately restricted to:

- `APPROVED_SELF_HOSTED_TARGET_LINUX`
- `BANK_FIELD_TARGET_LINUX`

A contract verifier, GitHub-hosted Ubuntu, local file, model assertion, self-reported `approved=true`, unmatched source/digest/machine or repository-only evidence cannot promote Q3.

## Next atomic step

`Q3_REAL_TARGET_INVOCATION_AND_TRUSTED_ATTESTATION_BINDING`

Use the now-qualified packageable Q3 probe on an actual approved target 信创 Linux environment from exact source `43f9ec4350b87b257e97ce17b929c6a174951667`:

1. run the probe on the real target distro/architecture/shell/package-local runtime;
2. preserve the exact observation JSON and its digest;
3. obtain trusted external target attestation bound to the same source/digest/machine identity;
4. evaluate that attestation through the frozen Q3 boundary;
5. preserve the resulting Evidence without claiming Field or BANK_FINAL beyond what the verifier actually proves.

Do **not** start Q4 qualification while Q3 remains target-environment HOLD. Q4 design/work may be read-only prepared, but qualification sequencing remains blocked by Q3.
