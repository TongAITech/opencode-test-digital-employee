# RC8 Implementation Blueprint v2

Status: FROZEN-CANDIDATE
Purpose: translate RC8 architecture, testing-intelligence, product, RC7-reality, and deployment requirements into a no-discount implementation blueprint.

## 1. Product mission

RC8 is an AI testing digital-employee platform, not a tool launcher. The system is complete only when one real bank mission can autonomously and truthfully execute:

Production/Requirement/SST
-> iterative requirement analysis
-> iterative code analysis
-> risk/test-intent/verification-point modeling
-> iterative test design
-> executable-spec construction
-> precondition/test-data preparation
-> applicable L1-L7 real execution
-> per-step Actual/Assertion/Evidence
-> coverage collection
-> failure ownership/RCA
-> Gap/Defect generation
-> repair/delta-design
-> targeted re-execution
-> sufficiency convergence
-> TEST_SUFFICIENT
-> report/release recommendation
-> durable product traceability.

Tool success is a dependency, never the mission outcome.

## 2. System topology

```text
                          RC8 CENTER / PRODUCT PLANE
  ┌──────────────────────────────────────────────────────────────────────┐
  │ Domain: Production/Version/Requirement/SST/TestRun/WorkItem/Attempt │
  │ Mission Graph / Gap Router / Invalidation / Sufficiency / Release    │
  │ R1 Runtime Ledger / Projection Engine                               │
  │ Artifact & Evidence Registry / Defect                               │
  │ Knowledge Store / System Behavior Graph / Skill Registry            │
  │ Node Registry / Capability / Task Lease / Resource Lease            │
  │ Package Repository / Product API / Product UI                       │
  └──────────────────────────────┬───────────────────────────────────────┘
                                 │
        Task / Event / Artifact / Knowledge / Skill / Package protocols
                                 │
                 ┌───────────────┼────────────────┐
                 ▼               ▼                ▼
              NODE A           NODE B           NODE C
            Node Agent       Node Agent       Node Agent
                 │               │                │
                DSH             DSH              DSH
                 │               │                │
       RC7 Execution Core  RC7 Execution Core  RC7 Execution Core
```

Center owns durable mission truth. Node owns real reasoning/execution. DSH Session is disposable execution context.

## 3. Mandatory Center modules

### 3.1 Delivery domain
- ProductionBatch
- SystemVersion
- Requirement
- RequirementDeliveryScope
- Application
- SST

### 3.2 Mission domain
- TestRun
- MissionGraph
- WorkItem
- Attempt
- StageState
- LayerState
- CompletionState
- ReleaseDecision

### 3.3 Test semantics
- BR/SR/TR
- BusinessRule
- Risk
- TestIntent
- VerificationPoint
- TestCase
- ExecutableSpec
- Oracle/Assertion
- CoverageRequirement

### 3.4 Runtime truth
- R1 Event Stream
- Runtime producer policy
- event idempotency/order/provenance
- projection engine

### 3.5 Closed-loop engine
- Sufficiency Evaluator Registry
- Gap Router
- Repair Planner
- Dependency Graph
- Invalidation Engine
- Convergence Controller

### 3.6 Execution control
- Node Registry
- Capability Registry
- Task Lease
- Resource Lease
- Worker/Tool provenance
- recovery coordinator

### 3.7 Evidence/asset domain
- Artifact Registry
- resumable upload
- Evidence binding
- Step/Assertion binding
- snapshot/environment provenance

### 3.8 Defect domain
- Defect Candidate
- Confirmed Defect
- RCA
- fix snapshot
- regression linkage

### 3.9 Knowledge/skill domain
- Knowledge candidate/verified/stable/stale/version
- Skill package/version/qualification
- System Behavior Graph
- task-scoped resolver

### 3.10 Product/deployment
- Product API
- 13 product surfaces
- Node package repository
- upgrade/rollback catalog
- system diagnostics

## 4. Mandatory Node Agent modules

