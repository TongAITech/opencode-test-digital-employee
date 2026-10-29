# RC7.2 Q2 Windows Clean-Unpack — CI PASS Checkpoint

Status: **CI_PASS_ENGINEERING_ONLY / FIELD_CONFIRMATION_PENDING / BANK_FINAL_NO**

Qualified implementation/source commit: `1b4f8ebb4612660ff07d93cdf6bf5b22c30e1d22`

## Same-HEAD qualification evidence

- Construction workflow run: `40801951720`
  - RC7.2 contracts Python 3.8: `225 passed`
  - RC7.2 contracts Python 3.11: `225 passed`
  - inherited RC7 regression: `492 passed, 1 skipped`
- Q1 source-platform workflow run: `40801951774`
  - Windows engineering: SUCCESS
  - Linux engineering proxy: SUCCESS
  - Q1 summary: SUCCESS
- Q2 Windows clean-unpack workflow run: `40801952853`
  - Q2-A clean package: SUCCESS
  - Q2-B clean runtime / R1 / Session / Git Bash entrypoint probe: SUCCESS

## Q2-A evidence

Artifact:

- id: `12866442208`
- name: `rc72-q2a-windows-clean-unpack-1b4f8ebb4612660ff07d93cdf6bf5b22c30e1d22`
- digest: `sha256:ec7aff88831c5fdc7efce7919a44612f0d024010c2dbf6d9b5bd053c992e32b0`

Proved on Windows engineering infrastructure:

1. exact-lineage RC7.2 package build;
2. distinct RC7.2 release identity, not an RC7 rename;
3. ZIP SHA verification;
4. build root deletion before clean extraction;
5. package-local Python execution;
6. strict RC7.2 manifest/checksum verification;
7. all current `rc7_runtime/rc72_*.py` modules load from the clean package;
8. Git/source checkout is not required at runtime for this proof.

## Q2-B evidence

Artifact:

- id: `12866217593`
- name: `rc72-q2b-windows-clean-runtime-1b4f8ebb4612660ff07d93cdf6bf5b22c30e1d22`
- digest: `sha256:1f4539e6e046d3944ceecaed1ddb63a6dbfbbadc3814c48b6062c0a7b36eb232`

Content-level evidence was inspected, not inferred from the green job only.

`rc72-q2b-clean-runtime.json` proves:

- `status=PASS`;
- `qualification=RC72_WINDOWS_CLEAN_PACKAGE`;
- `release_family=RC7.2`;
- `business_root=RELEASE_BATCH`;
- `source_commit=1b4f8ebb4612660ff07d93cdf6bf5b22c30e1d22`;
- package-local Python;
- Mission Graph v2 bootstrap;
- runtime-owned Reality Recon followed by Requirement Analysis producer routing;
- durable R1 truth;
- Session A -> B -> C handoff;
- generation 1 then generation 2;
- final active session `SESSION-C`;
- same task remains `RUNNING` across handoff;
- `chat_history_transferred=false`;
- `field_verified=false`;
- `target_linux_verified=false`;
- `bank_final=false`.

The uploaded canonical R1 stream contains the persisted `rc7_session_handoff` and `rc7_task` ownership transitions through `SESSION-A -> SESSION-B -> SESSION-C`.

`rc72-q2b-gitbash-launcher.txt` proves the real RC7.2 Git Bash entrypoint performed strict RC7.2 package verification and emitted the bounded Q2 launch plan:

```text
RC72_LAUNCH_PLAN profile=rc7.2-bank delegate=packaging/rc7/AITEST.sh field_verified=false bank_final=false offline_payload_verified=false
```

The `offline_payload_verified=false` value is deliberate. Q2 must not fake the Q4 offline DSH/plugin/tool payload gate. Default RC7.2 startup still delegates to the mature RC7 launcher; Q2's engineering probe only proves the entrypoint, isolated profile choice and delegate path.

## Q2 decision

`Q2_WINDOWS_CLEAN_UNPACK = CI_PASS_ENGINEERING_ONLY`

This does **not** prove:

- execution on an in-bank Windows PC;
- target 信创 Linux;
- complete offline DSH/plugin/tool payload;
- real Bank DSH startup;
- real BSK/CDP Field execution;
- real Human Approval;
- real ReleaseBatch N1-N10 mission;
- BANK_FINAL readiness.

Those remain later qualification gates.

## Next gate

`Q3_TARGET_LINUX_REALITY_CONTRACT`

Q3 must fail closed if no approved target 信创 Linux/self-hosted target environment is bound. Generic GitHub Ubuntu is an engineering proxy only and must never be promoted to target-Linux PASS.
