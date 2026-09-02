# PFC OpenCode 1.18.21 Web Explicit Project Binding Contract

## Source-derived behavior

`opencode web` starts the Web server without an ambient project instance. The package therefore does not treat startup cwd as Web project binding. Before the browser opens, it calls the v1.18.21 project and session routes with `directory=<stable-workspace>`, then opens the same explicit Web route `/<base64url(directory)>/session/<session-id>`.

## Required proof

The server must return the stable workspace for `/project/current`, a session whose actual `directory` equals the stable workspace, and an `aitest-director` agent from that directory. If any proof fails, Web is not reported READY, the browser is not opened, and the interactive primary surface remains `OPENCODE_TUI`; Web is recorded as `SECONDARY_KNOWN_LIMIT`.

## Durable bridge

The `.opencode/tools/pfc.ts` bridge resolves `<workspace-root>/pfc-field-validation/pfc_harness.py` only after checking the installation marker, AGENTS, OpenCode config, durable DB, and Test-Director. It does not use a hard-coded `D:\pfc-field-validation\` path or a package temporary directory. `pfc_truth` fails closed when this resolution or the durable SQLite truth contract fails.
