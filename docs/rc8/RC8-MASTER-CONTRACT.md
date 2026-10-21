# RC8 Master Contract

Status: FROZEN FOR CONSTRUCTION

Base branch: `work/rc7-field-hardening`
Base commit: `33433c8664ad73627409b27646d437e9efe66144`
RC8 branch: `work/rc8-control-plane-foundation`

## 1. Goal

RC8 upgrades RC7 from a primarily local closed-loop runtime into a shared testing-digital-employee platform with a central control/product plane and one or more DSH execution nodes, while preserving every RC7 reality-verified capability.

RC8 is accepted only when a tester can understand from the central product, without reading DSH conversation logs, what was tested, why it was tested, how it was executed, what actually happened, why the verdict was reached, what gaps caused rework, and what evidence proves the result.

## 2. Non-negotiable invariants

1. `RC7_CAPABILITY_MUST_NOT_REGRESS`.
2. `R1_EVENT_STREAM_IS_RUNTIME_TRUTH`.
3. `SESSION_IS_NOT_TASK_TRUTH`.
4. `PLAN_COMPLETE != TEST_SUFFICIENT`.
5. `WORKFLOW_COMPLETE != MISSION_COMPLETE`.
6. `NO_REAL_EXECUTION_EVIDENCE_NO_EXECUTED`.
7. `NO_ASSERTION_EVIDENCE_NO_PASS`.
8. `SINGLE_NODE_MUST_BE_FULLY_FUNCTIONAL`.
9. `MULTI_NODE_IS_HORIZONTAL_SCALE_NOT_A_FUNCTIONAL_PREREQUISITE`.
10. `PRODUCT_UI_MUST_EXPLAIN_RUNTIME_TRUTH_WITHOUT_DSH`.
11. `NODE_MUST_BE_DOWNLOADABLE_FROM_CENTER`.
12. `NODE_PACKAGE_MUST_CONTAIN_RC7_OFFLINE_CAPABILITIES`.
13. `WINDOWS_GIT_BASH_MUST_WORK`.
14. `XINCHUANG_LINUX_BASH_MUST_WORK`.
15. `ONE_NODE_PROTOCOL_MULTI_PLATFORM_ADAPTER`.
16. `SKILLS_ARE_CENTER_VERSIONED_AND_DISTRIBUTED`.
17. `KNOWLEDGE_IS_CENTER_DURABLE_AND_EVIDENCE_BACKED`.
18. `NODE_DOES_NOT_WRITE_CENTER_DATABASE_DIRECTLY`.
19. `BANK_DEPLOYMENT_IS_FIRST_CLASS`.
20. `NO_HIDDEN_EXTERNAL_DOWNLOAD_DEPENDENCY`.
21. `UPGRADE_MUST_PRESERVE_EXISTING_DATA`.
22. `CAPABILITY_BASED_NO_EXACT_VERSION_PIN`.

## 3. RC7 inheritance rule

RC8 reuses the RC7 execution core, adapters and already-proven offline tools. RC8 must not reimplement a verified RC7 capability unless an Architecture Decision explicitly proves reuse is impossible. Every inherited capability requires an RC8 migration regression gate: RC8 result must be no weaker than RC7 and must additionally integrate with TestRun identity, central R1 projection, Evidence, node capability qualification and product traceability.

## 4. Target architecture

RC8 consists of:

- Central platform: product UI, TestRun control plane, Mission graph, loop engine, dependency/invalidation engine, node registry, capability registry, task leasing, resource leasing, artifact/evidence registry, knowledge registry, skill registry, reports and defects.
- PostgreSQL: business assets, control state, projections and metadata.
- Redis: leases, short-lived coordination and cache; Redis loss must not destroy durable truth.
- Evidence/artifact storage: screenshots, videos, logs, HAR, request/response payloads, generated scripts and other large files.
- DSH execution node: Node Agent + RC7 execution core + offline toolset + skills + local durable queues/caches.
- Node/Center protocols: Task Protocol, Event Protocol and Artifact Sync Protocol.

The central server manages state, collaboration and durable memory. The office PC performs model reasoning and real execution.

## 5. Business master model

Top-level production scope is Production Batch / production date, not a single system version.

Canonical relationship:

`ProductionBatch -> Requirement -> RequirementDeliveryScope -> SystemVersion + Application + SST`

A requirement may participate in multiple production batches. In one production batch it may relate to one or many system versions, one or many applications and one or many SSTs.

Analysis, risk, cases, execution, defects and knowledge must be traceable to RequirementDeliveryScope and may also aggregate to requirement or production-batch level.

## 6. Closed-loop model

RC8 must implement three loop levels:

- Node-local loop: execute -> evaluate -> gap -> repair -> re-evaluate.
- Cross-node loop: downstream facts can route a Gap to the correct upstream node (requirement/code/design/data/auth/route/script/oracle/execution/etc.).
- Mission loop: evaluate overall test sufficiency, invalidate affected downstream outputs when upstream facts change, reopen only impacted work, and converge only with evidence-backed sufficiency.

Gap is a first-class durable object. Retry is not a substitute for routing.

## 7. Business-flow recording

RC8 must record business operation steps and the runtime relationship among page actions, requests and state transitions. A flow may include:

- user actions and page context;
- ordered API calls;
- request/response samples;
- authentication dependency;
- data dependency / variable binding;
- business-state dependency;
- resulting UI/API/DB state;
- evidence and replay history.

Raw capture, structured flow and candidate knowledge are separate artifacts. A temporal sequence is not automatically a verified dependency; replay/validation is required before promoting dependencies to verified knowledge.

## 8. Skill and knowledge sharing

Tools travel with the node package. Skills are center-versioned packages executed on nodes. Knowledge is center-durable, evidence-backed, versioned and retrieved by task scope.

Node startup synchronizes skill manifests, validates capabilities, and becomes READY only for capabilities proven on that node. A skill being installed is not equivalent to a verified capability.

Knowledge lifecycle: candidate -> evidence verified -> stable/verified -> possibly stale -> superseded. Session text is never the sole knowledge store.

Knowledge retrieval must work without embeddings, primarily using structured identities and relations: production batch, requirement, system, version, application, SST, page, API, table, class, method and knowledge type.

## 9. Test data

RC8 prioritizes discovering, creating, validating, leasing, reusing and reclaiming test data. Test-data sensitivity/desensitization is not a product-design gate for RC8 testing capability. Runtime credentials such as passwords, tokens and live session cookies remain system credentials rather than ordinary shared test data.

## 10. Artifact / upload model

All node-produced content enters Center through Node Agent. Nodes must never directly write PostgreSQL.

Canonical upload categories include Event, Artifact, Script, Skill Candidate, Knowledge Candidate and Data Asset. Every artifact has a unique identity, producer node, TestRun/WorkItem lineage, type, size/hash/version/status and subject bindings. Evidence must bind to the assertion/step it proves.

Large files use resumable/chunked upload where required. Nodes maintain a durable local upload queue so transient Center/network failure does not lose runtime facts or evidence.

## 11. Node distribution and platform support

Center provides node-package download and upgrade download. The node package includes the frozen RC7 offline toolset or capability-equivalent fallbacks and must not require public-network downloads at install/runtime.

Primary startup interface is shell:

- Windows: Git Bash -> `./rc8-node.sh`
- Xinchuan Linux: system bash -> `./rc8-node.sh`

Platform-specific binaries/adapters live below a common node protocol. CPU architecture must be detected; unsupported binary capabilities remain unavailable rather than being falsely reported READY.

## 12. Product rules

User-visible language is Chinese-first. Avoid mixed Chinese/English except necessary technical identifiers such as API methods, product names or database types.

Visual style: Apple-inspired simplicity, restrained color, generous spacing, clear hierarchy, weak borders, consistent components, list/search/detail as the primary interaction model, no decorative dashboard-first design.

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

Important details use large detail dialogs/pages with enough width/height and tabs; do not squeeze BR/SR/TR/code/case/execution/evidence into small cards.

Product acceptance heuristics: 10 seconds to understand the page, 30 seconds to locate the target object, 1 minute to trace why-tested -> how-tested -> actual -> assertion -> evidence.

## 13. Deployment and delivery

Deployment is part of architecture, not a final packaging step.

Deliverables must include Center package, Node package, upgrade package, DB migrations, preflight/diagnostic tools, install verification and rollback strategy.

Installation PASS requires a real end-to-end smoke: Center creates task -> node registers/leases -> real tool executes -> R1 event/evidence uploads -> UI projects the runtime result -> minimum report is produced.

Required validation stages: development, clean-machine package validation, real bank-environment validation, restart/recovery validation and upgrade/data-preservation validation.

## 14. Construction governance

Git/HEAD + frozen baselines + R1/Evidence are the source of truth. Conversation memory is not.

Every user requirement receives a traceability ID. Every RC7 gap carried into RC8 must map to design, implementation, test, evidence and closure state.

Completion state: `OPEN -> IMPLEMENTED -> TESTED -> REALITY_VERIFIED -> CLOSED`.

A code commit alone never closes a requirement or gap.

Any architecture change that weakens this contract requires an explicit Architecture Decision and baseline update before implementation.