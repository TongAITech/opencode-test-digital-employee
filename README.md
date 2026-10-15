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

## RC7 administration platform

The RC7 administration platform is a lightweight local web UI backed directly by the R1 Event Stream projection; it has no shadow business database.

Windows: `packaging\\rc7\\START-RC7-ADMIN.cmd`

macOS/Linux: `packaging/rc7/START-RC7-ADMIN.sh`

Use `PFC_RC7_R1_PATH` for the canonical R1 JSONL path. The UI is Chinese and provides left-side navigation, filters, lists, pagination, details, and controlled Test Case revision append operations.

## Never commit

Bank SUT source/data, credentials, cookies, OTP/MFA material, browser profiles, runtime databases, CodeGraph indexes, portable Python/Chromium/CodeGraph binaries, or generated Construction ZIPs.
