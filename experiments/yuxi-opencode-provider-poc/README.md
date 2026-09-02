# Yuxi ↔ OpenCode Provider PoC

## Status

Reviewed Yuxi baseline: `bd07ab4ac4faa2e5452507580b1c841543bbec61`.

Bank OpenCode compatibility target: `v1.14.22` (`596145a71d2e8baa1ffb99894d8499b76d130f13`). Its published server contract contains the exact endpoints this adapter requires: Session create/delete, synchronous message, `prompt_async`, `/event` SSE, `/provider`, `/agent`, and `/experimental/tool/ids`.

Current engineering evidence on the experiment branch:

- adapter protocol/unit suite: PASS;
- real LangChain `create_agent` tool loop through the adapter: PASS;
- ephemeral OpenCode session per model turn: PASS in deterministic protocol tests;
- OpenCode-owned tool fail-closed disablement: PASS in deterministic protocol tests;
- Yuxi `bd07ab4` overlay application, repeated application/idempotence, `git diff --check`, and patched Python compilation: PASS;
- real bank OpenCode + real bank model behavior: **PENDING LIVE GATE**.

No canonical main-branch runtime or frozen G1-G4 contract is changed by this experiment.

## Goal

Validate the narrow architecture in which **Yuxi remains the product/agent owner** while **OpenCode is the only bank-approved LLM access gateway**.

This experiment does **not** replace the canonical OpenCode testing-digital-employee runtime, does not modify frozen G1-G4 contracts, and is not included in `SOURCE_BASELINE_MANIFEST.json`.

## Critical invariants

1. Yuxi/LangGraph owns the conversation and Yuxi tool loop for this PoC.
2. Every Yuxi model call creates a fresh OpenCode session and deletes it in `finally`.
3. OpenCode session IDs are transport diagnostics only; they are never Mission/Plan/Task/Attempt/Thread truth.
4. Every OpenCode-owned tool discovered through `/experimental/tool/ids` is explicitly disabled for the prompt.
5. The dedicated OpenCode agent `yuxi-model-provider-proxy` denies every permission as a second guardrail.
6. If tool enumeration is unavailable, the adapter fails closed instead of silently allowing OpenCode tools.
7. Yuxi external tools are not executed by OpenCode.

## Why an adapter is required

OpenCode server is not an OpenAI-compatible `/v1/chat/completions` endpoint. Its public API is session-oriented:

- `POST /session`
- `POST /session/:id/message`
- `POST /session/:id/prompt_async`
- `GET /event`
- `DELETE /session/:id`

The prompt `tools` field controls OpenCode-owned tools; it is not a generic LangChain provider endpoint that accepts arbitrary `bind_tools()` schemas.

Therefore this PoC implements a real `BaseChatModel` adapter rather than configuring Yuxi's existing `ChatOpenAI(base_url=...)` path.

## Runtime flow

```text
Yuxi / LangGraph
    |
    | BaseChatModel.ainvoke()/astream()
    v
OpenCodeChatModel
    |
    | serialize full Yuxi conversation
    v
OpenCodeClient
    |
    | POST /session                 (ephemeral)
    | GET  /experimental/tool/ids  (disable all)
    | POST /session/:id/message     (or prompt_async + SSE)
    | DELETE /session/:id          (always)
    v
Bank OpenCode 1.14.22
    v
Bank-approved LLM provider
```

The full LangChain message history is serialized into one prompt because reusing an OpenCode session would duplicate state ownership, while the public Session API is an agent/session API rather than a raw stateless inference endpoint.

## Native Yuxi tools: current PoC strategy

OpenCode's public Session API does not provide arbitrary Yuxi/LangChain tool-schema pass-through. The PoC therefore uses a **strict fail-closed JSON envelope**:

```json
{"kind":"final","content":"assistant text"}
```

or

