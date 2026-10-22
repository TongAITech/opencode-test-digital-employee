# RC8 Implementation Status

Branch: `work/rc8`
RC7 source/capability base: `delivery/rc7-default-enhancements@2c2eecbf18dde97ecdb10b65264e8c5c2a88ef72`
RC7 verified transport/toolset reference: `delivery/rc7-internal-transport-0bbb8239@af59027e7227fa1861fea95c6d05ff73aefb8572`
Latest CI-verified code HEAD: `3577614c99129a70dd507f62bc213f0c06a6deae`
CI proof: workflow run `39736447374` = SUCCESS on Ubuntu + Windows.
Current wave: `W1 - Center + Single Node Reality Gate`
Overall status: `IN_PROGRESS / MAVEN_JUNIT_BANK_REALITY_VERIFIED / CODEGRAPH_CI_VERIFIED`

## Frozen inputs
- `docs/rc8/RC8-MASTER-CONTRACT.md`
- `docs/rc8/RC8-ARCHITECTURE-BASELINE.md`
- `docs/rc8/RC8-PRODUCT-BASELINE.md`
- `docs/rc8/RC7-TO-RC8-GAP-MATRIX.md`
- `docs/rc8/RC8-REQUIREMENT-TRACEABILITY-MATRIX.md`
- `docs/rc8/RC8-W1-SINGLE-NODE-VERTICAL-SLICE.md`
- `packaging/rc8/RC7_OFFLINE_TOOLSET_MANIFEST.json`

## RC7 inheritance baseline
RC8 intentionally keeps two RC7 authorities:
1. source/capability lineage: `2c2eecb`;
2. offline transport/toolset completeness reference: `af59027`.

Do not collapse these into one source. Capability code migrates from the newer source line while node offline payload completeness is checked against the verified transport line/manifest.

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

## W0 status
Implemented and CI-gated:
- canonical Node/TestRun/WorkItem/ProductionBatch/RequirementDeliveryScope identities;
- PLAN and RUNTIME planes separated;
- Director/model claims cannot create runtime truth;
- Evidence contract with hash/provenance/availability/assertion binding;
- capability qualification state machine; VERIFIED requires probe/evidence/time;
- `PLAN_COMPLETE != TEST_SUFFICIENT`;
- canonical R1 runtime ledger with idempotency/conflict/replay/node-sequence gates.

One authoritative-input hold remains: exact final certification wording/severity for `GAP-ADD-03`, `GAP-ADD-06`, `GAP-ADD-10` was not found in current Git sources. Keep `OPEN_INPUT`; never invent it.

## W1 control/runtime foundation
### Center
- Node registration/heartbeat
- capability projection/qualification
- WorkItem register/lease/start/complete
- lease ownership bound to Node, not DSH Session
- late runtime writes rejected after lease release
- central R1 append authorization
- stdlib HTTP transport boundary
- durable Center launcher and smoke check
- restart-persistent W1 fallback for Node/Capability/WorkItem/Artifact metadata

### Node Agent
- stable local Node identity across restart
- outbound-only Center connection
- register/heartbeat/capability/lease/start/runtime/complete clients
- Windows Git Bash + Linux bash launchers
- Windows Chinese/GB18030 output hardening where tool subprocesses require it

### Artifact Sync
- generic asset protocol for screenshots/logs/scripts/data/skill/knowledge attachments
- manifest -> resumable offset upload -> size/SHA-256 verify -> AVAILABLE
- active WorkItem lease required
- wrong Node rejected
- late completion after WorkItem completion rejected
- zero-byte artifacts supported
- metadata/bytes survive Center restart in the W1 durable fallback

## Maven/JUnit capability
### Implemented truth chain
- real `mvn -version` probe; presence alone never VERIFIED
- probe Artifact must reach AVAILABLE before capability VERIFIED
- real Maven subprocess execution
- Actual derives only from fresh Surefire/Failsafe XML plus Maven process result
- stale historical JUnit XML is ignored
- Windows Maven output tolerates UTF-8/GB18030/local encoding without crashing execution
- `maven_returncode != 0` cannot be hidden by green XML
- Actual/stdout/stderr/fresh JUnit XML are uploaded before R1
- WorkItem completes only after evidence and R1 persistence

