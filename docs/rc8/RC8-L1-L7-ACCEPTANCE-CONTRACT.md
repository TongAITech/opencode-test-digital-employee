# RC8 L1-L7 Acceptance Contract

Status: FROZEN-CANDIDATE
Purpose: define professional, layer-specific execution semantics, evidence, coverage, failure handling, sufficiency, and Reality gates. A generic layer-parameter worker is prohibited as the final architecture.

## 1. Common layer contract

Every L1-L7 layer MUST have:
- dedicated designer/selector logic
- dedicated execution worker
- explicit required capabilities
- explicit preconditions/test data
- explicit Expected/Oracle/Assertion
- append-only Attempt history
- typed Evidence
- layer-specific coverage model
- failure classification
- durable Gap generation
- delta/repair route
- dedicated sufficiency evaluator
- product projection
- bank Reality proof

Common statuses:
- NOT_PLANNED
- DESIGNED
- EXECUTABLE_READY
- EXECUTING
- EXECUTION_COMPLETED
- EXECUTION_BLOCKED
- SUFFICIENCY_PENDING
- SUFFICIENT
- INSUFFICIENT
- INVALIDATED

`EXECUTION_COMPLETED` never implies `SUFFICIENT`.

## 2. L1 - Unit / code-level behavior

### 2.1 Objective
Verify changed and impacted code behavior at the smallest executable code boundary with strong oracles and change-aware coverage.

### 2.2 Required inputs
- Requirement/Risk/VerificationPoint
- Git base/head/snapshot
- Code Analysis findings
- changed/impacted methods/branches
- applicable historical defects

### 2.3 Required tools
Depending on project:
- Maven/Gradle
- JUnit/TestNG
- pytest
- JaCoCo
- coverage.py
- mutation tool such as PIT for configured high-risk scope
- CodeGraph/Git for change mapping

Tool availability is qualified separately from L1 sufficiency.

### 2.4 ExecutableSpec requirements
- class/module under test
- setup/fixture/preconditions
- test data
- method/action
- expected result
- explicit assertions
- exception/side-effect assertions
- cleanup
- evidence requirements

### 2.5 Coverage dimensions
Mandatory where applicable:
- requirement executable coverage
- risk coverage
- verification-point coverage
- changed method coverage
- changed line coverage
- changed branch coverage
- critical business-rule branch coverage
- oracle/assertion coverage
- mutation adequacy for configured high-risk change

Global project line coverage alone cannot close L1.

### 2.6 Initial policy baseline
Project policy may raise thresholds but must not silently lower without explicit decision.
- critical requirement executable coverage = 100%
- critical changed methods = 100% or explicit accepted gap/hold
- critical changed branches = 100% or explicit accepted gap/hold
- normal changed line target >= 90%
- normal changed branch target >= 80%
- unresolved critical coverage/unknown gap = 0 for SUFFICIENT

### 2.7 Execution artifacts
- generated/selected script
- Maven/pytest command
- stdout/stderr
- fresh JUnit/pytest results
- fresh JaCoCo/coverage artifact
- change-coverage mapping
- mutation result when required
- Actual/Assertion evidence

### 2.8 Loop
Design -> Script -> Validate -> Execute -> Coverage -> Evaluate -> Gap/Failure -> Delta Design/Repair -> Targeted Re-run -> Recalculate -> Re-evaluate.

### 2.9 Failure semantics
- PRODUCT: preserve failing assertion/evidence; defect candidate; do not rewrite test to green
- SCRIPT: repair script; same expected semantics; new Attempt
- SPEC: repair ExecutableSpec through governed path
- ORACLE: independent oracle review
- DATA/PRECONDITION: repair preparation
- ENV/DEPENDENCY/TOOL: recover capability/environment
- FLAKY: controlled reproducibility
- UNKNOWN: durable Gap

### 2.10 L1 sufficiency
Requires all configured mandatory coverage dimensions and critical gaps to converge. `mvn test` return code 0 and zero JUnit failure means only EXECUTION_RESULT_GREEN.

