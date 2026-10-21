# RC8 Implementation Status

Current branch: `work/rc8-control-plane-foundation`
RC7 base: `work/rc7-field-hardening@33433c8664ad73627409b27646d437e9efe66144`

## Current wave

W0/W1 foundation: IN PROGRESS

## Done

- RC8 Master Contract frozen.
- RC8 Architecture Baseline frozen for W0/W1.
- RC8 Product Baseline frozen.
- Requirement Traceability Matrix created.
- RC7 -> RC8 carry-forward Gap Matrix created.
- `RequirementDeliveryScope` canonical identity added.
- Execution-node canonical model added.
- Capability qualification state chain added.
- Deterministic node liveness rules added.
- WorkItem lease/renew/release domain rules added.
- Scheduler eligibility requires VERIFIED capability evidence.
- RC8 Python 3.8 CI foundation added.

## Reality / test state

- Local container could not clone GitHub because external DNS is unavailable in the execution environment; this is not treated as test PASS or product failure.
- GitHub Actions `RC8 Core Foundation` is the current authoritative automated gate for the new slice.
- No bank-environment reality claim has been made for RC8.

## In progress / next construction

1. Make RC8 Core Foundation CI green and record evidence.
2. Add central Event/Artifact identity contracts that adapt rather than replace RC7 R1.
3. Add node heartbeat/capability/lease persistence ports and a minimal Center service boundary.
4. Add a minimal Node Agent protocol client skeleton using the same contracts.
5. Add the first product projection for 执行节点 so runtime node state can be queried without DSH logs.

## Explicitly not done yet

- PostgreSQL/Redis adapters.
- Artifact chunk/resume upload.
- Center HTTP API.
- Node package download.
- Windows Git Bash / Xinchuan Linux runtime package.
- Business flow recorder.
- Skill/knowledge registry.
- Cross-node closed-loop engine.
- Full product pages.
- Bank reality qualification.

## Completion rule

No item becomes CLOSED until implementation, automated test, required reality evidence and applicable product projection all pass.