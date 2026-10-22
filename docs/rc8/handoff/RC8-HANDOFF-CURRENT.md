# RC8 Current Handoff

Repository: `TongAITech/opencode-test-digital-employee`
Branch: `work/rc8`
RC7 source/capability base: `delivery/rc7-default-enhancements@2c2eecbf18dde97ecdb10b65264e8c5c2a88ef72`
RC7 transport/toolset reference: `delivery/rc7-internal-transport-0bbb8239@af59027e7227fa1861fea95c6d05ff73aefb8572`
Latest CI-verified CodeGraph code HEAD: `3577614c99129a70dd507f62bc213f0c06a6deae`
Latest CI proof: workflow run `39736447374` SUCCESS on Ubuntu + Windows.
Current wave: `W1 - Center + Single Node Reality Gate`
Current unique next gate: `CodeGraph BANK_REALITY_VERIFICATION`.

## Do not re-plan
Read and obey:
- `docs/rc8/RC8-MASTER-CONTRACT.md`
- `docs/rc8/RC8-ARCHITECTURE-BASELINE.md`
- `docs/rc8/RC8-PRODUCT-BASELINE.md`
- `docs/rc8/RC7-TO-RC8-GAP-MATRIX.md`
- `docs/rc8/RC8-REQUIREMENT-TRACEABILITY-MATRIX.md`
- `docs/rc8/RC8-IMPLEMENTATION-STATUS.md`
- `docs/rc8/RC8-W1-SINGLE-NODE-VERTICAL-SLICE.md`
- `docs/rc8/RC8-CODEGRAPH-REALITY-RUNBOOK.md`
- `packaging/rc8/RC7_OFFLINE_TOOLSET_MANIFEST.json`

New sessions verify current Git HEAD and newest CI before editing. Git/HEAD + target-bank R1 + evidence are authoritative; chat memory is not.

## Foundation already implemented
- durable Center/Node/TestRun/WorkItem identity; no Session authority
- Node registration/heartbeat/capability qualification
- Node-owned WorkItem leases
- R1 runtime-only truth with idempotency/conflict/replay gates
- Artifact Sync with resumable upload, hash verification and AVAILABLE state
- restart-persistent W1 fallback state
- Windows Git Bash + Linux bash launchers
- plan/runtime separation and evidence-before-PASS gates

## Maven/JUnit status
`maven-junit = BANK_REALITY_VERIFIED` for the tested bank chain.

Target-bank acceptance run supplied in the validation session proved:
- real Windows Git Bash node
- real bank Maven + real `cfg-center`
- fresh Surefire/JUnit evidence
- `tests=2243`, `failures=0`, `errors=0`, `skipped=8`
- `execution_passed=true`
- capability VERIFIED
- R1 `PERSISTENCE_VERIFIED`
- execution WorkItem COMPLETED
- reality status `EXECUTION_CHAIN_VERIFIED`

Important boundary: pure disconnected/offline Maven portability is not yet proven because the successful run could use the internal Maven repository.

Closed bank-reality defects from Maven validation:
- Windows/GB18030 subprocess decoding crash
- stale historical Surefire XML contaminating current Actual
- zero-byte execution artifact handling
- real Center Artifact response mismatch hidden by mocks

## CodeGraph construction now implemented
New/updated paths:
- `rc8_node/codegraph.py`
- `rc8_node/reality_codegraph.py`
- `packaging/rc8/rc8-codegraph-reality.sh`
- `tests/test_rc8_codegraph_adapter.py`
- `tests/test_rc8_codegraph_reality_runner.py`
- `docs/rc8/RC8-CODEGRAPH-REALITY-RUNBOOK.md`
- `.github/workflows/rc8-wave1-control.yml`

Truth rules:
1. Git is the change/snapshot authority.
2. CodeGraph is structural enrichment only.
3. Java diff/working-tree change or explicit Java target is required.
4. Real query families required per selected point:
   - `codegraph_get_ai_context`
   - `codegraph_get_callers`
   - `codegraph_get_callees`
   - `codegraph_get_dependency_graph`
   - `codegraph_analyze_impact`
5. graph evidence binds current Git head, `snapshot_id`, changed Java files/query points and `graph_digest`.
6. repository snapshot is checked before query, after query and before R1 publication.
7. snapshot change => fail closed; stale graph may never be published as current truth.
8. any required structural query failure => fail closed; do not pretend failure means empty graph.
9. capability becomes VERIFIED only after real query evidence Artifact is AVAILABLE.
10. execution WorkItem writes `CODEGRAPH_GRAPH_EVIDENCE_RECORDED` only after graph evidence is accepted and snapshot remains fresh.

## CodeGraph CI truth
Code HEAD: `3577614c99129a70dd507f62bc213f0c06a6deae`
Run: `39736447374`
- Ubuntu SUCCESS
- Windows SUCCESS
- Python 3.8 compile PASS
- node/center/maven/codegraph shell entrypoint checks PASS
- CodeGraph snapshot gate PASS
- structural-query failure gate PASS
- Center -> Node -> qualification -> Artifact -> R1 -> WorkItem contract PASS

CI uses a clearly labelled contract double, so current state is:
`codegraph = IMPLEMENTED / CI_VERIFIED / BANK_REALITY_PENDING`.

## Unique next construction/acceptance action
Produce/use a complete standalone RC8 W1 package containing the current Maven + CodeGraph code; never deliver a patch-only package.

In bank environment run `packaging/rc8/rc8-codegraph-reality.sh` against:
- actual RC8 Center/Node
- actual CodeGraph executable
- actual Java repository
- actual Java change range or explicit Java target

Required bank PASS:
- capability evidence Artifact AVAILABLE
- capability state VERIFIED
- every required graph-only structural query succeeds
- source snapshot unchanged through publish
- execution graph Artifact AVAILABLE
- R1 receipt persistence verified
- WorkItem COMPLETED
- result retains `snapshot_id` + `graph_digest`

Only after that move CodeGraph to `BANK_REALITY_VERIFIED`.

## Do not do next
- do not start BrowserSkill before CodeGraph bank gate unless CodeGraph is genuinely blocked by environment;
- do not expand multi-node scheduling;
- do not build all 13 product pages;
- do not infer graph/call chains with the model when CodeGraph fails;
- do not use stale graph evidence from another snapshot;
- do not deliver a HOTFIX/patch package: every bank validation delivery is a complete standalone package.

## Later sequence
CodeGraph bank reality -> BrowserSkill -> 4A -> DB/Test Data -> full single-node business TestRun -> truthful sample pages (`测试任务`, `执行节点`) -> then multi-node/knowledge/skills/closed-loop expansion.

## Remaining authoritative-input hold
Exact final wording/severity for `GAP-ADD-03`, `GAP-ADD-06`, `GAP-ADD-10` remains unavailable in Git. Keep `OPEN_INPUT`; never fabricate it.