## 3. L2 - Component / Repository / DB integration

### 3.1 Objective
Verify component/repository behavior against real integration boundaries, especially persistence and transactional semantics.

### 3.2 Required inputs
- impacted component/repository/DAO
- DB/schema/table knowledge
- data/precondition requirements
- business constraints
- risk/verification points

### 3.3 Required capabilities
- Java/Python integration runner
- real DB adapter/SQL for TDSQL/OceanBase/TiDB as scope requires
- transaction/readback
- log evidence when needed

Mocks may support diagnosis but cannot substitute for required real integration evidence.

### 3.4 Required coverage
- repository/ORM mapping
- CRUD
- constraints/defaults/nullability
- transaction/rollback
- idempotency/retry
- concurrency where risk requires
- data side effects
- readback consistency
- error paths
- changed persistence behavior

### 3.5 Evidence
- executed test result
- SQL/DB Actual/readback
- transaction evidence
- row/state before/after where applicable
- assertion result
- logs

### 3.6 Sufficiency
Required component/DB risks and verification points covered; no unresolved critical data-state gap. A single successful SQL query is not L2 PASS.

## 4. L3 - API / service integration

### 4.1 Objective
Verify affected service/API behavior through real observed/verified routes with authentication and backend effect assertions.

### 4.2 Route rule
No guessed API route. Route source must be one or more of:
- Browser network capture
- OpenAPI/spec
- code/runtime evidence
- verified route knowledge

Route has source, confidence, version/snapshot, last_verified_at. Stale route triggers revalidation.

### 4.3 Required capabilities
- HTTP/API runner
- 4A/auth when applicable
- route resolver
- DB/log/CAT support where oracle requires

### 4.4 Coverage
- affected endpoints
- method/path/contract
- positive
- negative
- boundary
- authentication
- authorization
- request schema
- response schema
- business assertions
- error handling
- backend side effect/readback
- idempotency/retry where applicable

### 4.5 Evidence
- request
- response
- headers/auth context as safely represented
- assertion
- backend readback/log correlation
- route source/freshness

### 4.6 Sufficiency
All required affected API/risk/VP coverage satisfied or explicit defect/hold. Repeated 404 guessing is a regression failure, not exploration success.

## 5. L4 - UI / Browser

### 5.1 Objective
Verify real user-visible page behavior through controlled Browser execution with page/network/backend evidence.

### 5.2 Required capabilities
- BrowserSkill/Playwright/Chromium
- fresh 4A runtime authentication
- DOM/action/network capture
- screenshot/trace
- API/backend oracle support where applicable

### 5.3 Mandatory real step rule
A UI case cannot be EXECUTED when zero meaningful page/action steps were executed.
`awaiting ui worker dispatch` cannot be promoted to PASS.

### 5.4 Coverage
- affected pages/components
- user operation paths
- positive/negative/boundary
- validation messages
- state linkage
- permissions/role visibility
- page->API integration
- backend state when relevant
- error/recovery behavior

### 5.5 Evidence
Per step:
- page/DOM target
- action/input
- Expected
- Actual
- Assertion
- screenshot/trace/network ref
- relevant API/backend evidence

### 5.6 Sufficiency
Required UI journeys/states/permissions and assertions covered; no critical unexecuted path. Browser launch/action success alone is not L4 sufficient.

## 6. L5 - Business E2E

### 6.1 Objective
Verify a coherent business outcome across UI/API/app/service/DB/system boundaries using one correlated journey.

### 6.2 Journey requirements
- business start condition
- data preparation
- fresh auth
- ordered user/system actions
- API/service sequence
- cross-application/system handoff where applicable
- backend state transitions
- final business state/readback
- cleanup/recovery
- trace/correlation identity

### 6.3 Coverage
- required critical journeys
- alternate/negative journeys where risk requires
- state transitions
- cross-app/system dependencies
- data/auth dependencies
- final-state business oracle

### 6.4 Evidence
One traceable journey evidence chain. Independent L2/L3/L4 green results cannot be combined after the fact to claim E2E PASS.

