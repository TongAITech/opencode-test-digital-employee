# RC8 Current Handoff

Repository: `TongAITech/opencode-test-digital-employee`
Branch: `work/rc8`
Base: `delivery/rc7-default-enhancements@2c2eecbf18dde97ecdb10b65264e8c5c2a88ef72`
Current wave: `W0 - Truth & Identity Foundation`

## Do not re-plan
RC8 architecture/product direction is frozen by:
- `docs/rc8/RC8-MASTER-CONTRACT.md`
- `docs/rc8/RC8-ARCHITECTURE-BASELINE.md`
- `docs/rc8/RC8-PRODUCT-BASELINE.md`
- `docs/rc8/RC7-TO-RC8-GAP-MATRIX.md`
- `docs/rc8/RC8-REQUIREMENT-TRACEABILITY-MATRIX.md`
- `docs/rc8/RC8-IMPLEMENTATION-STATUS.md`

New sessions must read these files and verify current Git HEAD before editing. Git/HEAD + R1 runtime truth + evidence are authoritative; chat memory is not.

## Key frozen constraints
- preserve RC7 verified execution capabilities; adapter/migrate rather than rewrite by default;
- single node must support full functional loop;
- Center supports multi-node sharing but multi-node is not required to run;
- Center owns durable TestRun/event/evidence/knowledge/skill state;
- node package is downloadable from Center and includes frozen redistributable RC7 offline toolset;
- Windows uses Git Bash; Xinchuang Linux uses bash;
- skills are centrally distributed; knowledge is centrally durable and task-scoped;
- business-flow capture includes human steps, API order, data/auth/state dependencies and replay verification;
- node artifacts (screenshots/data/scripts/skills/knowledge/etc.) use Node Agent artifact sync, not direct DB writes;
- product is Chinese-first, Apple-inspired, simple/clear/spacious and must explain what was tested without DSH logs;
- test-data sensitivity governance is not a delivery blocker; test-data lifecycle is.

## RC7 certification carried forward
- Reality Certification CLOSED
- RC8_ENTRY_READY=YES
- not FULLY_AUTONOMOUS_TEST_COMPLETE
- L1/L2/L3 READY
- L4/L5/L7 PARTIAL
- L6 BASELINE_ONLY
- Completion TEST_PARTIALLY_EXECUTED
- Release HOLD
- 16 canonical gaps from 49 raw gaps

## Completed in this handoff
- RC8 branch created from latest selected RC7 enhancement lineage.
- Core design contract/baseline files prepared for first commit.

## Next unique construction entry
Continue W0; do not jump directly to broad UI or multi-node scheduling.
1. Locate/import the final RC7 `capability-cert/final` artifact descriptions for `GAP-ADD-03`, `GAP-ADD-06`, `GAP-ADD-10` and individual canonical severities without guessing.
2. Define RC8 canonical identity/event/evidence schema in code.
3. Add tests proving plan != runtime truth and evidence provenance/assertion binding.
4. Define capability qualification state machine.
5. Define ProductionBatch/RequirementDeliveryScope/TestRun/WorkItem/Node identities.
6. Then enter W1 single-node vertical slice.

## Prohibited shortcuts
- do not claim implementation or PASS from prompts/docs alone;
- do not treat plugin installation as verified capability;
- do not let Director/model output create execution truth;
- do not make Session authoritative;
- do not build all product pages before the first single-node truthful vertical slice is working;
- do not simplify away requirements in the Traceability Matrix.
