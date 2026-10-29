# Q2-A Windows Package Identity / Clean-Unpack — CI PASS

Status: **CI_PASS_ENGINEERING_ONLY / Q2_OVERALL_IN_PROGRESS / FIELD_NO / BANK_FINAL_NO**

## Qualified lineage

```yaml
branch: work/rc7.2
qualified_source_commit: 120b16143fd5487706156b75c1c86168f642c024
q2a_workflow_run: 40794043110
same_head_q1_workflow_run: 40794043003
field_verified: false
bank_final: false
```

## Q2-A evidence

Windows clean-unpack job `q2a-windows-clean-unpack-python-3.8` completed SUCCESS.

Verified sequence:

```text
exact RC7.2 source commit
 -> RC7.2 package identity contracts PASS
 -> build RC7.2 transport ZIP
 -> SHA-256 sidecar verification
 -> delete built package root
 -> clean extraction into fresh directory
 -> package-local Python only
 -> RC7.2 package/manifest/checksum verification
 -> import every packaged rc7_runtime/rc72_*.py module
 -> upload evidence
```

Artifact:

- artifact id: `12861954949`
- artifact name: `rc72-q2a-windows-clean-unpack-120b16143fd5487706156b75c1c86168f642c024`
- artifact digest: `sha256:649caabe2aea50eaca6d11070a49ac48055d9d005efe98b270c2fa101912c56f`
- Q2-A contract tests: `8 passed`
- package verify status: `PASS`
- package file count: `4798`
- required RC7.2 runtime modules: `26`
- package-local imports: `26 PASS`
- package-local Python bundled: `true`
- exact source commit bound: `120b16143fd5487706156b75c1c86168f642c024`
- `field_verified=false`
- `bank_final=false`

RC7.2 package identity is distinct from inherited RC7:

- package: `PFC-AITest-DSH-Turnkey-RC7.2-BANK-WIN10`
- manifest schema: `pfc.aitest.rc7.2.package.v1`
- build id prefix: `RC7.2-`
- release family: `RC7.2`
- business root: `RELEASE_BATCH`
- runtime backbone: `N1_N10_MISSION_GRAPH`

## Same-head regression evidence

Same source commit `120b1614...` also passed Q1 source-platform qualification:

- Windows RC7.2 contracts: `218 passed`
- Windows inherited RC7: `493 tests = 492 passed, 1 skipped`
- Linux engineering proxy job: SUCCESS
- Windows engineering job: SUCCESS
- Q1 summary: SUCCESS

This proves the Q2-A packaging additions did not break the frozen source/runtime baseline.

## Decision

Q2-A is closed at engineering CI level.

Q2 overall is **not** complete. Q2-B remains mandatory:

1. clean package-local RC7.2 R1/Mission/session-continuity qualification;
2. package-local Python enforcement;
3. Git Bash entrypoint qualification;
4. RC7.2 identity retained throughout launcher/qualification evidence;
5. no Field or BANK_FINAL claim.

## Next atomic step

`Q2B_WINDOWS_CLEAN_RUNTIME_AND_GIT_BASH_TESTS_FIRST`

Do not begin Q3 target Linux until Q2-B is green and Q2 overall is checkpointed.
