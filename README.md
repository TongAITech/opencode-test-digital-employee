# OpenCode Test Digital Employee

Canonical engineering source for the OpenCode-based AI testing digital employee.

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
