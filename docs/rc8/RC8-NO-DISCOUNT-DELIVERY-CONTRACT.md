# RC8 No-Discount Delivery Contract

Status: FROZEN
Purpose: prevent tool-level success, one-shot execution, model claims, green CI, or partial evidence from being promoted into stage/L1-L7/mission completion.

This contract is an execution/acceptance amendment to the RC8 Master Contract, Architecture Baseline, Product Baseline, and RC7->RC8 Gap Matrix. When implementation pressure conflicts with this contract, implementation scope must expand or remain OPEN/PARTIAL; the acceptance bar must not be reduced.

## 1. Five independent truth levels

Every capability and every test stage MUST carry five separate statuses. No level may be inferred from a lower level.

1. TOOL_CAPABILITY
   - installed/discovered is not verified
   - REALITY_VERIFIED requires real target-environment invocation and evidence

2. STAGE_EXECUTION
   - real Worker/tool execution occurred
   - actual/assertion/evidence are bound to Attempt
   - execution completion is not sufficiency

3. STAGE_SUFFICIENCY
   - coverage/risk/oracle/evidence/gap gates satisfied
   - one green execution cannot imply this state

4. MISSION_SUFFICIENCY
   - all required stages/scopes converge
   - unresolved critical gaps = 0 or explicit governed waiver/hold

5. RELEASE_DECISION
   - separate from testing success
   - product defects may coexist with successful test execution and still cause HOLD

Forbidden promotions:
- TOOL_REALITY_VERIFIED != L1/L2/L3/L4/L5/L6/L7_READY
- MAVEN_BUILD_SUCCESS != L1_PASS
- JUNIT_ZERO_FAILURE != L1_SUFFICIENT
- CODEGRAPH_QUERY_SUCCESS != CODE_ANALYSIS_SUFFICIENT
- BROWSER_ACTION_SUCCESS != L4_PASS
- CASE_COUNT != DESIGN_SUFFICIENT
- PLAN_COMPLETE != TEST_SUFFICIENT
- WORKITEM_COMPLETED != TEST_SUFFICIENT
- REPORT_GENERATED != RELEASE_PASS

## 2. Canonical end-to-end semantic chain

The platform MUST preserve and productize this chain:

ProductionBatch
-> RequirementDeliveryScope
-> Requirement
-> BR/SR/TR
-> Risk
-> TestIntent
-> VerificationPoint
-> TestCase
-> Preconditions
-> TestData
-> ExecutableSpec
-> Script/Action Plan
-> Attempt
-> Action
-> Oracle/Assertion
-> Actual
-> Evidence
-> Failure Classification
-> Gap or Defect
-> Repair/Delta Design
-> Re-execution
-> Sufficiency Evaluation
-> TEST_SUFFICIENT
-> Release Decision

Each object is versioned/provenance-bound and traceable in Center. DSH Session is never authoritative task state.

## 3. Autonomous closed loop is mandatory, not optional polish

### 3.1 Node-local loop
Plan -> Execute -> Evidence -> Evaluate -> Gap -> Repair -> Re-evaluate.

### 3.2 Cross-stage route-back
A later failure/gap MUST route to the correct owner and invalidate stale downstream assets when needed:
- REQUIREMENT_UNCLEAR -> Requirement Analysis
- CODE_UNCERTAIN -> Code Analysis
- DESIGN_GAP -> Test Design
- SCRIPT -> Script Builder
- ORACLE -> Oracle/Assertion Design
- TEST_DATA -> Data Builder
- PRECONDITION -> Precondition Builder
- AUTH -> 4A/Auth Runtime
- ROUTE -> Browser/Network Route Discovery
- ENVIRONMENT -> Environment/Capability Recovery
- DEPENDENCY -> Build/Dependency Recovery
- PRODUCT -> Defect flow; do not repair test to make it green
- FLAKY -> controlled reproducibility analysis
- UNKNOWN -> durable Gap; never blind retry

### 3.3 Mission convergence
The loop stops only when sufficiency evaluator returns TEST_SUFFICIENT or an explicit governed HOLD/WAIVER exists. Retry count, all-green case execution, or plan exhaustion cannot close the mission.

## 4. Requirement Analysis node

Inputs:
- requirement/design documents
- production batch/version/application/SST scope
- historical verified knowledge

