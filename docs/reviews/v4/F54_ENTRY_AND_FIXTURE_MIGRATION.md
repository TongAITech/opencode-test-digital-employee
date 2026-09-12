# F54 tool-entry wiring and host-fixture migration

Incremental delivery after F53 foundation `09d1c86a7ca575d9d2efbdbfc47990602617a15a`. This patch owns entry wiring and regression fixtures; `general_work.execution`, its lease/session lifecycle and scoped file/OS brokers are separate runtime-owner work.

## Entry changes

The compatible default Primary name remains `aitest-director`. Its tools are now limited to the typed interaction entry, bounded PFC truth and questions. Old direct G3/G4/recovery/HumanGate write paths are unavailable to Primary until admitted typed-owner routes exist. Two dedicated subagents, `aitest-general-worker` and `aitest-runtime-diagnosis`, may use only `aitest_general_worker`; both deny all other tools. Installation and host capability checks require the two agents and worker tool.

The worker tool exposes eight strict actions: status, read_file, search_files, write_file, git_inspect, terminal, checkpoint and complete. It rejects caller/lease/root/approval fields, checks the action's payload schema before process spawn and invokes the dedicated `general-work` CLI. Every action requires a job_id. Actual host session/message/call identity is overwritten from ToolContext, never inherited from user payload. The raw host-recorded payload is forwarded without inserting schema defaults; the runtime owner matches the host tool part before applying defaults.

For admitted GeneralWork/RuntimeDiagnosis proposals, `hosted_interaction` calls `GeneralExecutionService(runtime, workspace_root, session_provider).start(admitted, owner)`. `operation_text` is the exact span of the just-verified actual user text, passed only through this trusted in-memory call. The receipt's immutable nine-field schema is unchanged. The executor owns policy, claim/job binding, replay and dispatch; its status/result is preserved. Missing executor module fails closed. The worker CLI delegates host-call/current-job/session/epoch checks to the actual runtime owner. No local fake executor is installed.

## Exact host call identifier evidence

Installed `@opencode-ai/plugin` 1.18.3 `dist/tool.d.ts` omits `callID`. Official exact v1.18.3 runtime source confirms it is actually present: `packages/opencode/src/session/tools.ts` lines 59–64 sets `callID: options.toolCallId`; `packages/opencode/src/tool/registry.ts` lines 142–148 spreads `toolCtx` into the plugin context. The local optional TypeScript field follows that observed source; missing values become an empty environment field so the runtime owner can use its verified unique host-part fallback or reject.

Sources: https://raw.githubusercontent.com/anomalyco/opencode/v1.18.3/packages/opencode/src/session/tools.ts and https://raw.githubusercontent.com/anomalyco/opencode/v1.18.3/packages/opencode/src/tool/registry.ts . Exact copies and SHA256 manifest are delivered in `work/v4-implementation/interaction-sdk-source`. Source evidence and a bridge unit test do not by themselves prove a real host callback.

## Executed qualification

Six old raw-request product fixtures now obtain actual fixture-owned user/assistant parent messages and enter F53 through the real product route. Their previous raw R2 authorization envelopes are not supplied. Shared in-process fixture code asserts two host reads and a COMPLETED real R1 interaction receipt bound to the actual Mission. The two HTTP fixtures use real local HTTP, the production DirectoryScoped provider and independent runtime processes. No test is converted wholesale into a trusted internal bypass.

- G1/G2 subprocess: 9/9 checks, 30 real local HTTP requests.
- Background control-loop subprocess: 8/8 checks, 35 real local HTTP requests.
- G3 product: 50/50 checks.
- G4 capability HumanGate: 4/4 checks.
- G4 full same-Mission product: 20/20 checks.
- G5 product: 39/39 checks.
- Interaction/admission/receipt plus entry-port suite: 39 unittest methods. The three new entry tests use an explicit port spy and prove routing only, not execution.
- Installed plugin schema and bridge: seven checks passed, including strict identity fields, raw input preservation and overriding all three host identifiers. Bun spawn is an explicit unit-test spy, not a real worker or host.
- Host capability adapter regression: 3/3 tests.

The machine's PATH initially selected Git 2.23, which lacks `init -b`; repository fixtures were executed with `/usr/bin` first (Apple Git 2.50.1). Local HTTP fixture binds required the allowed local-network execution permission. Neither issue changed product code or assertions.

## Remaining acceptance

Actual GeneralExecutionService implementation, current-session/epoch enforcement, policy leases, scoped file broker, Windows AppContainer execution, real OpenCode worker dispatch/callback, compaction/recovery and actual model semantics remain to be qualified after integration. Controls, Mission updates, independent HumanGate verification and staged receipt reconciliation still require typed owner wiring. Primary no longer has a direct write bypass for those missing routes. This delivery does not claim full F53/F54 or bank validation.