```text
Node Agent
├─ Durable Node Identity
├─ Registration / Heartbeat
├─ Capability Reality Probe
├─ Task Lease Client
├─ Resource Lease Client
├─ Durable Local Queue
├─ WorkItem Checkpoint / Recovery
├─ DSH Worker Bridge
├─ Specialist Worker Dispatcher
├─ RC7 Capability Adapters
├─ Runtime Event Producer
├─ Artifact Upload Queue
├─ Knowledge Resolver / Cache
├─ Skill Loader / Sync
├─ Package Upgrade Adapter
└─ Platform Adapter
   ├─ Windows Git Bash
   └─ Xinchuang Linux bash
```

Node identity/state MUST live outside versioned package directories.

## 5. Protocol boundaries

### 5.1 Task Protocol
Carries:
- mission/stage/work item identity
- scope/snapshot
- required capabilities
- task inputs/assets
- output/evidence contract
- lease/retry/idempotency metadata

### 5.2 Event Protocol
Carries only runtime facts:
- producer/node/worker/tool
- TestRun/WorkItem/Case/Attempt/Step/Assertion IDs
- occurrence/ingestion timestamps
- sequence/idempotency key
- payload + artifact refs

Plan/model claims are forbidden in Runtime Event plane.

### 5.3 Artifact Sync Protocol
Manifest -> upload/resume -> size/hash verification -> relation commit -> AVAILABLE.

### 5.4 Knowledge Sync Protocol
Task-scoped verified knowledge delivered to node; new facts return as candidates with provenance.

### 5.5 Skill Sync Protocol
Versioned Skill metadata/package, compatibility, qualification evidence, rollback.

### 5.6 Package Distribution Protocol
Center-hosted complete Node package + manifest + SHA-256 + platform/architecture metadata.

## 6. Canonical Mission Graph

Stages:
1. Scope Intake
2. Requirement Analysis
3. Requirement Sufficiency
4. Code Analysis
5. Code Sufficiency
6. Risk/Test Intent/Verification Point Modeling
7. Test Design
8. Design Sufficiency
9. ExecutableSpec
10. Precondition/Test Data
11. Applicable L1-L7 Execution
12. Failure Classification/RCA
13. Coverage/Sufficiency Evaluation
14. Gap/Defect Routing
15. Repair/Delta Design
16. Targeted Re-execution
17. Mission Sufficiency
18. Report/Release

Every stage can produce durable Gap objects. Repair may route backward and invalidate downstream artifacts.

## 7. Worker architecture

Director is control-plane logic only:
- decompose
- dispatch
- supervise
- route
- gate
- recover

Director MUST NOT fabricate runtime execution or replace specialist evidence.

Required specialist workers include at minimum:
- RequirementAnalysisWorker
- RequirementSufficiencyWorker
- CodeAnalysisWorker
- CodeSufficiencyWorker
- TestDesignWorker
- DesignSufficiencyWorker
- ExecutableSpecWorker
- TestDataWorker
- L1UnitWorker
- L2ComponentDbWorker
- L3ApiWorker
- L4BrowserWorker
- L5E2EWorker
- L6PerformanceWorker
- L7SecurityWorker
- FailureClassifierWorker
- RCAWorker
- DeltaDesignWorker
- ReportWorker

Each worker declares:
- inputs
- outputs
- allowed tools
- required evidence
- failure routes
- context budget
- timeout
- checkpoint schema

## 8. Requirement analysis implementation

Required outputs:
- BR/SR/TR
- business rules
- actors/roles/permissions
- state transitions
- boundaries/exceptions
- data conditions
- ambiguity/unknowns
- risks
- verification points

Required loop:
Analyze -> Evaluate -> Gap -> Delta Analyze -> Re-evaluate.

Single-pass model output cannot become sufficient.

## 9. Code analysis implementation

Inputs:
- Git base/head/working-tree snapshot
- Git diff/source
- requirement/SST scope
- CodeGraph evidence
- optional config/schema/API/DB evidence

Required outputs:
- changed files/classes/methods
- semantic change type
- callers/callees/dependencies
- controller/API/service/repository/DB/config impact where evidenced
- business/state impact
- regression surface
- risks
- L1-L7 test impact
- unknowns/follow-up queries
- evidence refs/snapshot