### Bank Reality result
Target-bank validation supplied during the RC8 acceptance session proved:
- Windows Git Bash execution node
- actual bank Maven and actual `cfg-center` project
- main/test compile successful after the project test baseline was repaired by line-in DSH
- real JUnit/Surefire execution
- `tests=2243`, `failures=0`, `errors=0`, `skipped=8`
- fresh Surefire evidence used instead of stale reports
- `execution_passed=true`
- capability state `VERIFIED`
- R1 receipt `PERSISTENCE_VERIFIED`
- execution WorkItem `COMPLETED`
- final reality status `EXECUTION_CHAIN_VERIFIED`

Therefore `maven-junit` is now `BANK_REALITY_VERIFIED` for the tested bank environment and project chain.

Boundary: pure disconnected/offline portability is still a separate gate because this successful bank run allowed the internal Maven repository. Do not report `PURE_OFFLINE_PORTABILITY=PASS` yet.

## CodeGraph capability - current construction
Files:
- `rc8_node/codegraph.py`
- `rc8_node/reality_codegraph.py`
- `packaging/rc8/rc8-codegraph-reality.sh`
- `docs/rc8/RC8-CODEGRAPH-REALITY-RUNBOOK.md`

### Implemented gates
- Git remains the sole change/snapshot authority.
- CodeGraph is structural enrichment, never change truth.
- Java changes are discovered from committed diff plus working-tree Java changes; explicit target is allowed when required.
- no Java change/target => fail closed (`CODEGRAPH_JAVA_CHANGE_OR_TARGET_REQUIRED`).
- required real graph-only calls per query point:
  - `codegraph_get_ai_context`
  - `codegraph_get_callers`
  - `codegraph_get_callees`
  - `codegraph_get_dependency_graph`
  - `codegraph_analyze_impact`
- repository snapshot fingerprint includes Git HEAD, working-tree status digest, tracked diff digest and untracked Java content hashes.
- snapshot is checked before queries, after queries and immediately before R1 publication.
- stale source => `CODEGRAPH_SNAPSHOT_STALE` / `CODEGRAPH_SNAPSHOT_STALE_BEFORE_PUBLISH`.
- any required structural query failure => `CODEGRAPH_STRUCTURAL_QUERY_FAILED`; failed query is never silently converted to empty graph.
- capability evidence Artifact must be AVAILABLE before `codegraph` can become VERIFIED.
- execution graph evidence Artifact binds `snapshot_id` and `graph_digest`.
- R1 event `CODEGRAPH_GRAPH_EVIDENCE_RECORDED` binds Git head/base/head refs, changed Java files, query points, tool names/count, graph digest and Artifact ref.
- WorkItem completion occurs only after evidence and R1 persistence.

### CI truth
Latest CodeGraph code HEAD: `3577614c99129a70dd507f62bc213f0c06a6deae`
Workflow run: `39736447374`
- Ubuntu: SUCCESS
- Windows: SUCCESS
- Python 3.8
- CodeGraph launcher: PASS
- snapshot-stale regression: PASS
- structural-query failure regression: PASS
- full Center -> Node -> capability -> Artifact -> R1 -> WorkItem contract: PASS

CI uses an explicit CodeGraph contract double and therefore proves protocol/truth semantics only. It does NOT make the bank CodeGraph capability Reality Verified.

Current CodeGraph state: `IMPLEMENTED / CI_VERIFIED / BANK_REALITY_PENDING`.

## Current next gate
Do not start BrowserSkill or broad UI before CodeGraph bank validation.

Run `docs/rc8/RC8-CODEGRAPH-REALITY-RUNBOOK.md` with the actual bank CodeGraph executable against an actual Java change/snapshot. Required acceptance:
- real CodeGraph executable
- at least one Java query point
- all five structural query families succeed
- source snapshot remains unchanged through publication
- capability Artifact AVAILABLE -> capability VERIFIED
- execution graph Artifact AVAILABLE
- R1 `CODEGRAPH_GRAPH_EVIDENCE_RECORDED` persistence verified
- execution WorkItem COMPLETED

Only then may `codegraph` move to `BANK_REALITY_VERIFIED`.

After CodeGraph, continue the frozen capability order: BrowserSkill -> 4A -> DB/Test Data -> full single-node business TestRun. Build truthful product surfaces from real runtime data, not before it exists.

## Status semantics
- OPEN / OPEN_INPUT: no implementation proof or authoritative input unavailable
- IMPLEMENTED: code exists
- CI_VERIFIED: automated cross-platform gates pass
- REALITY_VERIFIED / BANK_REALITY_VERIFIED: target bank environment real execution/evidence proves behavior
- CLOSED: requirement/gap trace complete and no acceptance blocker

A code commit, installed plugin, process exit, model statement or CI contract double is never by itself bank Reality Verification.
