---
name: pfc-full-chain-test
description: Run one governed PFC release Mission from requirement/code analysis through L1-L7 execution, evidence, defects, empirical coverage and report. Use RC6 MCP/runtime truth; never treat chat completion as test completion.
---

# PFC Full Chain Test — RC6

Use this skill only as the coordinator entry. The coordinator MUST stay thin: route work, evaluate runtime gates, checkpoint, and summarize artifact references. It MUST NOT perform requirement analysis, code analysis, test design, data construction, test execution, CAT diagnosis, or rewrite a frozen Case itself.

## Durable truth

- Mission != DSH Session.
- R1 Event Stream is the sole durable business truth.
- DSH session/subagent/job events are compute history, not product completion truth.
- A Stage may advance only when the corresponding RC6 runtime gate passes from stored evidence.
- `PASS` requires a real action, actual result, oracle assertion, current evidence and tool-call provenance on the exact TargetIdentity.

## Start / resume

1. Call `mcp__pfc_aitest_rc6__runtime_status` and fail closed if RC6 runtime identity is unavailable.
2. Create or load the durable Mission with `mcp__pfc_aitest_rc6__mission_create` / `mission_status`.
3. Resolve Bank Reality and a unique TargetIdentity before execution. Never guess routes, repositories, deployed revision, accounts, DB profiles or environment.
4. Keep coordinator context bounded. Before context pressure, checkpoint with `mission_checkpoint`, end the current coordinator session and continue from the ResumeEnvelope in a fresh session. Do not ask the user to type “continue”.

## Professional workers

Use independent workers for requirement analysis/review, code analysis/review, and each applicable layer. L1-L7 Design and L1-L7 Execution are separate roles. Never combine layers such as `L2|L3` or `L2|L3|L4` into one Case/worker. A failed worker may only be split/rotated into the same role; the coordinator cannot impersonate it.

Layer responsibilities:
- L1: code/unit, JUnit/Maven, changed method/line/branch and mutation evidence when available.
- L2: DB/component/internal integration, SQL/transaction/state evidence.
- L3: API/service integration, route/schema/auth/error/business evidence.
- L4: browser/UI, BrowserSkill/Playwright, page/control/state/network evidence.
- L5: E2E/cross-system journey and consistency evidence.
- L6: performance/workload/SLO evidence, k6 when admitted.
- L7: security/attack surface/control evidence, ZAP/API/browser when admitted.

## Analysis and design closure

Requirement and Code gates must be computed from stored evidence; ignore self-reported percentages. When CodeGraph is required, require a real admitted CodeGraph call and evidence reference. Build Test Intent -> Test Condition -> layer applicability -> layer-specific Case Candidates. Run Coverage Subject and Oracle evaluation, generate explicit gaps, perform delta design, and re-evaluate until all critical/high-risk gaps are closed. Only then freeze Cases.

## Preparation and execution

For every frozen Case: resolve and verify preconditions; search/build/verify/bind test data; freeze the PreparedAttempt; then execute with the corresponding Lx Execution worker. Do not let an execution worker modify a frozen Case or silently swap data. Product assertion failure after valid preparation and a real action is terminal PRODUCT evidence and cannot be retried/reprepared to green.

Failures use evidence-driven diagnosis. L3/L5 require CAT correlation when applicable; L1 requires CAT only for remote integration. Retry only transient failures within runtime budget. DATA/PRECONDITION/AUTH/TOOL/ROUTE/ENVIRONMENT/DESIGN follow distinct recovery paths.

## Empirical coverage and reporting

After execution, calculate layer-specific empirical coverage from real evidence on the exact TargetIdentity. Gaps route to same-layer DELTA_EXECUTION or DELTA_DESIGN and must be re-evaluated. Admin/API/Allure/report are derivatives of R1 only. Reconcile identities/counts before Mission completion.

Never declare the bank release qualified merely because this engineering candidate boots. Bank Field PASS requires the real same-Mission chain to complete without user continuation loops.
