# RC8 Current Handoff

Status: ACTIVE CONSTRUCTION HANDOFF

Repository: `TongAITech/opencode-test-digital-employee`
Branch: `work/rc8-control-plane-foundation`
RC7 source baseline: `work/rc7-field-hardening@33433c8664ad73627409b27646d437e9efe66144`
Handoff snapshot base head: `bc10772ef9bc4ccd91129d4d89349ca25c29b31b`
Last automated-tested code head: `0cca6ec32645bf30cb36eefcb15dc4ce0c7bf7db`
Authoritative automated evidence: `RC8 Core Foundation` GitHub Actions run `39625905641` = SUCCESS.

On resume, inspect the actual branch HEAD first. Never reset to the snapshot base if the branch has advanced.

## Required baselines to read before changing design

1. `docs/rc8/RC8-MASTER-CONTRACT.md`
2. `docs/rc8/RC8-ARCHITECTURE-BASELINE.md`
3. `docs/rc8/RC8-PRODUCT-BASELINE.md`
4. `docs/rc8/RC8-REQUIREMENT-TRACEABILITY-MATRIX.md`
5. `docs/rc8/RC7-TO-RC8-GAP-MATRIX.md`
6. `docs/rc8/RC8-IMPLEMENTATION-STATUS.md`

Do not re-plan RC8 from scratch. Git/HEAD + these frozen baselines + tests/evidence are the construction truth.

## What this construction session completed

### Governance / design freeze

- Created RC8 construction branch from the latest inspected RC7 Field Hardening baseline.
- Frozen Master Contract, Architecture Baseline and Product Baseline.
- Created 60-item requirement traceability matrix.
- Created 30-item RC7 -> RC8 carry-forward gap matrix.
- Recorded the invariant that RC7 verified capabilities must not regress.

### W0/W1 domain foundation

- `RequirementDeliveryScope` supports one requirement spanning multiple system versions/applications/SSTs.
- Canonical execution node identity/status/capability contracts.
- Reality qualification chain; package presence cannot directly become VERIFIED.
- Node runtime fingerprint change invalidates old capability verification.
- Heartbeat/offline rules.
- WorkItem lease/renew/release/expiry rules.
- R1-derived central event envelope with source event identity/sequence + idempotency key.
- Artifact manifest with TestRun/Mission/WorkItem/Node and Case/Attempt/Step/Assertion lineage.
- Artifact declare/upload/hash-size-verify lifecycle.
- Idempotent central runtime ingest.

### First single-node network vertical

Implemented and automatically tested:

`NodeAgent -> real HTTP -> CenterControlPlane -> NodeRegistry/RuntimeIngest -> Product projection`

The automated vertical proves:
- node HTTP registration;
- evidence-based capability qualification;
- WorkItem lease;
- idempotent R1-derived runtime event ingestion;
- assertion evidence declaration/integrity completion;
- live product query sees the same node and current WorkItem;
- release returns node to idle.

This is automated integration evidence only. It is NOT bank-environment Reality PASS.

### First product sample

Added execution-node query/detail surface:
- Chinese-first copy;
- restrained Apple-inspired visual direction;
- left navigation + query/list main surface;
- large 92vw/92vh detail shell;
- basic info/capability/current-task/history tabs;
- no dashboard cards;
- no mock node rows;
- data comes from live NodeRegistry projection;
- runtime/resource tabs explicitly avoid fake data until their real sources are implemented.

The visual design has not yet been user screenshot-reviewed and therefore must not be called product-approved.

## Known CI fact

Code head `0cca6ec32645bf30cb36eefcb15dc4ce0c7bf7db` passed `RC8 Core Foundation` run `39625905641`.

A prior run on `bde1e7e...` failed because the test used synthetic ancient heartbeat timestamps while product liveness used the real clock. The test was corrected to use the real clock and the next code head passed. Do not report the failed prior head as current.

## DO NOT redo

- Do not create a new RC8 architecture from scratch.
- Do not replace RC7 execution capabilities with new implementations without an Architecture Decision and regression proof.
- Do not replace R1 with a second runtime truth store.
- Do not bind TestRun truth to DSH Session.
- Do not mark plugin/package presence as verified capability.
- Do not mark artifact metadata as Evidence AVAILABLE before integrity verification.
- Do not expand all 13 product pages before the durable single-node vertical is proven.
- Do not add dashboard-heavy/card-heavy UI.
- Do not exact-version-pin platform tools when a capability check is sufficient.

## Next unique construction entry

Continue W1/W3 durability, not redesign:

1. Define persistence ports and schema for durable Node, TestRun, Mission, WorkItem, R1 event projection and Artifact metadata.
2. Add PostgreSQL adapter/migrations. Redis may coordinate leases/cache only; durable truth must survive Redis loss.
3. Add real artifact file-storage adapter and node durable upload queue; preserve current Artifact contract.
4. Restart test: Center restart must preserve TestRun/node/runtime metadata and product projection.
5. Add explicit durable TestRun/Mission/WorkItem models/state instead of transport-only string IDs.
6. Migrate the first proven RC7 capability through Node Agent (prefer Maven/JUnit or CodeGraph) and capture its real Evidence.
7. Only after this vertical survives restart, screenshot/review the execution-node product sample and freeze reusable visual components before expanding other product modules.

## Current non-claims

RC8 is NOT delivered.
RC8 is NOT bank-reality-verified.
The full RC7 toolset is NOT yet packaged into RC8 Node.
Windows Git Bash and Xinchuan Linux packages are NOT yet validated.
Business-flow recording, skill/knowledge sharing, cross-node closed loop, self-evolution and full product surfaces remain future construction slices.
