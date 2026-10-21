# RC8 Implementation Status

Branch: `work/rc8`
RC7 source/capability base: `delivery/rc7-default-enhancements@2c2eecbf18dde97ecdb10b65264e8c5c2a88ef72`
RC7 verified transport/toolset reference: `delivery/rc7-internal-transport-0bbb8239@af59027e7227fa1861fea95c6d05ff73aefb8572`
Current verified code HEAD before this status update: `21dc97a3bcfe7445aa9c7faffdf7b9bc9379f2cc`
Current wave: `W0 - Truth & Identity Foundation`
Overall status: `IN_PROGRESS`

## Frozen inputs
- `docs/rc8/RC8-MASTER-CONTRACT.md`
- `docs/rc8/RC8-ARCHITECTURE-BASELINE.md`
- `docs/rc8/RC8-PRODUCT-BASELINE.md`
- `docs/rc8/RC7-TO-RC8-GAP-MATRIX.md`
- `docs/rc8/RC8-REQUIREMENT-TRACEABILITY-MATRIX.md`
- `docs/rc8/RC8-W1-SINGLE-NODE-VERTICAL-SLICE.md`
- `packaging/rc8/RC7_OFFLINE_TOOLSET_MANIFEST.json`

## RC7 inheritance baseline
RC8 intentionally uses two RC7 authorities for different purposes:
1. **source/capability lineage**: `2c2eecb`, newer default enhancements and 90 commits ahead of `work/rc7-field-hardening@33433c8` on that lineage;
2. **offline transport completeness reference**: `af59027`, the verified full internal-transport publication branch derived from `0bbb8239` and containing transport/package-specific commits that are not on `2c2eecb`.

Do not replace this with a false either/or choice. RC8 capability code migrates from the newer source line while the node offline package is checked against the verified transport toolset manifest/reference.

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
Lock foundations that would otherwise contaminate every later layer:
1. canonical execution identities/provenance;
2. runtime vs plan truth boundary;
3. evidence reference contract;
4. capability qualification contract;
5. completion/release semantics;
6. production/requirement/delivery-scope identity model;
7. central TestRun/WorkItem/Node identity contract;
8. central R1 append/idempotency/replay boundary.

## W0 work items
| Work item | Description | Status | Current proof |
|---|---|---|---|
| RC8-W0-01 | Freeze Master Contract and design/product/gap/requirement baselines | IMPLEMENTED | `d2166529` |
| RC8-W0-02 | Import final RC7 capability-cert exact descriptions/severity for GAP-ADD-03/06/10 | OPEN_INPUT | not present in current Git tree/search; do not guess |
| RC8-W0-03 | Define canonical RC8 identity/event/evidence schemas | IMPLEMENTED | `rc8_runtime/contracts.py`, CI run 39624034428/39624713143 |
| RC8-W0-04 | Enforce truth boundary: plan != runtime; central R1 idempotent replay | IMPLEMENTED | `rc8_runtime/r1_runtime.py`, `tests/test_rc8_r1_runtime.py` |
| RC8-W0-05 | Evidence provenance/assertion-binding contracts/tests | IMPLEMENTED | `EvidenceManifest`, `require_pass_evidence` |
| RC8-W0-06 | Capability qualification state machine contract/tests | IMPLEMENTED | `CapabilityQualification`, transition tests |
| RC8-W0-07 | Completion semantics tests (`PLAN_COMPLETE != TEST_SUFFICIENT`) | IMPLEMENTED | `CompletionClaim` tests |
| RC8-W0-08 | Define ProductionBatch/Requirement/DeliveryScope domain model | IMPLEMENTED | RC8 contracts + multi-scope test |
| RC8-W0-09 | Define TestRun/WorkItem/Node durable identity model | IMPLEMENTED | session-independent identity contracts |
| RC8-W0-10 | Establish first single-node vertical-slice contract | IMPLEMENTED | `RC8-W1-SINGLE-NODE-VERTICAL-SLICE.md` |

`IMPLEMENTED` does not mean bank reality verified. W0 code gates currently prove deterministic contracts in CI. W1+ bank/node reality evidence is still required before closure.

## W0 CI
- Run `39624034428` for `392a9203`: SUCCESS on Ubuntu and Windows, Python 3.8, bash shell.
- Run `39624713143` for `21dc97a3`: SUCCESS on Ubuntu and Windows, Python 3.8, bash shell; includes central R1 tests.

## RC7 offline toolset freeze
`packaging/rc8/RC7_OFFLINE_TOOLSET_MANIFEST.json` records the source/transport dual authority and the frozen capability/tool categories, including Node/JDK/Maven/offline Maven repo, Python test/document stack, local OCR/CV, Playwright/GitNexus, CodeGraph, browser/BrowserSkill, Allure, k6, ZAP, ripgrep and required/optional DSH plugins. Presence never equals capability VERIFIED.

## W1 target
`W1 - Center + Single Node`
Prove one Center + one Windows Git Bash DSH Node can register, qualify a real capability, receive/lease one WorkItem, execute one real RC7 capability, append canonical R1 runtime events, upload assertion-bound evidence and display truthful Chinese product state.

The first slice is defined in `docs/rc8/RC8-W1-SINGLE-NODE-VERTICAL-SLICE.md`.

## W0-02 handling
Exact final text for `GAP-ADD-03`, `GAP-ADD-06`, `GAP-ADD-10` was not found in current repository search/tree and must not be fabricated. This is a traceability-import hold, not permission to discard those gaps. It blocks final canonical-gap closure, but does not block W1 implementation of already-known foundational requirements.

## Gate policy
Do not expand to broad multi-node scheduling or all product pages before the W1 single-node vertical slice is reality-verified.

## Status semantics
- OPEN / OPEN_INPUT: no implementation proof or required authoritative input unavailable
- IMPLEMENTED: code/design exists and automated gates pass where listed
- REALITY_VERIFIED: real execution/evidence proves behavior
- CLOSED: requirement/gap trace complete and no remaining acceptance blocker

Latest HEAD must always be re-checked before handoff claims. A previous green commit cannot describe a newer red HEAD as PASS.
