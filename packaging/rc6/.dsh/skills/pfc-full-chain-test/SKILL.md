---
name: pfc-full-chain-test
description: Run one governed PFC release Mission from requirement/code analysis through L1-L7 execution, evidence, defects, empirical coverage and report. RC6 Runtime chooses the next legal directive; chat completion is never test completion.
---

# PFC Full Chain Test — RC6 Autonomous Mission

Use this skill only as the coordinator entry. The coordinator MUST stay thin. It may execute Runtime routing directives, issue workers/leases, checkpoint and summarize artifact references. It MUST NOT perform requirement analysis, code analysis, test design, data construction, test execution, CAT diagnosis, or rewrite a frozen Case itself.

## Mandatory autonomous control loop

1. Call `mcp__pfc_aitest_rc6__runtime_status` and fail closed unless `autonomous_orchestrator=true`.
2. Create or load one durable Mission with `mission_create` / `mission_status`.
3. Call `mission_control_tick`. Treat the returned `MissionDirective` as the ONLY legal next high-level action.
4. Execute exactly that directive through the governed worker/tool/runtime path. Do not invent, skip or reorder phases.
5. Persist professional artifacts through `artifact_record`; never use chat claims or ad-hoc files as completion truth.
6. Run the deterministic evaluator requested by `RUN_GATE`. Only a real runtime PASS with an evidence reference may be committed with `mission_gate_commit`; a failed evaluator must use `mission_gate_block` and route the stated gap back to the owning professional worker.
7. Call `mission_control_tick` again. Repeat until Runtime returns `COMPLETE` or an explicit `BLOCKED`/unrecoverable condition.

The coordinator MUST NOT advance a Stage itself. `mission_plan_next` is read-only inspection; `mission_control_tick` is the state transition authority and advances at most one legal Stage per call.

## Session rotation is automatic Mission work

Mission != DSH Session. R1 Event Stream is the sole durable business truth; DSH session/subagent/job history is disposable compute history. Before coordinator context becomes unsafe, call `mission_control_tick` with `context_pressure=true`. Runtime writes a checkpoint, increments coordinator generation and returns `ROTATE_SESSION` plus a bounded ResumeEnvelope reference. Start the successor coordinator session from that envelope and resume the control loop. Never ask the user to type “continue”. Compaction is not Session Rotation.

## Worker authority and tool admission

Every professional worker MUST receive a runtime-issued identity (`worker_issue`) and signed lease (`lease_issue`). Before an external professional tool call, require both lease authorization (`tool_authorize`) and exact Worker/Target capability admission (`capability_admit`). Discovery alone is never READY; real probe/call evidence must be recorded through capability tools.

Wrong-role artifact writes, mixed-layer cases and lease/tool scope violations are Runtime errors, not warnings. A failed worker may only rotate/split into the same role/layer; the coordinator cannot impersonate it.

## Durable truth and Bank Reality

Professional artifacts MUST be persisted through `artifact_record`. Use `truth_inventory` / `truth_query` for Mission truth. Never infer completion from DSH messages.

Bank facts are read through `reality_list` / `reality_get` and refreshed through `reality_reconcile`; do not guess routes, repository revisions, DB profiles, account bindings, 4A or CAT. Build the unique execution target with `target_build`, then bind its `TARGET-*` identity to the current Mission with `mission_bind_target`. Any STALE/NEEDS_BINDING fact blocks execution.

## Professional roles and layers

Use independent requirement analyzer/reviewer, code analyzer/reviewer, TEST_FUSION, and independent L1-L7 design/execution workers for every applicable layer. Test Fusion owns Test Intent and Test Condition; the coordinator cannot create them. Never combine layers such as `L2|L3` or `L2|L3|L4` into one Case/worker.

- L1: code/unit, JUnit/Maven, changed method/line/branch and mutation evidence when available.
- L2: DB/component/internal integration, SQL/transaction/state evidence.
- L3: API/service integration, route/schema/auth/error/business evidence.
- L4: browser/UI, BrowserSkill/Playwright, page/control/state/network evidence.
- L5: E2E/cross-system journey and consistency evidence.
- L6: performance/workload/SLO evidence, k6 when admitted.
- L7: security/attack surface/control evidence, ZAP/API/browser when admitted.

`SPAWN_LAYER_WORKERS` means: evaluate L1-L7 applicability from Test Conditions, persist the decision/evidence in the governed runtime path, then spawn one professional design worker per applicable layer. No feature-slice or mixed-layer worker may substitute for a layer worker.

## Analysis, design and execution closure

Requirement and Code gates are computed from stored evidence; ignore self-reported percentages. When CodeGraph is required, require Tool Broker admission and real CodeGraph call/evidence. Build Requirement+Code -> Test Intent -> Test Condition -> applicability -> layer-specific candidates. Run semantic Coverage Subject and Oracle evaluation, generate explicit gaps, perform delta design and re-evaluate until critical/high-risk gaps are closed. Only then freeze Cases.

For every frozen Case: resolve/verify preconditions; search/build/verify/bind test data; freeze the PreparedAttempt; then execute with the corresponding Lx Execution worker. Product assertion failure after valid preparation and a real action is PRODUCT evidence and cannot be retried/reprepared to green.

Failures use evidence-driven diagnosis. L3/L5 require CAT correlation when applicable; L1 requires CAT only for remote integration. Retry only transient failures within runtime budget. DATA/PRECONDITION/AUTH/TOOL/ROUTE/ENVIRONMENT/DESIGN follow distinct recovery paths.

After execution, calculate layer-specific empirical coverage from real evidence on the exact TargetIdentity. Gaps route to same-layer DELTA_EXECUTION or DELTA_DESIGN and are re-evaluated. Admin/API/Allure/report are derivatives of R1 only and must reconcile identities/counts before Mission completion.

Never declare the bank release qualified merely because this engineering candidate boots or CI is green. Bank Field PASS requires a real same-Mission BLOAN release chain, real bank tools/environment, automatic multi-session continuation, real execution/evidence and report closure.
