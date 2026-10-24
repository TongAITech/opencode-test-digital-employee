# RC7.1 Autonomous Loop Implementation Status

## Contract

- Contract ID: `RC-AUTONOMOUS-TEST-LOOP`
- Contract Version: `1.0.0`
- Accepted Starting SHA: `98d7ee59cb3caf760177d7aaa933ee70082a6ff3`
- Construction Branch: `work/rc7.1-autonomous-loop`
- Engineering-verified Wave A implementation HEAD: `bf8badf3dc687eba3a2d092174ff1a31706f4ba1`
- Engineering-verified Wave B implementation HEAD: `4ad0d32eb009e870760db185bb8f5975705fdd5d`
- Engineering-verified Wave C implementation HEAD: `65f5340c9b88ecaacc472fca0d30f16f194249b7`
- Engineering-verified Wave D implementation HEAD: `9b02163435af49ddde704578a7c5d66b0a5939e4`

## Reality boundary

- Controlled Engineering: PASS for Waves A-D
- Wave A validation run: `40071040146` (#72): Ubuntu targeted PASS / Windows targeted PASS / full-rc7 PASS
- Wave B validation run: `40077002904` (#79): Ubuntu targeted PASS / Windows targeted PASS / full-rc7 PASS
- Wave C validation run: `40077581353` (#82): Ubuntu targeted PASS / Windows targeted PASS / full-rc7 PASS
- Wave D validation run: `40078256565` (#86): Ubuntu targeted PASS / Windows targeted PASS / full-rc7 PASS
- Bank Field Reality: `NOT_VERIFIED`

Controlled Engineering PASS MUST NOT be reported as Bank Field Reality PASS.

## Waves

| Wave | Scope | Status |
|---|---|---|
| A | Foundation registries/contracts/router/events/durable node control/coverage ledger | ENGINEERING_VERIFIED |
| B | N1-N4 autonomous node adoption | ENGINEERING_VERIFIED |
| C | N5-N6 preparation/script closure | ENGINEERING_VERIFIED |
| D | N7 coverage-driven execution closure | ENGINEERING_VERIFIED |
| E | N8-N9 recovery/defect closure | IN_PROGRESS |
| F | N10 mission convergence/reporting | NOT_STARTED |

## Wave D delivered

- Versioned/frozen `CoverageDenominatorSnapshot` is persisted as current Runtime truth per layer/target.
- Denominator shrink is forbidden; expansion creates a new version, emits `LAYER_DENOMINATOR_EXPANDED` / `LAYER_REOPENED`, and invalidates stale receipts.
- `CoverageLedger` reconciles evidence-backed obligation states; `COVERED_FAIL` counts as coverage closure while Product Quality remains separate.
- Exact uncovered obligations create durable coverage gaps routed to Requirement / Code / Test Design / N5 Preparation / N6 Script / N7 Execution / N8 Diagnosis as appropriate.
- PRODUCT Oracle failures are not turned into coverage gaps; they remain `COVERED_FAIL` and flow through quality/defect handling.
- Delta plans contain only open obligations and explicitly forbid re-running already closed obligations by default.
- Canonical L1-L7 metric contracts are enforced, including L1 line=100% + logic=100%.
- N7 final readiness requires current READY receipts for all seven canonical layers; missing or stale layer receipts fail closed.
- Downstream discovery can expand an upstream denominator and reopen N7 along the existing durable iteration lineage.
- N7 Runtime coordinator task state transitions use append-only R1 entity versions (`READY@v1 -> PASS@v2 -> READY@v3 -> ...`), preserving history instead of overwriting Runtime truth.
- Final logical N7 PASS remains Director-gated after Runtime coverage authority publishes NodeDelivery.

## GAP status after Waves A-D

- `RC71-AL-001` ENGINEERING_VERIFIED
- `RC71-AL-002` ENGINEERING_VERIFIED
- `RC71-AL-003` ENGINEERING_VERIFIED
- `RC71-AL-004` ENGINEERING_VERIFIED
- `RC71-AL-005` ENGINEERING_VERIFIED
- `RC71-AL-006` ENGINEERING_VERIFIED
- `RC71-AL-007` ENGINEERING_VERIFIED
- `RC71-AL-008` ENGINEERING_VERIFIED at controlled-engineering level; Bank Field fresh-4A reality remains NOT_VERIFIED
- `RC71-AL-017` N1-N7 adoption ENGINEERING_VERIFIED; N8-N10 continues in Waves E-F
- `RC71-AL-018` registry + N1-N7 events ENGINEERING_VERIFIED; later node-specific events continue in Waves E-F
- `RC71-AL-019` existing AgentTeams path ENGINEERING_VERIFIED; Bank Field still NOT_VERIFIED
- `RC71-AL-009/010/011/012/013` remain Wave E
- `RC71-AL-014/015/016` remain Wave F
- `RC71-AL-020` remains OPEN until real bank-field evidence exists

## Next exact work item — Wave E N8-N9

### N8
1. preserve existing Runtime diagnosis and narrow direct-retry controller
2. add durable non-direct `RepairWorkOrder` / `RepairReceipt` orchestration
3. N8 orchestrates; original owner node performs repair; N8 must not mutate upstream artifacts directly
4. DATA/PRECONDITION/AUTH -> N5, SCRIPT -> N6, SPEC/ORACLE -> N4, route-source truth -> N3, UNKNOWN -> evidence expansion, PRODUCT -> N9
5. same Failure Signature + same strategy + no delta must stop/escalate; no blind retry
6. every recovery verification requires a new successor attempt and real re-execution
7. publish N8 `FailureRecoveryPackage` / NodeDelivery only on evidence-backed RECOVERED / DEFECT_HANDOFF_READY / explicit BLOCKED terminal outcome

### N9
1. preserve current PRODUCT qualification/reproduction gates
2. add durable `DefectSignature` and evidence-backed duplicate/possible-duplicate decision
3. derive severity from deterministic impact policy instead of default HIGH
4. add RCA level/evidence chain without requiring confirmed code root cause to file a proven defect
5. preserve fix verification + impact regression before CLOSED
6. publish N9 DefectDeliveryPackage / node closure truth

Both N8 and N9 must keep targeted Ubuntu + Windows + full-rc7 green.

## Do not repeat

- Do not redesign N1-N10.
- Do not change canonical L1-L7 meanings.
- Do not reintroduce L5 API Contract / L6 Capability / L7 E2E taxonomy.
- Do not route DATA/PRECONDITION/AUTH back to Script Readiness.
- Coverage closure is not Product Quality PASS.
- Assertion failure is not PRODUCT.
- UNKNOWN failure cannot be blindly retried.
- Do not downgrade Bank Field `NOT_VERIFIED`.
