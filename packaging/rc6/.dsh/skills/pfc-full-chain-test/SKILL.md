---
name: pfc-full-chain-test
description: Run one governed PFC release Mission from requirement/code analysis through L1-L7 execution, evidence, defects, empirical coverage and report. Use RC6 MCP/runtime truth; never treat chat completion as test completion.
---

# PFC Full Chain Test — RC6

Use this skill only as the coordinator entry. The coordinator MUST stay thin: route work, evaluate runtime gates, checkpoint, and summarize artifact references. It MUST NOT perform requirement analysis, code analysis, test design, data construction, test execution, CAT diagnosis, or rewrite a frozen Case itself.

## Mandatory control plane

Before professional work, call `mcp__pfc_aitest_rc6__runtime_status`. All professional workers MUST receive a runtime-issued identity (`worker_issue`) and signed lease (`lease_issue`). Before an external tool call, require both lease authorization (`tool_authorize`) and exact Worker/Target capability admission (`capability_admit`). Discovery alone is never READY; real probe/call evidence must be recorded through the capability tools.

Professional artifacts MUST be persisted through `artifact_record`, never by chat claims or ad-hoc files. `artifact_record` enforces Role/Lease/Layer authority, validates the canonical domain contract, appends one atomic R1 event, applies projection, and requires read-after-write integrity. Use `truth_inventory` / `truth_query` for Mission truth. Never infer completion from DSH messages.

Bank facts are read through `reality_list` / `reality_get` and refreshed through `reality_reconcile`; do not guess routes, repository revisions, DB profiles, account bindings, 4A or CAT. Build a unique execution target with `target_build`; any STALE/NEEDS_BINDING fact blocks execution.

## Durable Mission and session rotation

Mission != DSH Session. R1 Event Stream is the sole durable business truth; DSH session/subagent/job events are compute history only. Create/load the durable Mission with `mission_create` / `mission_status`. Keep coordinator context bounded. Before context pressure, call `mission_checkpoint`, end the current coordinator session and continue from the ResumeEnvelope in a fresh session. Never ask the user to type “continue”.

## Professional roles

Use independent requirement analyzer/reviewer, code analyzer/reviewer, TEST_FUSION, and each applicable layer. Test Fusion owns Test Intent and Test Condition; the coordinator cannot create them. L1-L7 Design and L1-L7 Execution are separate roles. Never combine layers such as `L2|L3` or `L2|L3|L4` into one Case/worker. A failed worker may only rotate/split into the same role (`worker_rotate` preserves role/layer).

Layer responsibilities:
- L1: code/unit, JUnit/Maven, changed method/line/branch and mutation evidence when available.
- L2: DB/component/internal integration, SQL/transaction/state evidence.
- L3: API/service integration, route/schema/auth/error/business evidence.
- L4: browser/UI, BrowserSkill/Playwright, page/control/state/network evidence.
- L5: E2E/cross-system journey and consistency evidence.
- L6: performance/workload/SLO evidence, k6 when admitted.
- L7: security/attack surface/control evidence, ZAP/API/browser when admitted.

## Analysis and design closure

Requirement and Code gates are computed from stored evidence; ignore self-reported percentages. When CodeGraph is required, require real Tool Broker admission and a real CodeGraph call/evidence reference. Build Requirement+Code -> Test Intent -> Test Condition -> layer applicability -> layer-specific Case Candidates. Run Coverage Subject and Oracle evaluation, generate explicit gaps, perform delta design, and re-evaluate until critical/high-risk gaps are closed. Only then freeze Cases.

## Preparation and execution

For every frozen Case: resolve and verify preconditions; search/build/verify/bind test data; freeze the PreparedAttempt; then execute with the corresponding Lx Execution worker. Do not let an execution worker modify a frozen Case or silently swap data. Product assertion failure after valid preparation and a real action is terminal PRODUCT evidence and cannot be retried/reprepared to green.

Failures use evidence-driven diagnosis. L3/L5 require CAT correlation when applicable; L1 requires CAT only for remote integration. Retry only transient failures within runtime budget. DATA/PRECONDITION/AUTH/TOOL/ROUTE/ENVIRONMENT/DESIGN follow distinct recovery paths.

## Empirical coverage and reporting

After execution, calculate layer-specific empirical coverage from real evidence on the exact TargetIdentity. Gaps route to same-layer DELTA_EXECUTION or DELTA_DESIGN and must be re-evaluated. Admin/API/Allure/report are derivatives of R1 only. Reconcile identities/counts before Mission completion.

Never declare the bank release qualified merely because this engineering candidate boots. Bank Field PASS requires the real same-Mission chain to complete without user continuation loops.
