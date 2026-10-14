# RC6 Release Integrated Qualification

Status target for this phase: `ENGINEERING_CANDIDATE_NOT_BANK_FINAL`.

Wave 0-12 engineering qualification is necessary but not sufficient for Bank Field PASS. This phase turns the RC6 source tree into one Git-Bash-first Windows package and proves package identity/integrity plus DSH integration surfaces without pretending that GitHub CI is a bank environment.

## Turnkey entrypoints

The package exposes exactly these primary Git Bash entrypoints:

- `AITEST.sh` — one-click alias to start.
- `START-AITEST.sh` — run fail-closed verification, generate the local DSH MCP overlay, then start DSH Web as the long-lived host.
- `STOP-AITEST.sh` — stop the DSH host process started by the package.
- `STATUS.sh` — show process/build/source/release identity.
- `VERIFY.sh` — package integrity + MCP handshake + DSH capability/config probe. `--package-only` skips host-machine DSH probing for CI/package inspection.

No CMD file is a user entrypoint and no long-lived PowerShell process is used by the bank package.

## DSH-native integration

The package contains `.dsh/skills/pfc-full-chain-test/SKILL.md`. DSH's project skill filesystem discovers `<projectRoot>/.dsh/skills` without a version-specific path. `VERIFY.sh` also generates `runtime-state/rc6.cordis.yml`, using the official `@deepseek-ai/dsh-mcp-client` stdio configuration to expose the RC6 control server as `mcp__pfc_aitest_rc6__*` tools.

The package does not download or pin a DSH/OpenCode version. Admission is capability-based: the installed DSH must support headless help, Web profile config composition, the official MCP client row, and project skills. If those capabilities are absent the package fails closed rather than silently falling back to prompt-only execution.

## Immutable identity

Build output contains:

- `BUILD_ID`
- `SOURCE_COMMIT`
- `RELEASE_STATUS`
- `PACKAGE_MANIFEST.json`
- `CHECKSUMS.sha256`

The manifest explicitly sets `bank_field_pass=false`. Every package file except the checksum file itself is covered by `CHECKSUMS.sha256`; source commit and manifest identity must match on verification. Obvious credential/secret files are excluded from package construction and evidence metadata has independent secret guards in Wave 12.

## Engineering qualification

GitHub CI must pass on Linux and Windows:

1. all RC6 unit qualification,
2. Git Bash launcher syntax,
3. package build from the exact Git SHA,
4. package checksum/manifest verification,
5. package-local MCP initialize + tools/list handshake,
6. Git Bash package-only verification on the Windows runner,
7. ZIP artifact upload.

A successful run produces an engineering candidate ZIP. It does **not** grant Bank Field PASS.

## Bank field qualification still required

On the bank Windows host, `VERIFY.sh` must additionally prove the installed DSH can compose the generated MCP overlay. Then one real Mission must complete on a canonical TargetIdentity without a user `continue` loop:

`Requirement -> Code -> Fusion -> L1-L7 Design -> Coverage/Oracle Closure -> Preparation/Test Data -> L1-L7 Real Execution -> CAT Diagnosis/Recovery -> Empirical Coverage Closure -> Evidence/Defect/Allure/Report`

The same Mission must survive coordinator session rotation, provider backpressure and worker recovery. CodeGraph-required code analysis must contain real admitted CodeGraph call evidence. R1/projection/API/Admin/Allure/report identities/counts must reconcile. Only that real field evidence may change release status to Bank Field PASS.
