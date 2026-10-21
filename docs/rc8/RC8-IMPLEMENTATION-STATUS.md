# RC8 Implementation Status

Branch: `work/rc8`
RC7 source/capability base: `delivery/rc7-default-enhancements@2c2eecbf18dde97ecdb10b65264e8c5c2a88ef72`
RC7 verified transport/toolset reference: `delivery/rc7-internal-transport-0bbb8239@af59027e7227fa1861fea95c6d05ff73aefb8572`
Latest CI-verified code HEAD: `b0f35a8a45e29e68d4ac0a3dc725e3b5104d7d80`
CI proof: workflow run `39696048518` = SUCCESS on Ubuntu + Windows, Python 3.8, bash/Git Bash compatible entrypoints.
Current wave: `W1 - Center + Single Node Vertical Slice`
Overall status: `IN_PROGRESS / CI_VERIFIED_NOT_BANK_REALITY_VERIFIED`

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
1. source/capability lineage: `2c2eecb`;
2. offline transport/toolset completeness reference: `af59027`.

Do not collapse these into one source. RC8 migrates capability code from the newer source line while node offline payload completeness is checked against the verified transport line/manifest.

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
W0 foundation contracts are implemented and CI-gated:
- canonical Node/TestRun/WorkItem/ProductionBatch/RequirementDeliveryScope identities;
- PLAN and RUNTIME planes separated;
- Director/model claim cannot create runtime truth;
- Evidence contract with hash/provenance/availability/assertion binding;
- capability qualification state machine; VERIFIED requires probe/evidence/time;
- `PLAN_COMPLETE != TEST_SUFFICIENT`;
- canonical R1 runtime ledger with idempotency/conflict/replay/node-sequence gates.

One authoritative-input hold remains: exact final certification wording/severity for `GAP-ADD-03`, `GAP-ADD-06`, `GAP-ADD-10` was not found in current Git sources. Keep `OPEN_INPUT`; never invent it.

## W1 implemented
### Center control plane
- Node registration and heartbeat
- capability projection/qualification
- WorkItem register/lease/start/complete
- lease ownership bound to Node, not DSH Session
- lease release on completion; late runtime writes rejected
- central R1 append authorization
- stdlib HTTP transport boundary
- durable Center launcher and smoke check
- restart-persistent local W1 fallback repository for Node/Capability/WorkItem/Artifact metadata

### Node Agent
- stable local Node identity across restart
- outbound-only Center connection
- register/heartbeat/capability/lease/start/runtime/complete clients
- canonical `packaging/rc8/rc8-node.sh`
- Windows Git Bash + Linux bash platform detection
- UTF-8 forced to avoid Windows Python/Chinese CLI codepage failure

### Artifact Sync
- generic asset protocol for screenshot/log/script/data/skill/knowledge attachments
- manifest -> resumable offset upload -> size/SHA-256 verify -> AVAILABLE
- active WorkItem lease required
- wrong Node rejected
- late completion after WorkItem completion rejected
- zero-byte artifacts supported and SHA-256 verified (important for empty Maven stderr logs)
- Artifact metadata and bytes survive Center restart in the W1 durable fallback

### First real capability adapter: Maven/JUnit
Capability qualification:
- runs actual local subprocess `mvn -version`
- success is PROBING, never immediate VERIFIED
- probe evidence persisted and SHA-256 hashed
- probe evidence must reach Center/Artifact AVAILABLE before VERIFIED
- failed probe -> DEGRADED; missing Maven -> UNAVAILABLE

Execution:
- runs Maven as local subprocess
- reads Surefire/Failsafe XML
- Actual derives from tests/failures/errors/skipped
- subprocess exit code alone never proves PASS
- JUnit XML failure with Maven exit 0 remains failed Actual
- missing JUnit XML fails closed

Publication:
- Actual JSON, stdout, stderr, JUnit XML uploaded first
- every execution artifact must be AVAILABLE
- then canonical `MAVEN_JUNIT_ACTUAL_RECORDED` R1 event is appended with artifact refs
- only after evidence/R1 success may WorkItem complete

### Bank Maven/JUnit Reality Runner
Files:
- `rc8_node/reality_maven.py`
- `packaging/rc8/rc8-maven-reality.sh`

The runner executes:
Center health -> Node register -> qualification WorkItem -> real Maven probe -> probe Artifact -> Capability VERIFIED -> execution WorkItem -> Maven/JUnit -> JUnit XML Actual -> execution Artifacts -> R1 -> WorkItem COMPLETED.

Portability hardening:
- default Maven execution uses `-o` offline mode;
- optional explicit `--maven-repo` / `RC8_MAVEN_REPO`;
- `--strict-portability` requires an explicit offline Maven repository and forbids silently proving portability with developer-machine default `~/.m2`;
- unsafe run IDs are rejected before Center/Artifact mutation;
- `preflight.json` is written before execution with Center/platform/pom/Maven/repository facts;
- `reality-result.json` records execution-chain truth.

## Current CI truth
Latest verified code HEAD: `b0f35a8a45e29e68d4ac0a3dc725e3b5104d7d80`
Workflow: `RC8 W1 Center Node Control`
Run: `39696048518`
- Ubuntu: SUCCESS
- Windows: SUCCESS
- includes compile gates, node/center/reality shell entrypoints, control plane, R1, Artifact Sync, durable restart, real-subprocess capability semantics, Maven/JUnit Actual semantics, Center-HTTP publication, full WorkItem ordering, Reality Runner, strict portability preflight.

Important boundary: CI uses deterministic synthetic Maven command/JUnit fixtures for repeatability. Therefore:
- Maven/JUnit adapter = IMPLEMENTED / CI_VERIFIED
- W1 single-node protocol = IMPLEMENTED / CI_VERIFIED
- bank environment Maven/JUnit = NOT YET REALITY_VERIFIED
- RC8 W1 = NOT CLOSED

## Current next gate
Do not add broad multi-node scheduling or all product pages yet.

The next hard gate is one target-bank run using:
- Windows Git Bash or Xinchuang Linux bash
- actual RC8 Center
- actual Node
- actual Maven path
- actual project `pom.xml`
- explicit offline Maven repository in strict-portability mode
- actual Surefire/Failsafe XML
- actual Center Artifact persistence
- actual R1 persistence

Only after that evidence may Maven/JUnit be marked `BANK_ENV_VERIFIED` / `REALITY_VERIFIED`.

After the single-node real slice is accepted, build only the first two truthful product sample surfaces:
1. 测试任务
2. 执行节点

## Status semantics
- OPEN / OPEN_INPUT: no implementation proof or authoritative input unavailable
- IMPLEMENTED: code exists
- CI_VERIFIED: automated cross-platform gates pass
- REALITY_VERIFIED: target environment real execution/evidence proves behavior
- CLOSED: requirement/gap trace complete and no acceptance blocker

A code commit, installed plugin, successful process exit, or CI fixture is never by itself bank Reality Verification.
