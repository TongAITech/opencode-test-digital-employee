# RC6 Release Integrated Qualification

Status target for this phase: `ENGINEERING_CANDIDATE_NOT_BANK_FINAL`.

Wave 0-12 engineering qualification is necessary but not sufficient for Bank Field PASS. This phase turns the RC6 source tree into one Git-Bash-first Windows package and proves package identity/integrity plus DSH integration surfaces without pretending that GitHub CI is a bank environment.

## Turnkey entrypoints

The package exposes these primary Git Bash entrypoints:

- `AITEST.sh` — one-click alias to start.
- `START-AITEST.sh` — run fail-closed verification, generate the local DSH MCP overlay, then start DSH Web as the long-lived host.
- `STOP-AITEST.sh` — stop the DSH host process started by the package.
- `STATUS.sh` — show process/build/source/release identity.
- `VERIFY.sh` — package integrity + MCP handshake + DSH capability/config probe. `--package-only` skips host-machine DSH probing for CI/package inspection.
- `QUALIFY-AGENT-RUNTIME.sh` — run the blocking real DSH multi-worker vertical slice and validate its proof from R1. This is not a package smoke test.

No CMD file is a user entrypoint and no long-lived PowerShell process is used by the bank package.

## DSH-native integration

The package contains `.dsh/skills/pfc-full-chain-test/SKILL.md`. DSH's project skill filesystem discovers `<projectRoot>/.dsh/skills` without a version-specific path. `VERIFY.sh` also generates `runtime-state/rc6.cordis.yml`, using the official `@deepseek-ai/dsh-mcp-client` stdio configuration to expose the RC6 control server as `mcp__pfc_aitest_rc6__*` tools.

The package does not download or pin a DSH/OpenCode version. Admission is capability-based: the installed DSH must support headless execution, Web profile config composition, the official MCP client row, and project skills. If those capabilities are absent the package fails closed rather than silently falling back to prompt-only execution.

## Immutable identity

Build output contains:

- `BUILD_ID`
- `SOURCE_COMMIT`
- `RELEASE_STATUS`
- `PACKAGE_MANIFEST.json`
- `CHECKSUMS.sha256`

The manifest explicitly sets `bank_field_pass=false`, `autonomous_testing_pass=false`, `full_chain_real=false` and `agent_runtime_bank_final_gate=NOT_PROVEN_UNTIL_REAL_DSH_VERTICAL_SLICE_PASS`. Every package file except the checksum file itself is covered by `CHECKSUMS.sha256`; source commit and manifest identity must match on verification. Obvious credential/secret files are excluded from package construction and evidence metadata has independent secret guards in Wave 12.

## Engineering qualification

GitHub CI must pass on Linux and Windows:

1. all RC6 unit qualification including Agent Runtime fail-closed invariants,
2. Git Bash launcher syntax including `QUALIFY-AGENT-RUNTIME.sh`,
3. package build from the exact Git SHA,
4. package checksum/manifest verification,
5. package-local MCP initialize + tools/list handshake,
6. Git Bash package-only verification on the Windows runner,
7. proof that the package still labels the Agent Runtime gate NOT_PROVEN rather than fabricating a CI PASS,
8. ZIP artifact upload.

A successful run produces an engineering candidate ZIP. It does **not** grant Agent Runtime PASS or Bank Field PASS.

## Blocking Agent Runtime BANK_FINAL qualification

Before the package may use `AGENT_RUNTIME_PASS`, `AUTONOMOUS_TESTING_PASS`, `BANK_FINAL` or `FULL_CHAIN_REAL`, the real DSH host must execute:

`Coordinator -> pfc-requirement-analysis -> pfc-requirement-sufficiency -> Gap -> Repair -> pfc-requirement-analysis -> pfc-requirement-sufficiency -> PASS`

Attempt #1 intentionally omits `missing_boundary_rule`; therefore the first independent sufficiency evaluation must fail. A direct first PASS fails qualification. The repair attempt must run in a new Worker instance and fresh DSH headless session, and the second independent sufficiency evaluation must pass.

The canonical R1 stream must prove the ordered lifecycle `WORKER_ASSIGN_REQUESTED -> WORKER_ADMITTED -> WORKER_STARTED -> WORKER_TOOL_CALLED -> WORKER_OUTPUT_PRODUCED -> WORKER_COMPLETED -> HANDOFF_RETURNED`, followed by `SUFFICIENCY_STARTED -> SUFFICIENCY_GAP_FOUND -> REPAIR_REQUESTED -> WORKER_REASSIGNED -> SUFFICIENCY_REEVALUATED -> SUFFICIENCY_PASSED`. Each Worker handoff carries runtime identity, lease, assignment, scope, I/O refs, real tool-call refs, evidence refs, timestamps and result. Coordinator and Worker identities/sessions must be different. Missing Worker/DSH capability is `ROUTING_INTEGRITY_FAIL`; Coordinator fallback is forbidden.

GitHub unit tests may simulate parser/fail-closed mechanics, but simulation output is never accepted as this real proof. `QUALIFY-AGENT-RUNTIME.sh` is the only packaged qualification entrypoint for this gate and validates the result from R1 itself.

## Bank field qualification still required

After Agent Runtime proof is real, one real bank Mission must complete on a canonical TargetIdentity without a user `continue` loop:

`Requirement -> Code -> Fusion -> L1-L7 Design -> Coverage/Oracle Closure -> Preparation/Test Data -> L1-L7 Real Execution -> CAT Diagnosis/Recovery -> Empirical Coverage Closure -> Evidence/Defect/Allure/Report`

The same Mission must survive coordinator session rotation, provider backpressure and worker recovery. CodeGraph-required code analysis must contain real admitted CodeGraph call evidence. Any TEST PASS must contain an independent execution worker, a real execution attempt, Actual, Oracle, Evidence and execution-integrity PASS; HTTP 200, exit 0, a page opening or SQL success alone never grants PASS. R1/projection/API/Admin/Allure/report identities/counts must reconcile. Only that real field evidence may change release status to Bank Field PASS.
