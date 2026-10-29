# RC7.2 Q3 Target Linux Reality Binding — Package-Bound Mechanism PASS / Real Target HOLD Checkpoint

Status: **REALITY_BINDING_CONTRACT_CI_PASS / TARGET_PROBE_CI_PASS / FIELD_HANDOFF_CI_PASS / PACKAGE_BOUND_EXTERNAL_ATTESTATION_CI_PASS / TARGET_LINUX_HOLD / FIELD_VALIDATION_PENDING / BANK_FINAL_NO**

Qualified functional head: `495a12f35430443d7f9cfb59ad6691894a8c8125`

## Same-HEAD evidence set

All qualification evidence below is from the same functional source SHA `495a12f35430443d7f9cfb59ad6691894a8c8125`.

### Construction

Workflow run: `40815666704`

- RC7.2 contracts Python 3.8: `253 passed`
- RC7.2 contracts Python 3.11: `253 passed`
- inherited RC7 regression: `492 passed, 1 skipped`
- runtime/release compile: PASS

### Q1 source-platform baseline

Workflow run: `40815666700`

- Windows engineering: SUCCESS
- Linux engineering proxy: SUCCESS
- Q1 summary: SUCCESS
- Windows artifact id: `12872207615`
- Windows artifact digest: `sha256:22d39d64264d70032d03e2f100be49306f68ee16ee90ee1f98b3bcea91391183`
- Linux proxy artifact id: `12872466187`
- Linux proxy artifact digest: `sha256:88a4dabafec41ad5790cd53c0ad9368c3c44ad2df5446a9361865600def6d65d`

Q1 remains engineering-only. Generic Linux is not target 信创 Linux Field evidence.

### Q2 Windows clean-unpack

Workflow run: `40815666705`

Q2-A:

- exact-lineage package build: SUCCESS
- delete build root + clean re-extract: SUCCESS
- strict identity/checksum + package-local runtime: SUCCESS
- artifact id: `12871584284`
- artifact digest: `sha256:e61738fa3ba5b7de283922cacfca8652281447d75656b780fee155757a3e6795`

The actual Q2-A transport was inspected after qualification. The embedded `SOURCE_COMMIT` is `495a12f35430443d7f9cfb59ad6691894a8c8125`; the package contains the field handoff, target probe, AITEST entrypoint, attestation module and reality module used by Q3 package-bound verification.

Q2-B:

- exact Q2-A transport download + second clean extract: SUCCESS
- clean R1 / Session A->B->C continuity: SUCCESS
- active session: `SESSION-C`
- chat history transferred: `false`
- business root: `RELEASE_BATCH`
- runtime backbone: `N1_N10_MISSION_GRAPH`
- real Git Bash engineering entrypoint probe: SUCCESS
- profile: `rc7.2-bank`
- `offline_payload_verified=false`
- `field_verified=false`
- `bank_final=false`
- artifact id: `12872715575`
- artifact digest: `sha256:e874280b8eddd0c10d1e69fc1957ab114f2462d76206c81d169bddf599592706`

Q2 remains `CI_PASS_ENGINEERING_ONLY`. No Q4 payload claim was used.

### Q3 target Linux package-bound reality mechanism

Workflow run: `40815666715`, SUCCESS.

Artifact:

- id: `12872261627`
- name: `rc72-q3-generic-linux-negative-control-495a12f35430443d7f9cfb59ad6691894a8c8125`
- digest: `sha256:099237561300c9e049a2d4dbf8972e6fdccd2219a1294fbd103199cec38548f1`
- contract tests: `28 passed`

The target-side engineering mechanism now includes:

- `packaging/rc7.2/Q3-TARGET-LINUX-PROBE.sh`
- `packaging/rc7.2/Q3-FIELD-HANDOFF.sh`
- `rc7_release/rc72_target_linux_attestation.py`
- `rc7_release/rc72_target_linux_reality.py`

The probe is observation-only. The field handoff is package-lineage bound and creates four evidence objects without approving the target:

1. target observation;
2. transported-package evidence with critical-file SHA-256 digests;
3. external attestation request;
4. handoff manifest.

The external attestation boundary now requires one coherent binding across:

```text
exact source lineage
+ exact observation digest
+ exact transported-package evidence digest
+ exact machine identity
+ trusted external verifier
```

A missing package-evidence object produces HOLD. Package evidence that violates source/runner/no-install/no-self-approval/critical-file constraints produces FAIL. An attestation whose observation digest or package-evidence digest does not match produces FAIL.

The previous weaker positive path in `rc72_target_linux_reality.py` was closed: all positive target decisions now delegate to the same package-bound attestation evaluator.

Generic hosted runner evidence remains deliberately HOLD:

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

The engineering field-handoff request remains deliberately:

```yaml
state: AWAITING_EXTERNAL_ATTESTATION
package_evidence_bound: true
package_evidence_digest: fca93c2bf518ee524d2edd0a98f4d58bfcc8746358c3e169e16c7a11ff718154
target_linux_verified: false
field_verified: false
bank_final: false
```

This is the intended result. Workflow SUCCESS means the fail-closed policy, package handoff and trust boundary work; it does **not** mean target Linux qualification passed.

## Q3 decision

```yaml
q3_reality_binding_contract: CI_PASS
q3_target_probe_contract: CI_PASS
q3_field_handoff_contract: CI_PASS
q3_package_bound_external_attestation: CI_PASS
q3_generic_linux_negative_control: PASS
q3_target_linux: HOLD_TARGET_ENVIRONMENT_BINDING_REQUIRED
target_linux_verified: false
field_verified: false
bank_final: false
```

Trusted verifier kinds remain deliberately restricted to:

- `APPROVED_SELF_HOSTED_TARGET_LINUX`
- `BANK_FIELD_TARGET_LINUX`

A contract verifier, GitHub-hosted Ubuntu, local file, model assertion, self-reported `approved=true`, repository-only evidence, missing package evidence, unmatched source, observation digest, package-evidence digest or machine identity cannot promote Q3.

## Next atomic step

`Q3_REAL_TARGET_INVOCATION_AND_TRUSTED_ATTESTATION_BINDING`

Use the qualified transport from exact source `495a12f35430443d7f9cfb59ad6691894a8c8125` on an actual approved target 信创 Linux environment:

1. run `packaging/rc7.2/Q3-FIELD-HANDOFF.sh` on the real target distro/architecture/shell/runtime;
2. preserve the exact observation, package-evidence, request and manifest JSON files;
3. obtain trusted external target attestation bound to the same source, observation digest, package-evidence digest and machine identity;
4. evaluate that attestation through the frozen Q3 boundary;
5. preserve the resulting Evidence without claiming Field or BANK_FINAL beyond what the trusted verifier actually proves.

Do **not** start Q4 qualification while Q3 remains target-environment HOLD. Q4 design/work may be read-only prepared, but qualification sequencing remains blocked by Q3.