### 6.5 Sufficiency
All required critical journeys pass or have explicit valid product defects/hold with evidence. Fragmented layer execution is insufficient.

## 7. L6 - Performance / capacity / stability

### 7.1 Objective
Measure and evaluate system behavior under explicit workload and environment assumptions.

### 7.2 Required capabilities
- k6 or equivalent verified runner
- environment/runtime metrics as available
- data/auth setup appropriate to workload

### 7.3 Required model
- scenario/workload
- concurrency/arrival model
- duration
- test data
- environment/config snapshot
- warmup where appropriate
- NFR/SLA source

### 7.4 Metrics
- throughput TPS/RPS
- latency distribution including P95/P99 where relevant
- error rate
- timeout/failure
- resource metrics where available
- saturation/stability trends

### 7.5 NFR semantics
If authoritative threshold/SLA is absent:
`L6 = BASELINE_ONLY`.

PASS/FAIL may only be issued against explicit threshold with provenance. A short smoke load is not performance sufficiency.

## 8. L7 - Security / authorization

### 8.1 Objective
Verify authentication, authorization, privilege boundaries, negative security behavior, and applicable security threat controls.

### 8.2 Required coverage
- authentication
- role/permission matrix
- horizontal privilege
- vertical privilege
- direct API authorization
- negative/malformed input
- injection/XSS/applicable attack paths
- sensitive operation controls
- audit/security response

### 8.3 Scanner semantics
Scanner/ZAP availability is one capability only.
If scanner is unavailable, permission/authz/negative security tests must still execute when feasible.

Finding states:
- PROBE
- CANDIDATE
- CONFIRMED

### 8.4 Sufficiency
Configured threat/permission matrix covered; unresolved confirmed Critical/High findings drive Release HOLD according to policy.

## 9. Shared precondition/data contract

Every layer must declare preconditions and data requirements before dispatch.
Lifecycle:
Discover -> Build/Select -> Validate -> Lease -> Prepare -> Execute -> Readback -> Release/Cleanup -> Reuse/Revalidate.

Hidden manual data setup is not acceptable as normal autonomous execution.

## 10. Shared auth contract

Fresh 4A auth/re-auth is a runtime prerequisite, not an L-level.
No stale cookie/history fallback.
Explicit Human Lease only for unavoidable challenge.
Task identity survives re-auth.

## 11. Shared evidence contract

Every PASS assertion requires:
- Expected
- Actual
- assertion logic/result
- AVAILABLE evidence

Attempt history is append-only. Later green cannot erase earlier FAIL/BLOCKED.

## 12. Shared failure classes

PRODUCT, SCRIPT, SPEC, ORACLE, DATA, AUTH, ROUTE, ENVIRONMENT, DEPENDENCY, FLAKY, TOOL, MODEL, SESSION_RUNTIME, UNKNOWN.

Every layer maps failures to an owner/repair route. Blind retry is prohibited.

## 13. Cross-layer mission rule

Layer states remain independent.
Examples:
- L1 sufficient does not imply L2/L3/L4.
- L3+L4 sufficient does not imply L5 E2E.
- L6 BASELINE_ONLY cannot be represented as PASS.
- L7 scanner missing cannot mark all security tests blocked.

Mission evaluator determines which layers are applicable to a scope and whether their sufficiency is enough for TEST_SUFFICIENT.

## 14. Product acceptance for every layer

UI must expose:
- why this layer was applicable
- what cases/risks were covered
- attempts
- Expected/Actual/Assertion/Evidence
- coverage metrics/dimensions
- gaps/failures and ownership
- delta/re-run history
- final sufficiency reason

If only a final PASS/FAIL badge is visible, layer product acceptance fails.

## 15. Bank Reality requirement

Each layer must have at least one real bank Reality mission before it can be marked BANK_REALITY_VERIFIED/SUFFICIENT. CI doubles prove contracts only.

Reality mission must intentionally exercise at least one non-happy-path condition (coverage gap, product defect, data/auth/route recovery, or threshold decision as appropriate), proving the loop rather than a one-shot green run.