Outputs:
- BR/SR/TR
- business rules
- states/transitions
- constraints/boundaries
- actors/permissions
- data requirements
- ambiguity/unknown list
- risks and verification points

Mandatory loop:
Analyze -> Independent Evaluate -> Gap -> Delta Analyze -> Re-evaluate.

PASS requires:
- identified scope covered
- critical ambiguities resolved or explicit gap/waiver
- BR/SR/TR traceable
- risks/verification points evidence-backed

A single LLM pass is never sufficient.

## 5. Code Analysis node

Inputs:
- Git base/head/working-tree snapshot
- Git diff
- source
- requirement/SST scope
- CodeGraph structural evidence
- configuration/schema/API/DB evidence where available

Required outputs:
- changed files/classes/methods
- semantic nature of changes
- callers/callees/dependency graph
- API/controller/service/repository/DB/config impact where evidence supports it
- state/business-rule impact
- regression surface
- risks
- test impact by L1-L7
- unknowns and follow-up queries
- snapshot/evidence refs

Mandatory loop:
Git Diff -> CodeGraph query -> semantic analysis -> sufficiency evaluation -> additional queries -> re-analysis.

CodeGraph tool success alone is only TOOL_CAPABILITY evidence. CODE_ANALYSIS_SUFFICIENT requires semantic findings, evidence references, impact/risk/test mapping, and unresolved critical unknown = 0 or governed gap.

## 6. Test Design node

Test Design is not case generation. It is a coverage-optimization loop.

Inputs:
- requirement analysis
- code analysis
- risks
- historical defects
- verified business/API/data/auth knowledge

Required model:
Risk -> TestIntent -> VerificationPoint -> TestCase -> Oracle/Assertion.

Mandatory coverage matrix includes at least:
- requirement/business-rule coverage
- risk coverage
- verification-point coverage
- changed-code impact coverage
- positive/negative/boundary/state-transition coverage
- permission/auth coverage where relevant
- data/precondition coverage
- cross-scope/E2E coverage where relevant

Loop:
Design -> Independent Sufficiency Evaluate -> Coverage Gap -> Delta Design -> Re-evaluate.

Case count is never a sufficiency metric.

## 7. TestCase -> ExecutableSpec -> Script node

Every executable case MUST contain:
- preconditions
- test-data requirements
- ordered execution steps
- expected result per relevant step
- explicit oracle/assertion
- cleanup/recovery needs
- required tools/capabilities
- evidence requirements

Script generation MUST NOT silently rewrite expected/oracle to match implementation.

Script validation includes:
- compile/syntax
- tool/API compatibility
- fixture/data bindings
- assertion presence
- forbidden skip/disable patterns
- snapshot/spec provenance

## 8. L1-L7 are independent professional execution workers

A generic `layer` parameterized worker is prohibited as the final architecture. Each level has dedicated design/execution semantics, tools, evidence and sufficiency evaluator.

### L1 - Unit / code-level behavior
Primary tools:
- Java: Maven/Gradle where applicable, JUnit/TestNG, JaCoCo, optional PIT/mutation capability
- Python: pytest + coverage.py

Must verify:
- changed methods/lines/branches
- critical business-rule branches
- boundary/error paths
- assertion/oracle strength

Coverage is change-aware:
Git Diff + CodeGraph Impact + JaCoCo/coverage.py execution data.

Minimum configurable policy baseline:
- critical requirement executable coverage: 100%
- critical changed methods: 100% covered or explicit accepted gap
- critical changed branches: 100% covered or explicit accepted gap
- normal changed-line target: >=90%
- normal changed-branch target: >=80%
- critical unknown coverage gap: 0

JaCoCo global project percentage alone is insufficient.

Mandatory loop:
execute -> collect JUnit + coverage -> map changed code -> coverage gaps -> delta tests -> regenerate/repair script -> targeted rerun -> recalculate -> mutation/assertion-strength evaluation -> convergence.

`mvn returncode==0 && failures==0 && errors==0` means only EXECUTION_RESULT_GREEN.

### L2 - Component / Repository / DB integration
Primary tools:
- Java/Python integration runner
- real DB adapter/SQL
- transaction/readback evidence

Must verify:
- repository/ORM mapping
- CRUD and constraints
- transaction/rollback
- idempotency/retry
- data side effects/readback
- schema/data compatibility