```json
{
  "kind":"tool_calls",
  "tool_calls":[
    {"id":"call-1","name":"tool_name","args":{"key":"value"}}
  ]
}
```

`OpenCodeChatModel` validates the envelope and converts it to native LangChain `AIMessage.tool_calls`; LangGraph/Yuxi still executes the tool. Unknown tools, malformed JSON, missing/duplicate IDs, or non-object args fail closed.

This is **tool-calling emulation**, not proof of native provider-level function calling. Its reliability against the real bank model is the decisive live PoC gate.

## Yuxi integration overlay

`tools/apply_to_yuxi.py` applies the PoC to the reviewed Yuxi baseline. It deliberately uses exact integration anchors and fails closed if upstream Yuxi moves those seams.

It adds the adapter package under `backend/package/yuxi/models/opencode/`, adds `provider_type == "opencode"` to `load_chat_model()`, registers the provider type in backend validation, avoids duplicating the bank model credential into Yuxi, and adds `OpenCode Session Gateway` to model-provider UI choices.

Example provider data:

```json
{
  "provider_id": "bank-opencode",
  "display_name": "Bank OpenCode",
  "provider_type": "opencode",
  "base_url": "http://127.0.0.1:4096",
  "capabilities": ["chat"],
  "enabled_models": [
    {
      "id": "<OpenCode modelID>",
      "display_name": "Bank Model",
      "type": "chat",
      "source": "manual"
    }
  ],
  "headers_json": {},
  "extra_json": {
    "opencode_provider_id": "<OpenCode providerID>",
    "opencode_agent": "yuxi-model-provider-proxy",
    "opencode_directory": "C:/bank/ai-test-workspace"
  }
}
```

Do not confuse Yuxi's provider registry ID (`bank-opencode` above) with OpenCode's underlying `providerID`.

## Automated tests

```bash
cd experiments/yuxi-opencode-provider-poc
python -m pip install -e '.[test]'
pytest
```

The suite validates:

- ephemeral session cleanup on success and failure;
- model/provider payload mapping;
- disabling all OpenCode tools;
- fail-closed behavior when tool enumeration is unavailable;
- system + user/assistant/tool role serialization;
- Yuxi tool schema injection;
- strict tool-call conversion back to LangChain;
- malformed/unknown tool calls rejected;
- SSE filtering by ephemeral session and completion on `session.idle`;
- a complete LangChain `create_agent` model → Yuxi tool → ToolMessage → final-answer loop;
- safe provider/model discovery helpers for the live bank gate.

## Live bank gate

The remaining gate is executable, not a manual checklist. From an environment containing this PoC and able to reach the bank OpenCode server:

```bash
python tools/live_probe.py
```

The probe first performs only safe discovery. If more than one connected provider/model is available it returns `NEEDS_MODEL_SELECTION` and a secret-free inventory. Re-run with the selected IDs:

```bash
python tools/live_probe.py \
  --provider-id <OpenCode-providerID> \
  --model-id <OpenCode-modelID> \
  --directory <bank-test-workspace>
```

If OpenCode server Basic Auth is enabled, place the password in `OPENCODE_SERVER_PASSWORD`; the probe never prints it.

The live report checks:

1. server health/version;
2. safe provider/model discovery;
3. `/experimental/tool/ids` availability;
4. `yuxi-model-provider-proxy` availability;
5. real plain chat;
6. real system-prompt behavior;
7. real SSE streaming;
8. real bank-model selection of a Yuxi external tool using the strict envelope;
9. continuation after a Yuxi `ToolMessage` result;
10. no leftover probe session.

A live `PASS` is the threshold for promoting this architecture from engineering PoC to formal Yuxi-primary-platform architecture recon. If tool selection/continuation is not reliable enough across repeated bank-model calls, do **not** label OpenCode a native LLM provider. The fallback is either a raw inference gateway inside/alongside OpenCode or Yuxi as product/control-plane with OpenCode retaining agent/tool-runtime ownership.
