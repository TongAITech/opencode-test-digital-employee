# RC8 Implementation Status

Current branch: `work/rc8-control-plane-foundation`
RC7 base: `work/rc7-field-hardening@33433c8664ad73627409b27646d437e9efe66144`
Last automated-tested code head: `0cca6ec32645bf30cb36eefcb15dc4ce0c7bf7db`
Authoritative automated run: GitHub Actions `RC8 Core Foundation` run `39625905641` = SUCCESS.

## Current wave

W0/W1 foundation: IN PROGRESS

## Done / automated-tested foundation

- RC8 Master Contract frozen.
- RC8 Architecture Baseline frozen for W0/W1.
- RC8 Product Baseline frozen.
- Requirement Traceability Matrix created and first TESTED rows recorded.
- RC7 -> RC8 carry-forward Gap Matrix created.
- `RequirementDeliveryScope` canonical identity added and tested for one requirement spanning multiple system-version/application/SST scopes.
- Execution-node canonical model added.
- Capability qualification state chain added: DISCOVERED -> REGISTERED -> EXECUTED -> ASSERTED -> EVIDENCE_PERSISTED -> VERIFIED.
- VERIFIED capability requires evidence and is the only scheduler-eligible state.
- Platform/architecture/node-package change invalidates prior verified capabilities and forces requalification.
- Deterministic node liveness rules added.
- WorkItem lease/renew/release/expiry domain rules added.
- RC8 event envelope preserves source R1 event identity/sequence and idempotency key; it does not define a second runtime truth.
- Artifact manifest binds TestRun/Mission/WorkItem/Node and optional Case/Attempt/Step/Assertion lineage.
- Artifact state requires declare -> upload -> verified size/hash -> AVAILABLE.
- Center storage-agnostic ingest rejects idempotency conflicts and hash/size mismatches.
- `CenterControlPlane` service boundary added.
- `NodeAgent` boundary added.
- Dependency-free Node -> Center HTTP client added.
- Center HTTP control endpoints added for node registration/heartbeat/capability, WorkItem lease, runtime event and artifact metadata lifecycle.
- First networked single-node vertical test passes: node registers over HTTP, qualifies capability, leases a WorkItem, publishes idempotent R1-derived event, declares/verifies assertion evidence, and the product API observes the same node/current-task state.
- Execution-node product read model and live query/detail API added.
- First execution-node product sample page added with Chinese-first restrained layout, query/list and large detail shell; it consumes live `/api/nodes` projection and contains no mock node rows.
- Product HTTP smoke verifies live node JSON and Chinese product shell.
- RC8 Python 3.8 CI foundation covers `rc8_control`, `rc8_center`, `rc8_node`, `rc8_product` and RC7 import compatibility.

## Test / reality state

- Automated CI state for code head `0cca6ec32645bf30cb36eefcb15dc4ce0c7bf7db`: PASS (`39625905641`).
- The networked vertical is an automated localhost HTTP integration test, not bank-environment reality verification.
- Local container could not clone GitHub because external DNS is unavailable in that execution environment; this is not treated as RC8 product failure or PASS.
- No RC8 bank-environment reality claim has been made.
- No requirement is CLOSED merely because the automated vertical is green.

## Next construction — single entry point

W1 persistence/real-service continuation, without redesign:

1. Introduce persistence ports and PostgreSQL adapters for durable Node/TestRun/WorkItem/Event/Artifact metadata; Redis may coordinate leases/cache but must not become durable truth.
2. Introduce artifact file-storage adapter and durable Node upload queue; keep Artifact Sync contract unchanged.
3. Promote the current in-memory Center into a restartable service using those adapters while preserving the tested HTTP protocol.
4. Add durable TestRun/Mission/WorkItem identities/state instead of passing only string IDs through transport.
5. Connect the first real RC7 capability adapter (prefer proven Maven/JUnit or CodeGraph) through Node Agent and store its real evidence.
6. Continue execution-node product sample against durable state; do not expand all product pages until this vertical survives restart.

## Explicitly not done yet

- PostgreSQL persistence adapters / schema migrations.
- Redis lease adapter.
- Durable TestRun/Mission/WorkItem state machine.
- Actual artifact file/chunk/resume transfer (current slice verifies metadata/integrity lifecycle only).
- Durable node upload queue.
- Center node-package download/upgrade repository.
- Frozen RC7 offline toolset manifest/package.
- Windows Git Bash / Xinchuan Linux real node package validation.
- Business-flow recorder/API dependency graph.
- Skill registry/distribution.
- Knowledge registry/evolution.
- Cross-node Gap Router/invalidation loop.
- Test-data builder/resource lease.
- Remaining product modules.
- Bank reality qualification.

## Completion rule

No item becomes CLOSED until implementation, automated test, required reality evidence and applicable product projection all pass. Code existence, mock-only success and worker self-report do not close RC8 requirements or RC7 carry-forward gaps.