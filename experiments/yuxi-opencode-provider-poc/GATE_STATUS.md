# YUXI_OPENCODE_PROVIDER_POC — Gate Status

## Checkpoint identity

- Experiment branch: `experiment/yuxi-opencode-provider-poc`
- Experiment head before this checkpoint: `10eb8c7fe607d70af61b7400d5af16a057c06090`
- Canonical repository main branch: **UNCHANGED by this experiment**
- Reviewed Yuxi baseline: `bd07ab4ac4faa2e5452507580b1c841543bbec61`
- Bank OpenCode compatibility baseline: `v1.14.22` / `596145a71d2e8baa1ffb99894d8499b76d130f13`

## Formal state

```text
YUXI_OPENCODE_PROVIDER_POC = ENGINEERING_PASS
OPENCODE_1_14_22_REQUIRED_SESSION_API_COMPAT = PASS
YUXI_BASECHATMODEL_ADAPTER = ENGINEERING_PASS
EPHEMERAL_OPENCODE_SESSION_ISOLATION = PASS
OPENCODE_TOOL_RUNTIME_DISABLEMENT = PASS / PROTOCOL_TESTED
OPENCODE_NATIVE_YUXI_TOOL_SCHEMA_PASSTHROUGH = NOT_SUPPORTED
YUXI_TOOL_CALL_JSON_EMULATION = ENGINEERING_PASS / LIVE_RELIABILITY_UNPROVEN
LANGCHAIN_CREATE_AGENT_TOOL_LOOP = PASS
YUXI_BD07_PROVIDER_OVERLAY = ENGINEERING_PASS
YUXI_OVERLAY_IDEMPOTENCE = PASS
YUXI_OVERLAY_DIFF_CHECK = PASS
YUXI_OVERLAY_PYTHON_COMPILE = PASS
BANK_LIVE_PROVIDER_GATE = HUMAN_ACTION_REQUIRED
YUXI_AS_PRIMARY_TEST_DIGITAL_EMPLOYEE_PLATFORM = CANDIDATE / NOT_YET_BASELINED
CANONICAL_ARCHITECTURE_REPLACEMENT = NOT_AUTHORIZED
MAIN_BRANCH_PROMOTION = NOT_AUTHORIZED
```

## Evidence

### Adapter construction

- `76ba81715317a0e7220d1b1de16d0e7d4245cd1d` — initial OpenCode client/BaseChatModel/provider-proxy agent/protocol tests.
- `bc655647f42f1c8c40de0a6d899aab36dcf58731` — real LangChain `create_agent` model → Yuxi tool → ToolMessage → final answer loop.
- `b6ad1bb1ace85e302600ea74f4d5971ffa04e140` — pinned Yuxi `bd07ab4` integration overlay and upstream compatibility job.
- `10eb8c7fe607d70af61b7400d5af16a057c06090` — one-command live bank gate and safe provider/model discovery tests.

### Latest automated gate

GitHub Actions run `33660969147`:

- workflow conclusion: `success`;
- unit/protocol job: `17 passed`;
- Yuxi upstream compatibility job: `success`;
- overlay applied twice to exact Yuxi baseline;
- `git diff --check`: PASS;
- patched adapter/Yuxi Python compilation: PASS.

## Architecture truth established by the PoC

1. OpenCode `v1.14.22` exposes the required Session/Message/Event/Provider/Agent/tool-ID endpoints.
2. OpenCode Session API is an agent/session API, not a raw OpenAI-compatible inference endpoint.
3. Its request `tools` setting is an OpenCode-owned tool enable/disable map, not arbitrary LangChain function-schema pass-through.
4. Therefore Yuxi cannot safely use `ChatOpenAI(base_url=http://127.0.0.1:4096)` directly.
5. A dedicated `OpenCodeChatModel(BaseChatModel)` adapter is required.
6. To keep Yuxi/LangGraph as the owner of conversation/tool-loop state, every model call uses a fresh OpenCode scratch session and deletes it after the turn.
7. OpenCode-owned tools are enumerated and disabled; the provider-proxy agent also denies every permission.
8. Yuxi tools remain Yuxi/LangGraph tools. The current PoC carries their schemas through a strict JSON protocol and converts the response back into native LangChain `AIMessage.tool_calls`.

## Only remaining decisive gate

The remaining uncertainty cannot be truthfully resolved in public CI: the exact bank-deployed OpenCode build, configured bank provider/model mapping, and actual bank LLM must execute the adapter protocol.

From the PoC environment connected to the bank OpenCode server:

```bash
cd experiments/yuxi-opencode-provider-poc
python tools/live_probe.py
```

If auto-selection is ambiguous, use the secret-free inventory returned by the probe and re-run:

```bash
python tools/live_probe.py \
  --provider-id <OpenCode-providerID> \
  --model-id <OpenCode-modelID> \
  --directory <bank-test-workspace>
```

Required live PASS checks:

- server health/version;
- provider/model mapping;
- OpenCode tool enumeration;
- `yuxi-model-provider-proxy` presence;
- plain chat;
- system prompt;
- SSE streaming;
- strict Yuxi tool selection;
- ToolMessage continuation to final answer;
- zero leftover probe sessions.

## Promotion rule

`BANK_LIVE_PROVIDER_GATE = PASS` is necessary before starting a formal migration from the current canonical product architecture to a Yuxi-primary product architecture.

A single live PASS proves compatibility, not production reliability. Before production promotion, repeat the tool-selection/continuation scenario enough times to measure malformed-envelope rate, wrong-tool rate, argument-error rate, and completion reliability on the exact bank model.

If live tool protocol reliability is inadequate, do **not** weaken the gate or silently let OpenCode own Yuxi tools. Replan to one of:

1. a raw/stateless inference gateway inside or alongside OpenCode; or
2. Yuxi as product/control plane while OpenCode remains the agent/tool runtime.