Loop:
query -> semantic analyze -> sufficiency -> additional query -> re-analyze.

## 10. Test design implementation

Canonical model:
Requirement/Rule/Risk -> TestIntent -> VerificationPoint -> TestCase -> Oracle.

Coverage matrix:
- requirement/BR/SR/TR
- risk
- verification point
- changed-code impact
- positive/negative/boundary
- state transition
- permission/auth
- data/precondition
- API/business flow
- cross-application/system/E2E

Loop:
Design -> independent sufficiency -> Coverage Gap -> Delta Design -> re-evaluate.

Case count is never sufficient evidence.

## 11. ExecutableSpec implementation

Every executable case includes:
- preconditions
- test-data requirements
- ordered steps
- action/target/input
- expected result
- explicit oracle/assertion
- evidence requirements
- cleanup/recovery
- required capabilities
- failure policy

No ExecutableSpec -> no execution dispatch.

## 12. L1 implementation target

L1 is the first complete autonomous vertical slice.

Pipeline:
Git/Requirement Risk
-> L1 design
-> ExecutableSpec
-> JUnit/TestNG/pytest generation
-> script validation
-> data/precondition preparation
-> Maven/JUnit/pytest real execution
-> JaCoCo/coverage.py
-> changed-code coverage mapping
-> failure classification
-> coverage/risk/oracle gap generation
-> delta test design
-> delta script generation
-> targeted re-run
-> mutation/assertion-strength gate where configured
-> L1 sufficiency
-> convergence.

Key metrics:
- critical requirement executable coverage
- changed method coverage
- changed line coverage
- changed branch coverage
- critical branch coverage
- risk/verification-point coverage
- oracle/assertion coverage
- mutation adequacy for configured high-risk scope

## 13. L2-L7 implementation boundaries

### L2 Component/Repository/DB
Real repository/ORM/DB behavior, CRUD, constraints, transaction/rollback, idempotency/retry, side effects/readback.

### L3 API/Service
Verified route/auth, request/response contract, positive/negative/boundary/permission, business assertion, backend readback/log evidence.

### L4 UI/Browser
Real page steps, DOM/actions, network, screenshot/trace, fresh auth, UI + backend oracle. Zero-step proxy PASS prohibited.

### L5 Business E2E
One coherent journey with data/auth/UI/API/backend state/cross-app handoff/final readback/cleanup/correlation.

### L6 Performance
Workload model + NFR/SLA + TPS/RPS + P95/P99 + error/resource data. Without authoritative threshold use BASELINE_ONLY.

### L7 Security
Authentication/authorization matrix, horizontal/vertical privilege, negative/security cases, audit; scanner is optional capability, not entire L7.

## 14. Failure ownership and repair routing

Canonical classes:
PRODUCT, SCRIPT, SPEC, ORACLE, DATA, AUTH, ROUTE, ENVIRONMENT, DEPENDENCY, FLAKY, TOOL, MODEL, SESSION_RUNTIME, UNKNOWN.

PRODUCT -> defect flow; never repair test merely to get green.
SCRIPT -> script repair.
SPEC -> ExecutableSpec repair.
ORACLE -> independent oracle review.
DATA -> data builder/release/reprepare.
AUTH -> fresh 4A/re-auth.
ROUTE -> observe network/revalidate route.
ENVIRONMENT/DEPENDENCY -> recovery.
FLAKY -> controlled reproducibility.
UNKNOWN -> durable gap, no blind retry.

## 15. Coverage domain

Coverage is multidimensional:
- requirement / BR / SR / TR
- risk / verification point
- changed method / line / branch
- API
- business flow
- state transition
- permission/role
- data/precondition
- E2E journey
- performance NFR
- security threat/authz
- oracle/assertion
- mutation/assertion strength

No single percentage can close a stage.

## 16. Invalidation semantics