PASS requires real DB binding and observable state evidence, not mock-only SQL execution.

### L3 - API / service integration
Primary tools:
- HTTP/API runner
- verified route knowledge
- 4A/auth where required
- DB/CAT/log evidence as oracle/support

Must verify:
- affected APIs/contracts
- positive/negative/boundary
- authn/authz
- request/response schema and business assertions
- backend side effects/readback
- unexpected 5xx = 0 for required scope

No guessed route is allowed. Route must come from verified source such as Browser network/OpenAPI/code/runtime knowledge and freshness must be checked.

### L4 - UI / Browser
Primary tools:
- BrowserSkill/Playwright/Chromium
- fresh 4A runtime auth
- DOM/network/trace/screenshot evidence

Must verify:
- real page steps, not zero-step proxy checks
- form/state/linkage behavior
- positive/negative/permission paths
- UI actual + relevant API/backend oracle

Browser action success is not PASS. PASS derives from case Expected/Oracle.

### L5 - Business E2E
Orchestrates real L2/L3/L4 capabilities plus data/auth/log evidence.

Must verify one coherent business journey:
- prepare data/preconditions
- fresh auth
- UI/API action sequence
- backend state transitions
- cross-application/system handoff where in scope
- final-state readback
- cleanup/recovery
- one execution/trace correlation

Key required journeys must reach 100% PASS or explicit defect/hold; fragmented per-layer green cannot substitute for E2E.

### L6 - Performance / capacity / stability
Primary tool baseline: k6 or equivalent verified runner.

Must distinguish:
- BASELINE_ONLY when no authoritative NFR exists
- PASS/FAIL only when threshold/SLA is defined

Evidence:
- workload model
- environment/config
- TPS/RPS
- latency distribution incl. P95/P99 where applicable
- error rate
- resource/monitoring evidence
- threshold comparison

A single smoke load is not performance sufficiency.

### L7 - Security / authorization
Primary scope:
- authentication/authorization matrix
- horizontal/vertical privilege
- input/negative security cases
- injection/XSS/other applicable attack paths
- audit/security response
- ZAP or scanner only when capability/approval permits

Must distinguish:
- PROBE
- CANDIDATE
- CONFIRMED

Scanner unavailable must not erase role/permission tests. Critical/High unresolved confirmed findings block release according to policy.

## 9. Failure semantics

An execution FAIL does not mean testing failed. It must be classified.

Canonical failure ownership:
- PRODUCT
- SCRIPT
- SPEC
- ORACLE
- DATA
- AUTH
- ROUTE
- ENVIRONMENT
- DEPENDENCY
- FLAKY
- TOOL
- MODEL
- SESSION/RUNTIME
- UNKNOWN

Examples:
- PRODUCT -> create/attach defect, preserve failing evidence, continue mission sufficiency evaluation
- SCRIPT -> repair script without changing expected semantics, rerun impacted cases
- DATA -> rebuild/release data lease, rerun
- AUTH -> fresh 4A, same task identity, rerun
- ROUTE -> recapture network, revalidate route knowledge, rerun
- UNKNOWN -> durable gap; no blind retry

Success of the testing mission may contain valid PRODUCT failures and therefore lead to RELEASE=HOLD.

## 10. Oracle and assertion contract

Every PASS requires:
- explicit Expected
- Actual
- assertion logic/result
- evidence ref

Oracle sources may include:
- requirement/business rule
- API contract
- DB state
- UI state
- CAT/log/trace
- cross-system final state

Oracle cannot be silently mutated by the same worker that is trying to make execution green. Oracle changes require provenance and independent evaluation.

## 11. Coverage and sufficiency model

Coverage is multidimensional and stage-specific.

Required dimensions where applicable:
- requirement coverage
- BR/SR/TR coverage
- risk coverage
- verification-point coverage
- changed method/line/branch coverage
- API coverage
- state-transition coverage
- permission/role coverage
- data/precondition coverage
- browser journey coverage
- E2E journey coverage
- performance threshold coverage
- security threat/authorization coverage
- oracle/assertion coverage
- mutation/assertion-strength coverage

A single percentage is never sufficient.

Coverage gaps are durable Gap objects, not comments in a report.

## 12. Test data and precondition lifecycle

