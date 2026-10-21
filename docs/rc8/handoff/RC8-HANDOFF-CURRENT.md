# RC8 Current Handoff

Repository: `TongAITech/opencode-test-digital-employee`
Branch: `work/rc8`
RC7 source/capability base: `delivery/rc7-default-enhancements@2c2eecbf18dde97ecdb10b65264e8c5c2a88ef72`
RC7 transport/toolset reference: `delivery/rc7-internal-transport-0bbb8239@af59027e7227fa1861fea95c6d05ff73aefb8572`
Current verified code HEAD before this handoff update: `21dc97a3bcfe7445aa9c7faffdf7b9bc9379f2cc`
Current wave: `W0 -> W1 entry`

## Do not re-plan
RC8 direction is frozen by:
- `docs/rc8/RC8-MASTER-CONTRACT.md`
- `docs/rc8/RC8-ARCHITECTURE-BASELINE.md`
- `docs/rc8/RC8-PRODUCT-BASELINE.md`
- `docs/rc8/RC7-TO-RC8-GAP-MATRIX.md`
- `docs/rc8/RC8-REQUIREMENT-TRACEABILITY-MATRIX.md`
- `docs/rc8/RC8-IMPLEMENTATION-STATUS.md`
- `docs/rc8/RC8-W1-SINGLE-NODE-VERTICAL-SLICE.md`
- `packaging/rc8/RC7_OFFLINE_TOOLSET_MANIFEST.json`

New sessions must read these files and verify current Git HEAD before editing. Git/HEAD + R1 runtime truth + evidence are authoritative; chat memory is not.

## Implemented so far
1. RC8 master/architecture/product/gap/traceability baselines.
2. RC8 identity contracts for Node, ProductionBatch, RequirementDeliveryScope, TestRun and WorkItem.
3. Separate plan/runtime event envelopes; runtime producer is Node Agent/Worker/Tool, not Director/model claim.
4. EvidenceManifest with hash/provenance/availability/assertion/runtime-event binding.
5. Capability qualification state machine where VERIFIED requires real probe/evidence/time.
6. Completion contract where plan completion does not imply test sufficiency.
7. Central R1 runtime ledger boundary:
   - runtime-only append;
   - plan rejection;
   - event-id idempotency/conflict fail-closed;
   - deterministic replay;
   - per-node sequence/stale check.
8. Windows/Ubuntu Python 3.8 + bash CI gates.
9. W1 single-node vertical slice acceptance contract.
10. RC7 offline toolset dual-source freeze: newer capability source line + verified transport/toolset reference line.

## CI truth
- `392a9203` -> workflow run `39624034428` SUCCESS (Ubuntu + Windows).
- `21dc97a3` -> workflow run `39624713143` SUCCESS (Ubuntu + Windows), including R1 tests.

These are automated contract gates, not bank reality certification.

## RC7 transport inheritance note
Do not assume `2c2eecb` alone contains every transport-only commit. `af59027` is on a diverged internal-transport line from merge base `0bbb8239`. RC8 must preserve newer source/capability changes from `2c2eecb` while checking node offline payload completeness against the transport line/manifest.

## One authoritative-input hold
Exact final certification wording/severity for `GAP-ADD-03`, `GAP-ADD-06`, `GAP-ADD-10` was not found in current Git tree/search. Keep them OPEN_INPUT; do not guess. This blocks final RC7-gap certification closure but does not block W1 construction.

## Next unique construction entry
Enter W1; do not broaden to multi-node or all pages.
1. Implement Center-side Node Registry + heartbeat + capability projection using durable interfaces.
2. Implement Node Agent registration/heartbeat client and canonical `rc8-node.sh` entrypoint compatible with Windows Git Bash and Linux bash.
3. Implement WorkItem lease contract/service tied to `TestRunIdentity`, not Session.
4. Connect Node runtime events to `CentralR1RuntimeLedger` through the Center service boundary.
5. Build Artifact Sync minimum path: manifest -> upload -> hash verify -> AVAILABLE.
6. Adapt one real RC7 capability behind the Node Agent; no fake tool.
7. Build only two first product sample surfaces: `测试任务` and `执行节点`.
8. Reality-test the full single-node chain before expanding.

## Prohibited shortcuts
- no claim of REALITY_VERIFIED from CI/unit tests alone;
- no direct DSH/tool write to Center DB;
- no plugin-installed => VERIFIED shortcut;
- no Director/model-generated execution truth;
- no Session authority;
- no PASS without AVAILABLE assertion-bound evidence;
- no broad multi-node scheduling before single-node slice passes;
- no building all product pages before sample surfaces are accepted;
- no dropping requirements/gaps because architecture is harder;
- no RC8 node package that silently omits transport-only RC7 offline capabilities.
