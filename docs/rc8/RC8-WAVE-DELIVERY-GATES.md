# RC8 Wave Delivery Gates

Status: FROZEN-CANDIDATE
Purpose: define delivery sequence and four-line Definition of Done so implementation breadth cannot outrun vertical completeness.

## 1. Four-line gate for every wave

A wave can close only when all applicable lines pass:

### A. Architecture Gate
- domain/state/protocol implemented
- identity/provenance correct
- leases/recovery/idempotency defined
- dependency/invalidation behavior defined
- persistence/restart semantics verified

### B. Testing Intelligence Gate
- specialist worker(s)
- real tool use
- evidence contract
- coverage model
- failure classification
- durable Gap/repair route
- sufficiency evaluator
- convergence behavior

### C. Product Gate
- Center projection/API
- list/detail UX
- Attempt/history
- Coverage/Gap/Defect/Evidence drilldown
- traceability
- no DSH-log dependency for understanding result

### D. Reality/Deployment Gate
- automated regression
- target-bank Reality case
- RC7 regression catalog checks
- restart/session-recovery where applicable
- complete package/integrity
- truthful status update in Closure Matrix/RTM

Missing one applicable gate => PARTIAL; never CLOSED.

## 2. W-A - Governance / Mission Kernel

### Scope
- No-Discount contract
- scoped status model TOOL/STAGE/LAYER/MISSION/RELEASE
- Mission Graph domain
- Gap domain/router skeleton
- Dependency/Invalidation skeleton
- Sufficiency evaluator contract
- Attempt append-only semantics
- Capability Closure Matrix / RC7 Regression Catalog
- product projection contract

### Acceptance
- impossible for Maven green to set L1 SUFFICIENT through domain/API
- impossible for CodeGraph tool VERIFIED to set Code Analysis SUFFICIENT
- invalidated result cannot remain current green
- UI/API exposes scoped status

## 3. W-B - First Autonomous L1 Vertical Slice

### Scope
- real requirement/code-risk input
- L1 test design
- ExecutableSpec
- script generation/validation
- Maven/JUnit + pytest as applicable
- JaCoCo/coverage.py
- changed-code coverage mapper
- failure classifier
- coverage Gap
- delta design/script
- targeted rerun
- mutation/assertion-strength for configured high-risk scope
- L1 sufficiency/convergence
- task/case/coverage/gap/report UI

### Mandatory Reality scenario
A real bank Java change where Attempt 1 leaves at least one changed critical branch/method gap; system automatically opens Gap, designs delta test, executes Attempt 2+, recalculates coverage and converges or explicitly remains insufficient.

One-shot all-green scenario is insufficient to close W-B.

## 4. W-C - Upstream Analysis / Design Sufficiency

### Scope
- RequirementAnalysisWorker + evaluator loop
- CodeAnalysis DSH semantic worker + evaluator/requery loop
- Risk/TestIntent/VerificationPoint model
- TestDesignWorker + coverage matrix + delta loop
- Oracle governance
- downstream invalidation
- requirement/code/design product pages

### Mandatory Reality
Use real SST/design docs + real Git change; demonstrate at least one analysis/design gap and repair round before downstream L1 dispatch.

## 5. W-D - L2 + Test Data / DB Closed Loop

### Scope
- Test Data lifecycle + Resource Lease
- DB adapters for applicable bank DBs
- repository/ORM/transaction/readback semantics
- L2 coverage/sufficiency
- DATA/ENV failure routing
- data/system-info UI

### Mandatory Reality
A real persistence scenario including before/after readback and at least one data/precondition repair or transaction/error-path validation.

## 6. W-E - L3 + Route + API + Auth Closed Loop

### Scope
- observe-first route discovery
- route knowledge freshness
- 4A runtime prerequisite
- HTTP/API worker
- request/response/business assertion/backend readback
- L3 coverage/sufficiency
- AUTH/ROUTE repair routes
- 测试接口/知识/product traces