Mandatory lifecycle:
Discover -> Build/Select -> Validate -> Lease -> Prepare -> Use -> Readback -> Release/Cleanup -> Reuse/Revalidate.

Test data/precondition construction is part of execution, not manual hidden work.

Resource leases protect accounts, business objects, records and write-sensitive environment resources.

## 13. 4A/auth runtime

Requirements:
- use fresh auth each new login/re-auth
- no stale historical cookie fallback
- no 'wait for manual login' as normal path
- expiry detection and re-auth
- human challenge handled through explicit controlled human lease when unavoidable
- preserve same task/TestRun identity through auth recovery
- evidence of auth runtime result

4A is a runtime prerequisite/capability, not a standalone L-level.

## 14. Browser / route knowledge

Mandatory observe-first policy:
Observe -> reason -> propose -> validate -> act -> observe.

API routes must not be guessed. Browser network capture/OpenAPI/code/runtime evidence becomes versioned route knowledge with source, confidence, freshness and last verification time.

Stale route knowledge triggers revalidation, not repeated 404 guessing.

## 15. Evidence / Artifact / R1 truth

R1 remains runtime truth.

Each Attempt preserves append-only history. Never overwrite old BLOCKED/FAIL/PENDING into PASS.

Evidence must bind where applicable to:
- TestRun
- WorkItem
- Case
- Attempt
- Step
- Assertion
- producer Node/Worker/Tool
- occurrence time
- source snapshot/environment
- hash/provenance

Artifact AVAILABLE is required before evidence-dependent PASS.

## 16. Defect closed loop

A defect is first-class and links:
Requirement/Scope -> Case -> Attempt -> Assertion -> Evidence -> RCA -> Code Impact -> Fix Snapshot -> Regression Attempt.

Objective is valid defect discovery, not green execution.

Defect closure requires regression evidence and no stale pre-fix evidence promotion.

## 17. Report semantics

Report first answers:
- what was tested
- why it was tested
- what was not tested and why
- coverage/sufficiency by dimension
- product defects found
- unresolved gaps/risks
- evidence and traceability
- release recommendation

Report generation cannot close a mission.

## 18. Director / Worker governance

Director:
- plan, decompose, route, supervise, gate, recover
- MUST NOT fabricate runtime execution
- MUST NOT replace specialist worker output with its own unproven analysis

Workers:
- dedicated by domain/stage/layer
- real tool use
- evidence-bound output
- bounded context

Session rotation:
- RUN/TestRun/WorkItem are durable
- DSH sessions are disposable
- checkpoint/handoff/artifacts preserve progress
- context inflation or lost session cannot erase mission state

## 19. Center / Node / multi-node

Single node MUST support the full product loop.
Multi-node adds parallelism/handoff, never correctness dependency.

Center owns durable mission/task/gap/evidence/knowledge/skill/projection state.
Nodes own real execution/reasoning and local durable queues.

Node identity/state lives outside versioned packages and survives upgrade.

## 20. Skill / Knowledge evolution

Tools != Skills != Knowledge.

Skills:
- versioned in Center
- declares provides/requires/platform/evidence/tests
- presence != verified capability

Knowledge:
- candidate -> verified -> stable -> stale/versioned
- source/evidence/provenance required
- route/auth/data/business/code/failure knowledge are scoped and revalidated
- DSH session memory is never durable knowledge truth

## 21. Product surface is part of Definition of Done

Critical pages:
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

The UI must show real projections of R1/domain state, including Attempt history, coverage, gaps, route-back, invalidation, defects and evidence. If users must read DSH logs to understand why PASS/FAIL occurred, the product slice is not done.

## 22. Bank deployment is part of capability

Separate complete deliverables:
- RC8-CENTER
- RC8-NODE

Node requirements:
- Windows Git Bash
- Xinchuang Linux bash
- x86_64/aarch64 platform adapters where required
- downloadable from Center
- carries frozen RC7 redistributable offline tools
- no hidden public-internet dependency
- persistent state outside package directory
- clean install/start/smoke/restart/upgrade/rollback gates

Every handoff is a complete package, never a patch-only acceptance package.

## 23. RC7 reality problems that remain mandatory RC8 acceptance inputs

