# Q1 Source Platform Engineering Baseline — CI PASS

Status: **CI_PASS / ENGINEERING_ONLY / FIELD_NO / BANK_FINAL_NO**

## Qualified lineage

```yaml
branch: work/rc7.2
qualified_source_commit: 77e954558f1fdc933febe2adfeb8a069d3d92c00
workflow_run: 40791919277
qualification_kind: Q1_SOURCE_PLATFORM_BASELINE
field_verified: false
bank_final: false
```

## Windows engineering evidence

- job: `q1-windows-engineering-python-3.8`
- conclusion: SUCCESS
- platform evidence: Windows 10 / AMD64 / Python 3.8.10
- RC7.2 contracts: `210 passed, 0 failed, 0 skipped`
- inherited RC7: `493 tests = 492 passed, 1 skipped`
- artifact id: `12862112628`
- artifact digest: `sha256:afcb75c10da7adafd89f3bfb5b14839ae204340b181dbc5b10be7f0b7e9834c5`
- evidence source commit: exact `77e954558f1fdc933febe2adfeb8a069d3d92c00`
- `field_verified=false`
- `bank_final=false`

## Linux engineering proxy evidence

- job: `q1-linux-engineering-proxy-python-3.8`
- conclusion: SUCCESS
- platform evidence: Linux / x86_64 / Python 3.8.18
- RC7.2 contracts: `210 passed, 0 failed, 0 skipped`
- inherited RC7: `493 tests = 492 passed, 1 skipped`
- artifact id: `12861219520`
- artifact digest: `sha256:baca1bd6e7fb0d13cddb878ad07878e64d6a81adebb2503722d3efb8ef7a51a7`
- evidence source commit: exact `77e954558f1fdc933febe2adfeb8a069d3d92c00`
- `field_verified=false`
- `target_linux_verified=false`
- `bank_final=false`

The GitHub-hosted Linux runner is an engineering proxy only. This checkpoint MUST NOT be presented as target 信创 Linux qualification.

## Decision

Q1 satisfies the frozen `07-PLATFORM-QUALIFICATION-AND-FIELD-ACCEPTANCE-CONTRACT.md` source-platform engineering gate.

This proves that the RC7.2 source/runtime contract suite and inherited RC7 regression execute successfully on Windows and Linux engineering runners. It does not prove clean-unpack packaging, offline portability, in-bank Windows behavior, target Linux behavior, real BSK, real Human Approval, real ReleaseBatch Field execution or BANK_FINAL readiness.

## Next atomic step

`Q2_WINDOWS_CLEAN_UNPACK`

Q2 MUST build from an exact RC7.2 source commit, cleanly extract outside the source checkout, use package-local runtime, verify checksums/identity/payload, and prove that RC7.2 modules/contracts needed by the delivered runtime are actually present. Inherited RC7/RC7.1 packaging mechanics may be reused, but an RC7/RC7.1 package renamed to RC7.2 is forbidden.
