# RC7.1 Autonomous Loop Implementation Status

## Contract

- Contract ID: `RC-AUTONOMOUS-TEST-LOOP`
- Contract Version: `1.0.0`
- Accepted Starting SHA: `98d7ee59cb3caf760177d7aaa933ee70082a6ff3`
- Construction Branch: `work/rc7.1-autonomous-loop`
- Engineering-verified Wave A implementation HEAD: `bf8badf3dc687eba3a2d092174ff1a31706f4ba1`
- Engineering-verified Wave B implementation HEAD: `4ad0d32eb009e870760db185bb8f5975705fdd5d`
- Engineering-verified Wave C implementation HEAD: `65f5340c9b88ecaacc472fca0d30f16f194249b7`

## Reality boundary

- Controlled Engineering: PASS for Waves A-C
- Wave A validation run: `40071040146` (#72): Ubuntu targeted PASS / Windows targeted PASS / full-rc7 PASS
- Wave B validation run: `40077002904` (#79): Ubuntu targeted PASS / Windows targeted PASS / full-rc7 PASS
- Wave C validation run: `40077581353` (#82): Ubuntu targeted PASS / Windows targeted PASS / full-rc7 PASS
- Bank Field Reality: `NOT_VERIFIED`

Controlled Engineering PASS MUST NOT be reported as Bank Field Reality PASS.

## Waves

| Wave | Scope | Status |
|---|---|---|
| A | Foundation registries/contracts/router/events/durable node control/coverage ledger | ENGINEERING_VERIFIED |
| B | N1-N4 autonomous node adoption | ENGINEERING_VERIFIED |
| C | N5-N6 preparation/script closure | ENGINEERING_VERIFIED |
| D | N7 coverage-driven execution closure | IN_PROGRESS |
| E | N8-N9 recovery/defect closure | NOT_STARTED |
| F | N10 mission convergence/reporting | NOT_STARTED |

## Wave C delivered

### N5 Test Data / Preconditions

- Existing `PreparationRuntime` / `CaseRuntime` remain the real side-effect implementation; no duplicate preparation engine was introduced.
- Added Batch Preparation Plan as durable planning truth with `execution_proof=false`.
- Added durable resource reservation bound to the PreparedAttempt data-binding fingerprint.
- Added explicit pre-execution freshness evidence.
- Per-Case finalization requires the current immutable PreparedAttempt, exact frozen Case identity/hash, matching reservation and current freshness proof.
- AUTH preconditions require current same-attempt `PRECONDITION_EVIDENCE` whose source identifies fresh `foura-auth`; stale evidence is rejected.
- N5 Runtime readiness publishes a durable NodeDeliveryPackage; final logical node PASS remains Director-gated.

### N6 Script Build / Readiness

- Existing Runtime script readiness gate remains authoritative for compile/discovery/dependency and frozen Case/Oracle fingerprints.
- Added `ScriptImplementationMatrix` semantic closure over Case steps, Oracle refs, runtime bindings and evidence collectors.
- Missing/duplicate/unexpected semantic mappings create durable `SCRIPT_IMPLEMENTATION_COVERAGE_GAP` instead of script READY.
- N6 explicitly forbids business assertion execution during readiness.
- Complete technical + semantic readiness publishes N6 NodeDeliveryPackage; final node PASS remains Director-gated.

## GAP status after Waves A-C

- `RC71-AL-001` ENGINEERING_VERIFIED
- `RC71-AL-002` ENGINEERING_VERIFIED
- `RC71-AL-006` ENGINEERING_VERIFIED
- `RC71-AL-007` ENGINEERING_VERIFIED
- `RC71-AL-008` ENGINEERING_VERIFIED at controlled-engineering level for fresh-auth preparation gating; Bank Field remains NOT_VERIFIED
- `RC71-AL-017` N1-N6 adoption ENGINEERING_VERIFIED; N7-N10 continues in Waves D-F
- `RC71-AL-018` registry + N1-N6 events ENGINEERING_VERIFIED; later node-specific events continue in Waves D-F
- `RC71-AL-019` existing AgentTeams path ENGINEERING_VERIFIED; Bank Field still NOT_VERIFIED
- `RC71-AL-003/004/005` foundation exists; full N7 implementation is Wave D
- `RC71-AL-009/010/011/012/013` remain Wave E
- `RC71-AL-014/015/016` remain Wave F
- `RC71-AL-020` remains OPEN until real bank-field evidence exists

## Next exact work item — Wave D N7

1. persist versioned/frozen Layer Coverage denominators as current Runtime truth
2. reconcile real execution coverage evidence into `CoverageLedger`
3. preserve `COVERED_FAIL` as valid coverage while keeping Product Quality separate
4. emit exact uncovered Coverage obligations and route gaps to N2/N3/N4/N5/N6/N7/N8/N9 by cause
5. execute only delta obligations; do not full-restart closed coverage
6. denominator expansion invalidates stale LayerCoverageReceipt and reopens the affected layer
7. support cross-layer backward reopen when downstream evidence expands upstream scope
8. enforce L1 target line=100% and logic=100%, plus canonical L2-L7 obligation targets
9. publish N7 NodeDelivery only when all current layer contracts are closed
10. targeted Ubuntu + Windows + full-rc7 must remain green

## Do not repeat

- Do not redesign N1-N10.
- Do not change canonical L1-L7 meanings.
- Do not reintroduce L5 API Contract / L6 Capability / L7 E2E taxonomy.
- Do not route DATA/PRECONDITION/AUTH back to Script Readiness.
- Coverage closure is not Product Quality PASS.
- Do not downgrade Bank Field `NOT_VERIFIED`.
