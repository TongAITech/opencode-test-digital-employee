# RC8 W1 Single-Node Vertical Slice Contract

Status: FROZEN-CANDIDATE
Depends on: W0 Truth & Identity contracts

## Objective
Prove the smallest truthful RC8 system before expanding to multi-node scheduling or broad product pages:

`1 Center + 1 Windows Git Bash DSH Node + 1 TestRun + 1 WorkItem + 1 real RC7 capability + R1 event + assertion/evidence + truthful product projection`.

The same Node protocol must remain portable to Xinchuang Linux bash; Windows is the first reality slice because current bank validation primarily runs on office Windows PCs.

## Slice scope
Use a low-risk RC7 capability that already has reality evidence and can produce deterministic machine-readable output. Candidate preference order:
1. CodeGraph probe/query when the local bank tool is available;
2. Maven/JUnit minimal harness;
3. AnyDoc document parse;
4. Browser/network probe only after the first Center/Node transport is stable.

The slice must not fake the RC7 tool. If a candidate is unavailable in the execution environment, the node advertises it UNAVAILABLE and the slice selects another VERIFIED capability.

## Required sequence
1. Center creates `ProductionBatch`, `RequirementDeliveryScope`, `TestRun`, `WorkItem`.
2. Node starts from `rc8-node.sh` under Git Bash.
3. Node registers identity and heartbeat.
4. Node runs a real capability probe; Center records qualification evidence.
5. Node leases the WorkItem; lease owner is the node/worker, not a DSH Session.
6. DSH/Worker invokes one real RC7 capability through an adapter.
7. Node emits ordered runtime events to central R1.
8. Tool output produces at least one actual assertion and typed EvidenceManifest.
9. Artifact Sync uploads the evidence asset and it reaches AVAILABLE.
10. Independent evaluator decides PASS/FAIL from Actual + Assertion + Evidence.
11. Center projection shows task/case/attempt/evidence truth.
12. Minimal Chinese product page can answer what ran, actual result and evidence without reading DSH logs.
13. Kill/restart DSH; TestRun identity/state remains.
14. Restart Node Agent; it reconnects and does not duplicate runtime facts.

## Minimal Center APIs/contracts
Transport can evolve, but semantic contracts are frozen:
- node register/heartbeat
- capability report/probe evidence
- WorkItem list/lease/start/complete
- runtime event append with idempotency key
- artifact upload manifest/content/complete
- TestRun projection query
- node projection query

Node does not receive database credentials.

## Minimal product surfaces
Do not build the full 13-module product in W1. Build two sample surfaces using the RC8 Product Baseline design system:
1. `测试任务` detail: current phase, work item, actual execution, assertion, evidence.
2. `执行节点` detail/list: online/status/capabilities/current task/last heartbeat.

These two surfaces establish typography, spacing, filters, table, large-detail shell, tabs and status style for later product pages.

## Reality acceptance
W1 is not REALITY_VERIFIED by unit tests alone. Required evidence:
- Center startup log/health
- Node Git Bash startup log
- node registration/heartbeat record
- capability real-probe evidence
- WorkItem lease record
- RC7 real tool execution evidence
- canonical R1 runtime events
- assertion result
- uploaded artifact hash/content
- product screenshots showing truthful projection
- DSH restart recovery result

## Failure rules
- plugin/tool discovered but no probe => not VERIFIED;
- DSH/model says “executed” but no RC7 tool evidence => FAIL;
- PASS without assertion-bound AVAILABLE evidence => FAIL;
- product says complete while R1/Completion gate says incomplete => FAIL;
- DSH Session restart loses TestRun => FAIL;
- W1 requires a second node to function => FAIL;
- Windows requires cmd/PowerShell as canonical startup instead of Git Bash => FAIL.

## Exit
Only after this slice is REALITY_VERIFIED may RC8 broaden into business-flow recording, cross-stage loop, shared skills/knowledge and multi-node collaboration while retaining the same truth contracts.