The following MUST have explicit regression scenarios and cannot disappear behind broader gap labels:
- Director doing work instead of Worker dispatch
- Session/context inflation, stall or loss
- stale 4A cookie/manual-history fallback
- guessed API routes / repeated 404
- CodeGraph installed but not invoked
- plan/model events contaminating runtime truth
- plugin installed mistaken for capability verified
- L1 harness/environment false blockers
- L2 weak DB/Repository integration evidence
- L3 weak request/response/assertion traceability
- L4 zero-step/fake execution and awaiting worker dispatch
- L5 fragmented layer execution mistaken for E2E
- L6 BASELINE_ONLY/NFR ambiguity
- L7 scanner availability mistaken for all security capability
- incomplete preconditions/test data
- weak Actual/Expected/Assertion/Evidence mapping
- stale/insufficient evidence
- backend/product projection drift
- knowledge lost with DSH session
- cross-session/cross-worker continuation failure
- package succeeds in development but fails bank clean-install reality

## 24. Anti-simplification review required for every implementation slice

Before a slice may be called complete, review these questions:
1. What exact business/test capability is being claimed?
2. What lower-level tool capability is merely a dependency?
3. What is the dedicated sufficiency evaluator?
4. What coverage dimensions are measured?
5. What happens when coverage is insufficient?
6. What happens on PRODUCT failure vs SCRIPT/DATA/AUTH/ROUTE/ENV failure?
7. What new Attempt/Evidence/Gap/Defect facts are created?
8. What downstream artifacts are invalidated on upstream repair?
9. How does it resume across DSH session loss?
10. What does the product UI show without reading logs?
11. What bank-reality test proves it?
12. Which RC7 field regression does it close?

If any applicable answer is missing, status stays OPEN/PARTIAL/IMPLEMENTED; never promote by optimistic interpretation.

## 25. Mandatory status vocabulary

Use explicit scoped labels, for example:
- TOOL:MAVEN_JUNIT:BANK_REALITY_VERIFIED
- TOOL:CODEGRAPH:BANK_REALITY_VERIFIED
- STAGE:CODE_ANALYSIS:IMPLEMENTED
- STAGE:CODE_ANALYSIS:SUFFICIENCY_PENDING
- LAYER:L1:AUTONOMOUS_LOOP_PENDING
- MISSION:TEST_SUFFICIENT:NO
- RELEASE:HOLD

Never use an unscoped `PASS` for a complex capability.

## 26. Required implementation order from current RC8 state

Do not continue breadth-first tool verification until the first vertical autonomous slice is complete.

Priority A - Truthful vertical L1 closed loop:
1. ExecutableSpec contract
2. script builder/validator
3. Maven/JUnit and pytest real runners
4. JaCoCo / coverage.py adapters
5. changed-code coverage mapper (Git + CodeGraph + coverage)
6. failure classifier + ownership router
7. delta test design
8. delta script generation
9. targeted re-execution
10. mutation/assertion-strength gate
11. L1 sufficiency evaluator
12. convergence controller
13. Artifact/R1/Gap/Defect projections
14. product Attempt/Coverage/Gap display
15. bank reality mission test

Priority B - complete Requirement -> Code -> Design upstream loops feeding L1.

Priority C - L2, L3, L4 professional closed loops including DB/API/Browser/4A/route/data.

Priority D - L5 coherent E2E journey closure.

Priority E - L6/L7 dedicated sufficiency with BASELINE/NFR/security semantics.

Priority F - full mission sufficiency across L1-L7, multi-node/handoff, restart/recovery, product/report/release gates.

## 27. Final Definition of Done

RC8 is not accepted as an autonomous AI testing digital employee until one real bank mission demonstrates, with durable evidence:

Requirement/SST
-> iterative requirement analysis
-> iterative code analysis
-> iterative test design
-> executable specs/scripts
-> real precondition/data preparation
-> applicable L1-L7 real execution
-> per-step Actual/Assertion/Evidence
-> coverage collection and gap generation
-> failure ownership/RCA
-> defect creation for product failures
-> autonomous delta repair/re-design
-> targeted re-execution
-> coverage/sufficiency convergence
-> TEST_SUFFICIENT
-> truthful Report
-> Release recommendation
-> visible product traceability
-> restart/session-rotation continuity
-> full package deployment reality.

Anything less must be reported with exact scope as PARTIAL/IMPLEMENTED/REALITY_VERIFIED_TOOL_ONLY, never as the completed testing capability.