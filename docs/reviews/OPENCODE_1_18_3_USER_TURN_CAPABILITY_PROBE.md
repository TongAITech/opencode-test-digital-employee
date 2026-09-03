# OpenCode 1.18.3 User-Turn Capability Probe

Status: `PROBE_COMPLETE`

Scope: F1A `HUMAN_TAKEOVER_YIELD_AND_EXPLICIT_USER_TURN_RESUME` only. This document is engineering evidence for Repair Wave 2 Closure; it does not amend ArchitectureBaseline v7.

## Exact version probed

OpenCode upstream tag: `v1.18.3`.

Authoritative upstream source locations inspected:

- `packages/plugin/src/index.ts` at tag `v1.18.3`
- `packages/opencode/src/session/prompt.ts` at tag `v1.18.3`

Upstream URLs:

- https://github.com/anomalyco/opencode/blob/v1.18.3/packages/plugin/src/index.ts
- https://github.com/anomalyco/opencode/blob/v1.18.3/packages/opencode/src/session/prompt.ts

## Probe result

### 1. `chat.message` is a real v1.18.3 hook, not only an SDK type declaration

`packages/plugin/src/index.ts` declares the hook as:

- input: session / agent / model / message identifiers
- mutable output: `UserMessage` plus `Part[]`
- return contract: `Promise<void>`

`packages/opencode/src/session/prompt.ts` contains a real `plugin.trigger("chat.message", ...)` call in the user-message prompt path.

Therefore:

`OPENCODE_1_18_3_PRE_LLM_USER_MESSAGE_HOOK = AVAILABLE`

### 2. Stable pre-LLM short-circuit interception is not part of the proved hook contract

The exact v1.18.3 hook contract exposes mutation/observation of the user message and parts. It does not expose a supported `handled`, `cancel`, `stop`, direct-response, or equivalent result that proves a plugin can consume a message and prevent the normal LLM path.

The existence of `chat.message` is therefore insufficient authority for claiming deterministic no-LLM interception.

Therefore:

`OPENCODE_1_18_3_STABLE_PRE_LLM_SHORT_CIRCUIT_INTERCEPTION = NOT_PROVEN_BY_SUPPORTED_HOOK_CONTRACT`

This conclusion is intentionally fail-closed. It does not claim that unsupported/internal techniques are impossible; it states that Repair Wave 2 cannot make them a product guarantee from the exact v1.18.3 supported hook contract.

## Product seam selected by F1A

The supported Repair Wave 2 product path is:

1. Executor reaches a 4A / CAPTCHA / manual browser condition.
2. G4 durably persists the HumanGate, root Attempt, StepCursor, BrowserContext and BrowserLease transition.
3. `request_human_takeover` returns `WAITING_HUMAN`, `ai_turn=YIELD`, `blocking_tool_call=false`; the current Assistant Turn may end.
4. The user performs the operation in the controlled browser while the browser observer remains enabled and AI browser actuation remains disabled.
5. The user sends a new OpenCode User Turn such as `完成`.
6. Because supported short-circuit interception is not proven, the Primary Director may receive that User Turn and invoke the deterministic G4 product action `human_gate_user_turn_resume`.
7. `HumanGateUserTurnResumeResolver` semantics are implemented in G4 Runtime. It queries compatible PENDING HumanGate truth from the current Mission R1 Event Stream, not from conversation memory.
8. The user text produces only `REQUEST_TO_VERIFY_COMPLETION`; it is never completion authority.
9. Browser Runtime fresh verification over the same BrowserContext, HUMAN lease, auth state, page identity and business/resume condition is the completion authority.
10. Only successful fresh verification can resolve canonical R2.6 HumanGate truth, transfer HUMAN→AI and resume the same root Attempt / StepCursor.

Formal decision for this repair:

- `USER_TEXT_COMPLETION_AUTHORITY = FORBIDDEN`
- `CONVERSATION_HISTORY_GATE_SELECTION = FORBIDDEN`
- `R1_PENDING_HUMAN_GATE_SELECTION = REQUIRED`
- `BROWSER_RUNTIME_FRESH_VERIFICATION = COMPLETION_AUTHORITY`
- `PRIMARY_DIRECTOR_TO_DETERMINISTIC_RUNTIME_RESOLVER = AUTHORIZED_FALLBACK_FOR_OPENCODE_1_18_3`

## Architecture and scope audit

- ArchitectureBaseline remains `v7 / FROZEN / UNCHANGED`.
- G1/G2/G2.1 are not redesigned.
- G5 remains HOLD.
- G6 remains HOLD.
- This probe does not make OpenCode conversation state a durable authority.
