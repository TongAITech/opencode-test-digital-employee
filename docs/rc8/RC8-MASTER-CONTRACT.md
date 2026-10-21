# RC8 Master Contract

Status: FROZEN-CANDIDATE
Branch: `work/rc8`
RC7 inheritance base: `2c2eecbf18dde97ecdb10b65264e8c5c2a88ef72`

## 1. Product goal
RC8 is the shared AI testing digital-employee platform that preserves RC7's proven execution capabilities while adding a central control/product plane, durable TestRun state, single/multi-node execution, cross-node closed-loop control, business-flow capture, shared skills/knowledge, durable evidence, deployability, and an understandable Chinese product UI.

RC8 is not a rewrite of proven RC7 tools. The default strategy is: preserve RC7 execution core, add RC8 adapters/node agent/control plane/product plane, migrate capabilities behind reality gates, and close RC7 reality gaps in RC8.

## 2. Non-negotiable invariants
1. `RC7_CAPABILITY_MUST_NOT_REGRESS` — RC7 capabilities already reality-verified cannot become UNKNOWN after migration.
2. `R1_EVENT_STREAM_IS_RUNTIME_TRUTH` — runtime truth is event/evidence based; plans and model claims cannot become execution facts.
3. `NO_REAL_EXECUTION_NO_EXECUTED` — an agent statement cannot substitute for tool/worker execution.
4. `NO_ASSERTION_EVIDENCE_NO_PASS` — PASS requires actual result, assertion and bound evidence.
5. `PLAN_COMPLETE_IS_NOT_TEST_SUFFICIENT`.
6. `SESSION_IS_NOT_TASK_TRUTH` — DSH Session is an interaction context, not durable task state.
7. `SINGLE_NODE_MUST_BE_FULLY_FUNCTIONAL` — one Center + one DSH Node must support the full functional loop; multi-node is horizontal scale/collaboration, not a prerequisite.
8. `PRODUCT_UI_MUST_EXPLAIN_RUNTIME_TRUTH_WITHOUT_DSH` — a user must understand what was tested and why from the product UI without reading DSH logs.
9. `NODE_MUST_BE_DOWNLOADABLE_FROM_CENTER`.
10. `NODE_PACKAGE_MUST_CONTAIN_RC7_OFFLINE_CAPABILITIES` — the bank transport package includes the frozen redistributable RC7 offline toolset and does not depend on public internet install at runtime.
11. `WINDOWS_GIT_BASH_MUST_WORK` and `XINCHUANG_LINUX_BASH_MUST_WORK` — the canonical entrypoint is shell-based; Windows runs it from Git Bash, Xinchuang Linux from bash.
12. `ONE_NODE_PROTOCOL_MULTI_PLATFORM_ADAPTER` — platform differences live behind adapters; task/event/artifact protocols are common.
13. `SKILLS_ARE_CENTER_DISTRIBUTED` — skills are versioned packages distributed by Center and verified on nodes.
14. `KNOWLEDGE_IS_CENTER_DURABLE` — verified knowledge is central/durable and requested by task scope; DSH session memory is non-authoritative.
15. `ARTIFACTS_ARE_SYNCED_NOT_DIRECT_DB_WRITES` — DSH/tools do not write Center DB directly; Node Agent synchronizes events/assets through defined protocols.
16. `BANK_DEPLOYMENT_IS_FIRST_CLASS` — packaging, clean install, startup, smoke, upgrade, restart/recovery are part of Definition of Done.
17. `CAPABILITY_BASED_NO_EXACT_VERSION_PIN` — dispatch by verified capability, not exact software version.

## 3. Architecture boundaries
### RC8 Center
Owns durable identity and collaboration:
- production batches, system versions, requirements, delivery scopes, applications, SSTs;
- TestRun / WorkItem / Attempt state;
- node registry, capability registry, task/resource leases;
- centralized R1 event projection;
- artifact metadata, reports, defects, gaps;
- Skill Registry and Knowledge Store;
- business-flow/route/system-behavior knowledge;
- product UI and node package distribution.

Recommended first implementation: modular monolith + PostgreSQL + Redis + artifact/file storage. Do not split microservices before reality requires it.

### RC8 Node Agent
Runs on an office PC and owns:
- registration/heartbeat/capability qualification;
- task lease and local durable work/upload queue;
- adapters to RC7 execution capabilities;
- DSH invocation and Worker execution;
- event/artifact/knowledge/skill-candidate synchronization;
- platform adapters for Windows Git Bash and Xinchuang Linux bash.

