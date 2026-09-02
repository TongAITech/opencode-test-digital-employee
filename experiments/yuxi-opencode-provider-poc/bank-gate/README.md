# Bank Live Gate — Zero-install Runner

Purpose: execute the decisive `YUXI -> OpenCode -> bank LLM` compatibility gate inside the bank without installing Yuxi, Python, LangChain, pip packages, npm packages, or Playwright.

## Prerequisites already present in the target bank baseline

- Git Bash;
- Node.js 20+;
- OpenCode 1.14.22 or a compatible bank build;
- an OpenCode provider/model that can reach the bank LLM.

## Run

From Git Bash in this directory:

```bash
bash RUN_YUXI_OPENCODE_GATE.sh
```

The runner creates only a local `.probe-workspace`, installs the deny-all `yuxi-model-provider-proxy` agent into that isolated workspace, and targets `http://127.0.0.1:4096` by default.

If no server is reachable there, it starts a temporary `opencode serve` on port `4097` from the isolated probe workspace and kills that process automatically on exit.

The runner resolves the workspace through Windows Node and URI-encodes the `x-opencode-directory` value exactly as the OpenCode 1.14.22 JavaScript SDK does.

If the server has more than one candidate provider/model and no deterministic default, the probe prints a secret-free inventory and returns:

```text
NEEDS_MODEL_SELECTION
```

Re-run the same command with the IDs printed in that inventory:

```bash
bash RUN_YUXI_OPENCODE_GATE.sh \
  --provider-id <OpenCode-providerID> \
  --model-id <OpenCode-modelID>
```

If Basic Auth is enabled on the OpenCode server, set the password only in the environment:

```bash
export OPENCODE_SERVER_PASSWORD='...'
bash RUN_YUXI_OPENCODE_GATE.sh
```

The password is never included in the JSON report.

## What it validates

- server reachability/version when exposed;
- safe provider/model discovery;
- `/experimental/tool/ids` availability;
- deny-all provider-proxy agent availability;
- real plain chat;
- real Yuxi system-message transport;
- real SSE streaming through `prompt_async` + `/event`;
- real bank-model compliance with the strict Yuxi external-tool JSON envelope;
- second-turn continuation after a synthetic Yuxi `ToolMessage` result;
- zero leftover `yuxi-model-gateway*` scratch sessions.

Every model invocation creates a disposable OpenCode session, disables all enumerated OpenCode-owned tools, and deletes the session in cleanup. The probe never executes the fake Yuxi arithmetic tool and never calls shell/file/browser/database/Git/MCP/testing tools through OpenCode.

## Result to carry back

Carry back the complete JSON printed by the runner. The decisive field is:

```json
{"gate": "PASS"}
```

`PASS` authorizes the next architecture-recon step; it does **not** authorize main-branch migration or claim production reliability. Repeated real-model reliability testing is still required before any production promotion.
