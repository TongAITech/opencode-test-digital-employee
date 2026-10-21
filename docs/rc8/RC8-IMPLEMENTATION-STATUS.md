# RC8 Implementation Status

Branch: `work/rc8`
RC7 base: `2c2eecbf18dde97ecdb10b65264e8c5c2a88ef72`
Current wave: `W0 - Truth & Identity Foundation`
Overall status: `IN_PROGRESS`

## Frozen inputs
- `docs/rc8/RC8-MASTER-CONTRACT.md`
- `docs/rc8/RC8-ARCHITECTURE-BASELINE.md`
- `docs/rc8/RC8-PRODUCT-BASELINE.md`
- `docs/rc8/RC7-TO-RC8-GAP-MATRIX.md`
- `docs/rc8/RC8-REQUIREMENT-TRACEABILITY-MATRIX.md`

## RC7 inheritance baseline
Latest construction base selected for RC8 is `delivery/rc7-default-enhancements@2c2eecb`, which is 90 commits ahead of `work/rc7-field-hardening@33433c8` and contains that field-hardening lineage.

RC7 certification facts carried into RC8:
- Reality Certification CLOSED
- RC8_ENTRY_READY=YES
- not FULLY_AUTONOMOUS_TEST_COMPLETE
- L1/L2/L3 READY
- L4/L5/L7 PARTIAL
- L6 BASELINE_ONLY
- TEST_PARTIALLY_EXECUTED
- Release HOLD
- 49 raw gaps -> 16 canonical gaps

## W0 objective
Before broad architecture/product expansion, lock the truths that would otherwise contaminate everything downstream:
1. canonical execution identities/provenance;
2. runtime vs plan truth boundary;
3. evidence reference contract;
4. capability qualification contract;
5. completion/release semantics;
6. production/requirement/delivery-scope identity model;
7. initial central TestRun/Node identity contract.

## W0 work items
| Work item | Description | Status |
|---|---|---|
| RC8-W0-01 | Freeze Master Contract and design/product/gap/requirement baselines | IMPLEMENTED |
| RC8-W0-02 | Import final RC7 capability-cert canonical gap descriptions/severity verbatim | OPEN |
| RC8-W0-03 | Define canonical RC8 identity/event/evidence schemas | OPEN |
| RC8-W0-04 | Add truth-boundary tests: plan != runtime | OPEN |
| RC8-W0-05 | Add evidence provenance/assertion-binding tests | OPEN |
| RC8-W0-06 | Add capability qualification state machine contract/tests | OPEN |
| RC8-W0-07 | Add completion semantics tests (`PLAN_COMPLETE != TEST_SUFFICIENT`) | OPEN |
| RC8-W0-08 | Define ProductionBatch/Requirement/DeliveryScope domain model | OPEN |
| RC8-W0-09 | Define TestRun/WorkItem/Node durable identity model | OPEN |
| RC8-W0-10 | Establish first single-node vertical-slice test plan | OPEN |

## W1 target
`W1 - Center + Single Node`
Prove one Center + one Windows Git Bash DSH node can register, qualify capability, receive/lease one WorkItem, execute one real RC7 capability, upload event/evidence and display truthful state.

## Gate policy
Do not expand to broad multi-node scheduling or all product pages before the W1 single-node vertical slice is reality-verified.

## Status semantics
- OPEN: no implementation proof
- IMPLEMENTED: code/design exists but reality gate not yet proven
- REALITY_VERIFIED: real execution/evidence proves behavior
- CLOSED: requirement/gap trace complete and no remaining acceptance blocker

Latest HEAD must be re-checked before any handoff claims. A previous green commit cannot be used to describe a newer red HEAD as PASS.
