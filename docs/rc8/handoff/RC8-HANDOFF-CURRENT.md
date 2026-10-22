# RC8 Current Handoff

Repository: `TongAITech/opencode-test-digital-employee`
Branch: `work/rc8`
RC7 source/capability base: `delivery/rc7-default-enhancements@2c2eecbf18dde97ecdb10b65264e8c5c2a88ef72`
RC7 transport/toolset reference: `delivery/rc7-internal-transport-0bbb8239@af59027e7227fa1861fea95c6d05ff73aefb8572`

## Current truth

The project has been re-baselined to prevent tool-level success from being promoted into testing-capability completion.

Scoped status:
- `TOOL:MAVEN_JUNIT = BANK_REALITY_VERIFIED`
- `TOOL:CODEGRAPH = BANK_REALITY_VERIFIED`
- `STAGE:CODE_ANALYSIS = PARTIAL / FULL_BANK_ANALYSIS_PENDING`
- `LAYER:L1 = AUTONOMOUS_CLOSED_LOOP_NOT_IMPLEMENTED`
- `LAYER:L2..L7 = RC8_AUTONOMOUS_CLOSED_LOOP_NOT_IMPLEMENTED`
- `MISSION:TEST_SUFFICIENT = NO`
- `RELEASE = HOLD`

Do not infer any broader PASS from the two verified tool capabilities.

## Mandatory design set - read before any code change

Upper baselines:
- `docs/rc8/RC8-MASTER-CONTRACT.md`
- `docs/rc8/RC8-ARCHITECTURE-BASELINE.md`
- `docs/rc8/RC8-PRODUCT-BASELINE.md`
- `docs/rc8/RC7-TO-RC8-GAP-MATRIX.md`
- `docs/rc8/RC8-NO-DISCOUNT-DELIVERY-CONTRACT.md`

Construction-grade frozen contracts:
- `docs/rc8/RC8-IMPLEMENTATION-BLUEPRINT-v2.md`
- `docs/rc8/RC8-CAPABILITY-CLOSURE-MATRIX.md`
- `docs/rc8/RC8-L1-L7-ACCEPTANCE-CONTRACT.md`
- `docs/rc8/RC8-MISSION-GRAPH-CONTRACT.md`
- `docs/rc8/RC8-PRODUCT-PROJECTION-MAP.md`
- `docs/rc8/RC8-RC7-REGRESSION-CATALOG.md`
- `docs/rc8/RC8-WAVE-DELIVERY-GATES.md`
- `docs/rc8/RC8-REQUIREMENT-TRACEABILITY-MATRIX.md`
- `docs/rc8/RC8-IMPLEMENTATION-STATUS.md`

New sessions MUST verify current Git HEAD/CI and read the above set before editing. Git/HEAD + R1 + target-bank evidence are authoritative; chat/session memory is not.

## Core no-discount rule

Every implementation slice has four independent closure lines:
1. Architecture
2. Testing Intelligence / Autonomous Loop
3. Product Projection / UX
4. Reality / Deployment

Missing any applicable line -> `PARTIAL`/`IMPLEMENTED`, never `CLOSED`.

Status levels are independent:
- TOOL
- STAGE
- LAYER
- MISSION
- RELEASE

Forbidden promotions include:
- Maven/JUnit green != L1 sufficient
- CodeGraph verified != Code Analysis sufficient
- Browser action success != L4 sufficient
- all WorkItems completed != TEST_SUFFICIENT
- product defect fail != testing mission failure

## Existing reusable foundation

Keep and reuse; do not rewrite:
- W0 identity/truth contracts
- R1 runtime-only truth
- Center/Node registration/heartbeat/capability/lease foundations
- Artifact Sync with hash/AVAILABLE semantics
- Maven/JUnit real execution adapter and bank Reality fixes
- CodeGraph real snapshot/query/evidence adapter and bank Reality proof
- Node shell/platform groundwork
- DSH semantic code-analysis worker under construction

These are dependencies of the next vertical slice, not substitutes for it.

## Why the previous breadth-first sequence is cancelled

The old sequence `Maven -> CodeGraph -> Browser -> 4A -> DB -> ...` risks producing a verified tool box without an autonomous tester.

Do not continue breadth-first capability collection as the main construction path.

## Current unique next functional target

`W-A Mission Kernel prerequisites + W-B First Autonomous L1 Vertical Slice`.

The first real slice must implement and prove:

Requirement/Code Risk
-> Test Design
-> ExecutableSpec
-> Script Build/Validation
-> Preconditions/Test Data
-> Real Maven/JUnit/pytest execution
-> JaCoCo/coverage.py
-> Changed Method/Line/Branch Mapping
-> Requirement/Risk/VP/Oracle Coverage
-> Failure Classification
-> durable Gap
-> Delta Test Design
-> Delta Script
-> Targeted Re-execution
-> Coverage Recalculation
-> L1 Sufficiency
-> Convergence
-> Product Projection
-> Bank Reality.

Mandatory proof: Attempt 1 must expose at least one real insufficiency/gap and the system must route/repair/re-run. A one-shot green run does not prove autonomous closure.

## Mission-kernel prerequisites that must be built with the slice

- scoped TOOL/STAGE/LAYER/MISSION/RELEASE status model
- durable MissionGraph/StageInstance
- append-only Attempt
- Gap domain/router
- Dependency/Invalidation
- Sufficiency Evaluator contract/registry
- Convergence Controller
- product projections for TestRun/Attempt/Coverage/Gap

Do not build these as abstract framework for months; implement them through the real L1 slice.

## Product requirement for the first slice

At minimum the real product UI/API must expose:
- 测试任务: Mission Graph/current stage/Attempts
- 测试用例: Risk/VP/precondition/data/steps/Expected/Oracle/script/Attempts
- Coverage: changed methods/lines/branches + uncovered items
- Gap: source/evidence/route/repair/closure
- AI闭环: Attempt1 -> gap -> delta -> Attempt2 -> convergence
- 测试报告: tested/not-tested/coverage/defects/gaps/sufficiency/release

If understanding the slice requires DSH logs, Product Gate fails.

## Permanent RC7 regression input

All `RC7-REG-*` scenarios in `RC8-RC7-REGRESSION-CATALOG.md` remain mandatory. Especially protect against:
- Director self-execution
- session/context loss
- stale 4A cookie/manual fallback
- guessed routes/404
- CodeGraph not invoked/stale evidence
- Maven false block/stale Surefire
- JUnit green mistaken for L1 sufficient
- missing JaCoCo/coverage loop
- weak preconditions/test data
- L4 zero-step/awaiting-worker fake PASS
- fragmented L5 fake E2E
- L6 NFR ambiguity
- L7 scanner-all-blocked mistake
- product/runtime projection drift
- knowledge loss across sessions
- gap route-back/invalidation failure

## Packaging rule

Bank handoffs are always complete standalone packages, never patch-only.
Node identity/runtime state is outside version package and survives upgrade.
Final platform target remains Windows Git Bash + Xinchuang Linux bash with capability-based platform adapters.

## Authoritative input hold

Exact final wording/severity for `GAP-ADD-03`, `GAP-ADD-06`, `GAP-ADD-10` remains unavailable in Git. Keep `OPEN_INPUT`; never invent it.

## Next action after design review approval

Begin implementation at `W-A/W-B`, not BrowserSkill.
The first commit should introduce the Mission/Attempt/Gap/Sufficiency domain contracts needed by the L1 vertical slice, immediately followed by JaCoCo/change-coverage and closed-loop execution behavior. Every code commit must update the Capability Closure Matrix/RTM evidence rather than claiming broad PASS.