### RC7 Execution Core
Preserve and wrap proven capabilities such as Browser/Chromium, CodeGraph, Maven/JUnit harness, pytest, AnyDoc, ripgrep, 4A auth, routing, R1 runtime components and other frozen redistributable RC7 tools/plugins. Migration is adapter-first, not reimplementation-first.

## 4. AI closed-loop model
Closed loop has three levels:
1. Node-local loop: plan -> execute -> evidence -> evaluate -> gap -> repair -> re-evaluate.
2. Cross-node/cross-stage loop: later-stage gaps route to the correct earlier stage (requirements, code analysis, design, data, auth, route, script, oracle, environment) and invalidate dependent downstream artifacts as needed.
3. Mission loop: global sufficiency evaluation continues until `TEST_SUFFICIENT`; execution completion alone is insufficient.

Gaps are first-class durable objects. A failure is classified and routed; it is not blindly retried.

## 5. Evolution model
Self-evolution means verified accumulation of knowledge, skills, strategies and test assets, not automatic model training.
- Discover -> candidate -> evidence -> verify -> version -> reuse -> revalidate.
- One node cannot directly poison shared knowledge or skill releases.
- Knowledge and skills keep provenance, version, evidence and verification status.

## 6. Business-flow capture
A captured business flow must preserve more than an API list:
- business operation steps;
- page/action timeline;
- API call order;
- data dependencies and variable bindings;
- authentication dependencies;
- business state dependencies;
- request/response examples;
- screenshots/network evidence;
- replay/validation history.

Captured flow becomes a candidate asset and must be replay/verified before becoming trusted shared knowledge.

## 7. Data model anchor
Top-level delivery reality is production batch/date, not a single system version.
A requirement can map in one production batch to one or many system versions, one or many applications, and one or many SSTs.
Canonical link object: `RequirementDeliveryScope(production_batch, requirement, system_version, application, sst)`.
The same requirement can reappear across later production batches/iterations.
Testing must support scope-local and cross-application/cross-system/E2E cases.

## 8. Artifact synchronization
Protocols between Center and Node are separate and explicit:
- Task Protocol
- Event Protocol
- Artifact Sync Protocol

Artifacts include screenshots, video, logs, HAR/network, request/response, SQL results, scripts, data assets, skill candidates and knowledge candidates. Large files live in artifact storage; PostgreSQL stores metadata/relationships. Every evidence asset binds to TestRun/Case/Attempt/Step/Assertion where applicable and carries hash/provenance.

## 9. Product constraints
The product is Chinese-first, Apple-inspired, simple, restrained, spacious and consistent.
- no dashboard-first UX;
- no giant cards or noisy colorful navigation;
- left navigation + clear filter/list surfaces + large detail views;
- large detail modal/page for complex objects, not cramped nested dialogs;
- lists locate objects, details explain them;
- testing semantics and traceability are primary; statistics are secondary;
- 10-second understand / 30-second locate / 1-minute trace target.

Primary navigation baseline:
1. 投产管理
2. 版本管理
3. 需求管理
4. 代码分析
5. 业务流程
6. 测试接口
7. 测试用例
8. 测试任务
9. 测试报告
10. 缺陷管理
11. 知识库
12. 执行节点
13. 系统信息

## 10. Test data policy
For RC8 delivery scope, do not make data desensitization/sensitivity governance a blocker. Prioritize test-data discovery, construction, preparation, validation, leasing, reuse and cleanup. Runtime credentials/secrets remain a separate system-security concern and are not ordinary test-data assets.

## 11. Packaging/deployment contract
Center and Node are independent deliverables.
- Center: deployable on test server, preferably containerized where the bank environment supports Docker.
- Node: portable package downloadable from Center; no hidden public-internet install dependency.
- canonical start scripts: `rc8-node.sh`, `rc8-check.sh`, `rc8-stop.sh`, `rc8-upgrade.sh`.
- Windows: Git Bash.
- Xinchuang Linux: bash; architecture variants are capability-qualified rather than assumed.
- installation PASS requires real end-to-end smoke: Center task -> Node receive -> real tool execution -> event -> assertion/evidence -> product display/report.
- upgrade must preserve existing data/assets and support rollback.

## 12. Definition of Done
A work item is not CLOSED until applicable gates pass:
- requirement/design trace exists;
- implementation exists;
- automated regression passes;
- reality execution passes;
- evidence exists;
- product projection exists if user-visible;
- restart/recovery remains truthful;
- single-node path passes;
- multi-node path passes where applicable;
- package/install/upgrade gates pass where applicable;
- traceability status moves: OPEN -> IMPLEMENTED -> REALITY_VERIFIED -> CLOSED.

Any implementation that contradicts this contract requires an explicit architecture decision and baseline update before code change.
