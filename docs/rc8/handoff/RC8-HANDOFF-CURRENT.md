# RC8 Current Handoff

Repository: `TongAITech/opencode-test-digital-employee`
Branch: `work/rc8`
RC7 source/capability base: `delivery/rc7-default-enhancements@2c2eecbf18dde97ecdb10b65264e8c5c2a88ef72`
RC7 transport/toolset reference: `delivery/rc7-internal-transport-0bbb8239@af59027e7227fa1861fea95c6d05ff73aefb8572`
Latest CI-verified code HEAD: `b0f35a8a45e29e68d4ac0a3dc725e3b5104d7d80`
Latest CI proof: workflow run `39696048518` SUCCESS on Ubuntu + Windows.
Current wave: `W1 - Center + Single Node Reality Gate`

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

New sessions must read these files and verify current Git HEAD and newest CI before editing. Git/HEAD + R1 runtime truth + evidence are authoritative; chat memory is not.

## Implemented and CI-verified so far
1. RC8 master/architecture/product/gap/traceability baselines.
2. Identity contracts for Node, ProductionBatch, RequirementDeliveryScope, TestRun and WorkItem.
3. Plan/runtime split; Director/model claims cannot create runtime truth.
4. Evidence/Artifact hash, provenance, availability and assertion-reference contracts.
5. Capability qualification state machine; VERIFIED requires real probe evidence.
6. Completion semantics where `PLAN_COMPLETE != TEST_SUFFICIENT`.
7. Central R1 ledger: runtime-only append, idempotency, conflict fail-close, replay, node sequence.
8. Center Node Registry/heartbeat/capability/WorkItem lease/start/complete.
9. Node-owned lease; no DSH Session authority.
10. Node Agent outbound Center protocol and stable local Node identity.
11. `rc8-node.sh` and `rc8-center.sh`, Windows Git Bash + Linux bash compatible.
12. Windows UTF-8 shell hardening for Chinese CLI.
13. Artifact Sync with resumable offset upload, size/SHA-256 verification and AVAILABLE gate.
14. Active WorkItem lease authorization for runtime/artifact writes; late writes fail closed.
15. Zero-byte Artifact support for real empty logs such as successful Maven stderr.
16. Durable W1 fallback repository proving Center restart preservation for Node/Capability/WorkItem/Artifact metadata and bytes.
17. First real capability adapter: Maven/JUnit.
18. Maven capability probe -> Center Artifact AVAILABLE -> VERIFIED chain.
19. Maven/JUnit execution adapter derives Actual from Surefire/Failsafe XML; exit code alone never proves PASS.
20. Execution publication uploads Actual/stdout/stderr/JUnit XML before R1.
21. Complete WorkItem order: lease -> start -> tool execution -> Artifact AVAILABLE -> R1 -> complete.
22. Real Center HTTP response shape is covered; mocks cannot hide nested Artifact response mismatches.
23. Maven/JUnit bank reality runner: `rc8_node/reality_maven.py`.
24. Cross-platform bank reality shell: `packaging/rc8/rc8-maven-reality.sh`.
25. Reality Runner defaults offline, supports explicit Maven repo, strict portability, preflight and result records.
26. Strict portability forbids using implicit developer `~/.m2` as portability proof.
27. Unsafe run IDs are rejected before Center/Artifact mutation.

## Latest verified CI truth
Code HEAD: `b0f35a8a45e29e68d4ac0a3dc725e3b5104d7d80`
Run: `39696048518`
- Ubuntu: SUCCESS
- Windows: SUCCESS
- Python 3.8
- shell entrypoints: PASS
- W1 control/runtime/artifact/capability/execution/reality-runner tests: PASS

This is `CI_VERIFIED`, not target-bank `REALITY_VERIFIED`.
CI uses deterministic synthetic Maven/JUnit fixtures to prove protocol and truth semantics. Never report these fixtures as a successful bank Maven/JUnit run.

## Current single hard gate
Run the first target-bank Maven/JUnit reality slice. Do not add broad multi-node scheduling or all product pages first.

Required real chain:
1. start actual RC8 Center;
2. use one real office-PC Node;
3. Windows uses Git Bash; Xinchuang Linux uses bash;
4. point `RC8_MVN` / `--maven` at actual Maven;
5. point `--project-dir` at an actual Maven project containing `pom.xml`;
6. use `--strict-portability --maven-repo <explicit offline repo>`;
7. qualification probe must upload to Center before `maven-junit` becomes VERIFIED;
8. execution WorkItem must be leased by that Node;
9. Maven/JUnit must produce actual Surefire/Failsafe XML;
10. Actual/stdout/stderr/JUnit XML must be AVAILABLE in Center;
11. R1 event must be persistence-verified and reference those artifacts;
12. WorkItem must complete only after evidence/R1 success;
13. preserve `preflight.json` and `reality-result.json` as acceptance evidence.

Only after this chain runs on the real bank target may Maven/JUnit status move to `REALITY_VERIFIED` / `BANK_ENV_VERIFIED`.

## After the bank single-node gate
Build only the first two truthful product sample surfaces:
1. 测试任务
2. 执行节点

These surfaces must explain scope, Node, WorkItem, Actual, evidence, R1 state and blockers without reading DSH logs.

Then continue W1 hardening/restart recovery and only later expand capabilities/multi-node/product pages according to the frozen plan.

## RC7 transport inheritance note
Do not assume `2c2eecb` alone contains every transport-only commit. Keep the dual authority: newer source/capability line + verified `af59027` transport/toolset completeness reference. RC8 node packages must not silently omit RC7 offline capabilities.

## One authoritative-input hold
Exact final certification wording/severity for `GAP-ADD-03`, `GAP-ADD-06`, `GAP-ADD-10` is still unavailable in current Git sources. Keep them `OPEN_INPUT`; never guess them.

## Prohibited shortcuts
- no CI fixture => bank Reality Verified claim;
- no direct DSH/tool write to Center DB;
- no plugin installed => VERIFIED shortcut;
- no Director/model-generated runtime truth;
- no Session authority;
- no PASS without real Actual and AVAILABLE evidence;
- no Maven exit code 0 => PASS shortcut;
- no implicit `~/.m2` portability proof in strict mode;
- no broad multi-node scheduling before single-node real slice passes;
- no all-page product build before the two truthful sample surfaces;
- no node package that omits transport-only RC7 offline capabilities.