Upstream version change invalidates dependent downstream facts.
Examples:
- Requirement analysis changes -> code/test design/execution sufficiency potentially stale.
- Code analysis finds new risk -> design/L1-L7 sufficiency stale.
- Oracle changes -> affected Attempts no longer prove PASS.
- Route/auth knowledge becomes stale -> dependent API/UI results require revalidation when applicable.

Invalidation is versioned, scope-aware, append-only and visible in UI.

## 17. Test data lifecycle

Discover -> Build/Select -> Validate -> Lease -> Prepare -> Use -> Readback -> Cleanup/Release -> Reuse/Revalidate.

Test data/preconditions are first-class execution assets, not hidden manual prerequisites.

## 18. 4A/auth runtime

- fresh authentication for new login/re-auth
- no stale cookie/history fallback
- expiry detection
- same WorkItem identity through re-auth
- explicit Human Lease only for unavoidable challenge
- auth result evidence

## 19. Route/system behavior

Observe-first policy:
Observe -> reason -> propose -> validate -> act -> observe.

Verified route knowledge contains source/evidence/confidence/version/freshness/last_verified_at.
Repeated API guessing/404 is a regression failure.

System Behavior Graph connects:
page/action -> API -> auth -> service/application -> code -> DB/state.

## 20. Runtime truth/evidence

R1 is the canonical runtime ledger.
Attempts are append-only.
Every PASS requires Expected + Actual + Assertion + AVAILABLE Evidence.
Evidence binds TestRun/WorkItem/Case/Attempt/Step/Assertion/producer/snapshot/environment/hash.

## 21. Product architecture

13 primary surfaces:
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

No dashboard-first design. Product status comes from domain projections, never front-end inference from raw counts.

## 22. Product projection rule

For every backend capability implemented, define:
- domain object
- runtime events
- projection
- API
- list/detail UI
- evidence drilldown
- invalidation/history behavior

If user must read DSH logs to understand the result, the slice is incomplete.

## 23. Session/runtime recovery

TestRun/WorkItem/Attempt are durable and session-independent.
Worker session checkpoint includes:
- input refs
- current stage
- completed actions
- pending gaps
- artifact refs
- knowledge refs
- handoff summary

Context/session loss cannot erase mission progress.

## 24. Deployment architecture

CENTER:
- modular monolith first
- PostgreSQL durable domain/projection
- Redis lease/coordination
- artifact/file storage
- containerized on test server where supported

NODE:
- office PC
- DSH/internal model access
- complete portable package
- RC7 offline tools
- Windows Git Bash + Xinchuang Linux bash
- x86_64/aarch64 platform capability adapters where needed
- persistent state outside package

## 25. Definition of Done: four-line gate

Every implementation slice must pass all applicable lines:

### Architecture
Domain/state/protocol/lease/recovery/invalidation/provenance correct.

### Testing Intelligence
Worker/tool/evidence/coverage/gap/repair/sufficiency complete.

### Product
Projection/API/list/detail/history/evidence/traceability usable.

### Reality
Automated regression + target-bank real execution + restart/recovery/package evidence.

Missing any applicable line -> PARTIAL/IMPLEMENTED only.

## 26. Status vocabulary

Always scoped:
- TOOL:<name>:DISCOVERED/VERIFIED/BANK_REALITY_VERIFIED
- STAGE:<name>:IMPLEMENTED/SUFFICIENCY_PENDING/SUFFICIENT
- LAYER:L1..L7:EXECUTED/SUFFICIENCY_PENDING/SUFFICIENT
- MISSION:TEST_SUFFICIENT:YES/NO
- RELEASE:PASS/HOLD/BLOCKED

Unscoped PASS is forbidden for complex capabilities.

## 27. First construction objective

Do not continue breadth-first tool migration as the main line.

First complete vertical target:
Requirement/Code Risk -> Test Design -> ExecutableSpec -> L1 Script -> Data/Precondition -> Real Execution -> JaCoCo/Coverage -> Failure/Gap -> Delta Design -> Targeted Re-run -> Convergence -> Product Projection -> Bank Reality.

Only after this vertical slice proves the architecture/intelligence/product/reality model should the same pattern expand to L2-L7.