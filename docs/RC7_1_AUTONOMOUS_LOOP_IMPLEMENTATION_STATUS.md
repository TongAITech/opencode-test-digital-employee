# RC7.1 Autonomous Loop Implementation Status

## Contract

- Contract ID: `RC-AUTONOMOUS-TEST-LOOP`
- Contract Version: `1.0.0`
- Accepted Starting SHA: `98d7ee59cb3caf760177d7aaa933ee70082a6ff3`
- Construction Branch: `work/rc7.1-autonomous-loop`
- Engineering-verified Wave A implementation HEAD: `bf8badf3dc687eba3a2d092174ff1a31706f4ba1`
- Engineering-verified Wave B implementation HEAD: `4ad0d32eb009e870760db185bb8f5975705fdd5d`

## Reality boundary

- Controlled Engineering: PASS for Waves A-B
- Wave A validation run: `40071040146` (#72)
  - targeted Ubuntu: PASS
  - targeted Windows: PASS
  - full-rc7: PASS
- Wave B validation run: `40077002904` (#79)
  - targeted Ubuntu: PASS
  - targeted Windows: PASS
  - full-rc7: PASS
- Bank Field Reality: `NOT_VERIFIED`

Controlled Engineering PASS MUST NOT be reported as Bank Field Reality PASS.

## Waves

| Wave | Scope | Status |
|---|---|---|
| A | Foundation registries/contracts/router/events/durable node control/coverage ledger | ENGINEERING_VERIFIED |
| B | N1-N4 autonomous node adoption | ENGINEERING_VERIFIED |
| C | N5-N6 preparation/script closure | IN_PROGRESS |
| D | N7 coverage-driven execution closure | NOT_STARTED |
| E | N8-N9 recovery/defect closure | NOT_STARTED |
| F | N10 mission convergence/reporting | NOT_STARTED |

## Wave A delivered

- CanonicalNodeRegistry N1-N10
- CanonicalLayerRegistry L1-L7
- NodeLoopState and durable NodeIteration lineage in R1
- immutable NodeDeliveryPackage + R1 Artifact/Evidence/ready receipt
- canonical Gap routing foundation
- CoverageDenominatorSnapshot / CoverageObligation / CoverageLedger / LayerCoverageReceipt
- canonical autonomous R1 event registry
- machine-readable contract registries and five delivery schemas
- fail-closed contract validator and CI hard gates
- RC7.1 execution profiles restored to canonical L5 E2E / L6 Performance / L7 Security
- L4-L7 production evidence gate aligned to canonical taxonomy
- DATA/PRECONDITION/AUTH recovery routed to Runtime Preparation (logical N5)
- dynamic backend-dispatch-aware CAT policy covering L3/L4/L5/L6/L7
- unrealized execution contracts classified as SCRIPT repair instead of UNKNOWN/BLOCKED
- existing real dsh-agent-teams assignment/member receipt path retained and hard-tested

## Wave B delivered

- N2 Requirement, N3 Code and N4 Test Design evaluated subtask PASS no longer constitutes node-level PASS by itself
- immutable NodeDeliveryPackage + separate Director acceptance/rejection gate for N1-N4
- Director cannot reuse specialist/evaluator identity or impersonate a node worker
- Director rejection preserves prior lineage and requires a delta before the next iteration
- N1 Runtime Reality Recon is bound into the autonomous node contract without replacing the existing runtime-owned recon engine
- N1 autonomous readiness requires current environment, target version, source revision and durable VERIFIED capability/service proof
- N1 mandatory capabilities include DSH headless, AgentTeams bootstrap, fresh auth, Browser Network route discovery and Runtime execution
- legacy Reality Recon PASS without the autonomous proof matrix cannot impersonate N1 completion
- `AUTONOMOUS_NODE_GATE` Evaluation evidence is now fail-closed at the R1 durable boundary: evidence must exist and belong to the same Mission
- N1/N2/N3/N4 final node PASS remains Director-gated; N1 engineering fixtures explicitly have no Bank Field certification authority

## GAP status after Waves A-B

- `RC71-AL-001` ENGINEERING_VERIFIED
- `RC71-AL-002` ENGINEERING_VERIFIED
- `RC71-AL-006` ENGINEERING_VERIFIED
- `RC71-AL-007` ENGINEERING_VERIFIED
- `RC71-AL-017` FOUNDATION + N1-N4 ADOPTION ENGINEERING_VERIFIED; N5-N10 adoption continues in Waves C-F
- `RC71-AL-018` REGISTRY + N1-N4 NODE EVENTS ENGINEERING_VERIFIED; later node-specific events continue in Waves C-F
- `RC71-AL-019` EXISTING_ENGINEERING_VERIFIED; Bank Field still NOT_VERIFIED
- `RC71-AL-008` PARTIAL: ownership/routing fixed; fresh 4A preparation lifecycle is Wave C
- `RC71-AL-003/004/005` foundation exists; full N7 implementation is Wave D
- `RC71-AL-009/010/011/012/013` remain Wave E
- `RC71-AL-014/015/016` remain Wave F
- `RC71-AL-020` remains OPEN until real bank-field evidence exists

## Next exact work item — Wave C N5-N6

Do not rewrite working preparation/script engines. Integrate them into the shared autonomous contract:

1. preserve Runtime-owned side effects and existing Provider/Human Gate truth
2. add N5 batch preparation planning/shared resource truth without treating a batch snapshot as execution proof
3. require per-Case final preparation immediately before each execution attempt
4. add explicit reservation/freshness lifecycle and current fresh-auth proof; historical cookie remains forbidden
5. preserve immutable `PreparedAttempt` identity and cleanup/release/quarantine evidence
6. bind N5 Runtime readiness into durable N5 NodeDelivery/Runtime deterministic gate
7. keep Script Readiness business execution disabled; add N6 semantic implementation closure over Case steps/Oracle/runtime bindings/evidence collectors
8. bind N6 evaluated script truth into durable NodeDelivery + Director Gate
9. targeted Ubuntu + Windows + full-rc7 must remain green

## Do not repeat

- Do not redesign N1-N10.
- Do not change canonical L1-L7 meanings.
- Do not reintroduce L5 API Contract / L6 Capability / L7 E2E taxonomy.
- Do not route DATA/PRECONDITION/AUTH back to Script Readiness.
- Do not downgrade Bank Field `NOT_VERIFIED`.
