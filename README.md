# OpenCode Test Digital Employee

Canonical engineering source for the OpenCode-based AI testing digital employee.

The V1.12.0 Recovery Turnkey Validation package starts with `bash AITEST.sh`.
See [VALIDATION_README.md](VALIDATION_README.md) for Windows field validation.
Version1.12.0 advances the actual packaging baseline1.11.1; V1.9.4 remains the historical capability reference.

## Source of truth

- Git commit SHA = Engineering Source Truth.
- `runtime-lock.json` = pinned offline-runtime payload contract.
- large runtime binaries/caches are derived payloads and are not stored in Git.
- R1 Event Stream remains the product's sole durable runtime truth.

## Repository layout

- `workspace-template/` — product source, OpenCode agents/tools/commands, tests and configuration.
- `packaging/` — installer/launcher source used to assemble the offline package.
- `docs/governance/` — current formal design/governance contracts.
- `runtime-lock.json` — pinned offline payload versions and integrity requirements.

## Never commit

Bank SUT source/data, credentials, cookies, OTP/MFA material, browser profiles, runtime databases, CodeGraph indexes, portable Python/Chromium/CodeGraph binaries, or generated Construction ZIPs.
