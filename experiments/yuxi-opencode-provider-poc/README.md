# Yuxi ↔ OpenCode Provider PoC

## Goal

Validate the narrow architecture in which **Yuxi remains the product/agent owner** while **OpenCode is the only bank-approved LLM access gateway**.

This experiment does **not** replace the canonical OpenCode testing-digital-employee runtime, does not modify frozen G1–G4 contracts, and is not included in `SOURCE_BASELINE_MANIFEST.json`.

## Critical invariants

1. Yuxi/LangGraph owns the conversation and tool loop for this PoC.
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

The prompt `tools` field is an enable/disable map for OpenCode-owned tool IDs. It is **not** arbitrary LangChain function schema pass-through.

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
Bank OpenCode
    v
Bank-approved LLM provider
```

The full LangChain message history is serialized into one prompt because reusing an OpenCode session would duplicate state ownership, while the public Session API does not expose a raw stateless inference endpoint that accepts arbitrary historical assistant/tool messages directly.

## Native Yuxi tools: current PoC strategy

OpenCode's public Session API cannot receive Yuxi's arbitrary `bind_tools()` schemas as native provider tools. The PoC therefore uses a **strict fail-closed JSON envelope**:

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

## Yuxi integration seam

Yuxi already resolves chat models through `load_chat_model()` and its model-provider registry stores `provider_type` as a string. A production patch can add a branch similar to:

```python
if info.provider_type == "opencode":
    return OpenCodeChatModel(
        base_url=info.base_url,
        opencode_provider_id=info.extra["opencode_provider_id"],
        model_id=info.model_id,
        agent=info.extra.get("opencode_agent", "yuxi-model-provider-proxy"),
        directory=info.extra.get("opencode_directory"),
        headers=info.headers,
    )
```

Do not confuse Yuxi's provider registry ID with OpenCode's underlying `providerID`. The latter belongs in `extra_json`, for example:

```json
{
  "opencode_provider_id": "bank-deepseek",
  "opencode_agent": "yuxi-model-provider-proxy",
  "opencode_directory": "C:/bank/pfc-ai-test"
}
```

## Tests

```bash
cd experiments/yuxi-opencode-provider-poc
python -m pip install -e '.[test]'
pytest
```

The unit suite validates:

- ephemeral session cleanup on success and failure;
- model/provider payload mapping;
- disabling all OpenCode tools;
- fail-closed behavior when tool enumeration is unavailable;
- system + user/assistant/tool role serialization;
- Yuxi tool schema injection;
- strict tool-call conversion back to LangChain;
- malformed/unknown tool calls rejected;
- SSE filtering by ephemeral session and completion on `session.idle`.

## Live bank gate

Unit protocol tests are not enough. A real line-of-business validation must prove:

1. the bank OpenCode version exposes the required Session/Event/tool-ID endpoints;
2. configured `providerID/modelID` can invoke the bank model;
3. system prompt behavior is preserved;
4. token streaming works without cross-session leakage;
5. the bank model follows the strict Yuxi tool envelope reliably across repeated calls;
6. no OpenCode tool or permission prompt is triggered in provider-proxy mode;
7. scratch sessions are deleted and never become product truth.

If item 5 is not reliable enough for an autonomous testing worker, the architecture must **not** pretend OpenCode is a native raw LLM provider. The next candidate is either a raw inference endpoint inside/alongside OpenCode, or Yuxi as product/control-plane with OpenCode retaining agent/tool-runtime ownership.