### Mandatory Reality
Real bank API path discovered/verified without guessing; show expiry/stale-route or negative case handling and recovery where safe.

## 7. W-F - L4 Browser/UI Closed Loop

### Scope
- BrowserSkill/Playwright integration
- fresh auth
- real DOM/action/network/screenshot/trace
- page + backend oracle
- UI journey coverage/sufficiency
- zero-step/awaiting-worker regressions
- business flow capture

### Mandatory Reality
Real cfg-admin case with meaningful page actions, assertions and network evidence; zero-step proxy cannot satisfy execution.

## 8. W-G - L5 Business E2E

### Scope
- coherent journey orchestration across L2/L3/L4
- correlation/trace
- cross-app/system handoff
- final-state oracle/readback
- cleanup/recovery
- E2E sufficiency
- business-flow/System Behavior Graph productization

### Mandatory Reality
One real business journey from start condition to final business state. Fragmented layer results cannot substitute.

## 9. W-H - L6 Performance + L7 Security

### L6
- workload model
- k6/equivalent
- NFR/SLA provenance
- TPS/P95/P99/error/resource
- BASELINE_ONLY semantics

### L7
- authn/authz matrix
- horizontal/vertical privilege
- negative/security cases
- scanner where available
- finding lifecycle PROBE/CANDIDATE/CONFIRMED

### Mandatory Reality
At least one real performance baseline/threshold decision and one real authz/security scope with evidence. Scanner absence may not block non-scanner security cases.

## 10. W-I - Full Mission Sufficiency / Product Closure

### Scope
- applicable L1-L7 mission policy
- cross-stage gap routing
- dependency/invalidation
- defect/fix/regression loop
- report/release decision
- all 13 product pages backed by real projections
- global traceability

### Mandatory Reality
One real bank Requirement/SST mission from analysis through execution/convergence/report/release, including at least one route-back event and one product UI trace without reading DSH logs.

## 11. W-J - Multi-node / Knowledge / Skill / Recovery / Deployment Finalization

### Scope
- multiple users/nodes
- task/resource leases under concurrency
- durable queue/outage replay
- session rotation/handoff
- Knowledge lifecycle/resolver
- Skill Registry/distribution/qualification
- Center package
- Node package
- Windows + Xinchuang Linux platform gates
- architecture variants as required
- clean install/restart/upgrade/rollback
- Center-hosted package download

### Mandatory Reality
- concurrent independent TestRuns on multiple nodes
- DSH session loss/rotation with mission continuation
- Center/Node restart recovery
- complete package clean install
- upgrade preserving Node identity/Center data/assets
- rollback proof

## 12. Continuous gates across all waves

Every wave must update:
- Capability Closure Matrix
- Requirement Traceability Matrix
- RC7 Regression Catalog results
- Implementation Status
- Handoff Current

No wave may delete or weaken a requirement to achieve green CI.

## 13. Wave status semantics

- PLANNED
- IN_PROGRESS
- ARCHITECTURE_VERIFIED
- CI_VERIFIED
- BANK_REALITY_VERIFIED
- PRODUCT_VERIFIED
- CLOSED

A wave is CLOSED only after the four-line gate and all mandatory Reality scenarios pass.

## 14. Current restart point

Current RC8 has valuable foundation/tool evidence but does not satisfy W-B.

Existing reusable facts:
- W0 truth/identity foundations
- Center/Node lease/control foundation
- Artifact Sync foundation
- TOOL:MAVEN_JUNIT:BANK_REALITY_VERIFIED
- TOOL:CODEGRAPH:BANK_REALITY_VERIFIED
- partial Code Analysis semantic worker construction

Next functional construction wave after these design contracts are reviewed:
`W-B - First Autonomous L1 Vertical Slice`, while completing W-A Mission/Gap/Invalidation/Sufficiency kernel prerequisites as part of the slice.

No Browser-first breadth expansion before the first vertical autonomous loop is proven.