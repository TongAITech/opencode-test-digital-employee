# RC8 Mission Graph Contract

Status: FROZEN-CANDIDATE
Purpose: define the durable runtime state machine for autonomous testing. This is not a drawing-only architecture artifact; it is the authoritative execution model to be implemented in Center.

## 1. Mission identity

A Mission is a durable TestRun bound to:
- production_batch_id
- requirement/delivery scope
- system versions/applications/SSTs
- source/config snapshots
- applicable test layers
- policy version

DSH Session is not mission identity.

## 2. Canonical stage graph

```text
SCOPE_INTAKE
  ↓
REQUIREMENT_ANALYSIS
  ↓
REQUIREMENT_SUFFICIENCY
  ├─ GAP -> REQUIREMENT_ANALYSIS
  ↓
CODE_ANALYSIS
  ↓
CODE_SUFFICIENCY
  ├─ GAP -> CODE_ANALYSIS / REQUIREMENT_ANALYSIS
  ↓
RISK_TEST_MODEL
  ↓
TEST_DESIGN
  ↓
DESIGN_SUFFICIENCY
  ├─ GAP -> TEST_DESIGN / CODE_ANALYSIS / REQUIREMENT_ANALYSIS
  ↓
EXECUTABLE_SPEC
  ↓
PRECONDITION_DATA_PREP
  ↓
APPLICABLE_LAYER_EXECUTION (L1..L7)
  ↓
FAILURE_CLASSIFICATION + COVERAGE_EVALUATION
  ├─ PRODUCT -> DEFECT
  ├─ SCRIPT -> EXECUTABLE_SPEC/SCRIPT
  ├─ SPEC -> EXECUTABLE_SPEC
  ├─ ORACLE -> ORACLE_REVIEW
  ├─ DATA -> PRECONDITION_DATA_PREP
  ├─ AUTH -> AUTH_RECOVERY
  ├─ ROUTE -> ROUTE_DISCOVERY
  ├─ ENV/DEPENDENCY/TOOL -> ENV_RECOVERY
  ├─ CODE_UNCERTAIN -> CODE_ANALYSIS
  ├─ DESIGN_GAP/COVERAGE_GAP -> TEST_DESIGN
  ├─ REQUIREMENT_UNCLEAR -> REQUIREMENT_ANALYSIS
  └─ UNKNOWN -> DURABLE_GAP / HUMAN_GATE if policy permits
  ↓
DELTA_REPAIR / TARGETED_REEXECUTION
  ↓
MISSION_SUFFICIENCY
  ├─ INSUFFICIENT -> route unresolved gaps
  └─ SUFFICIENT -> REPORT_RELEASE
```

## 3. Stage instance model

Each StageInstance contains:
- stage_instance_id
- test_run_id
- stage_type
- scope_version
- input artifact/version refs
- assigned worker
- attempt_no
- status
- started_at/finished_at
- evaluator_id/policy_version
- output refs
- gap refs
- invalidation refs
- predecessor/successor IDs

No stage result may be overwritten. Rework creates a new StageInstance/version.

## 4. Stage states

Canonical states:
- PENDING
- READY
- LEASED
- EXECUTING
- EVIDENCE_PENDING
- EVALUATING
- INSUFFICIENT
- SUFFICIENT
- BLOCKED
- WAITING_HUMAN
- INVALIDATED
- SUPERSEDED
- FAILED_RUNTIME
- COMPLETED

`COMPLETED` is execution lifecycle, not sufficiency.

## 5. Attempt model

Every execution/re-analysis/design round creates a new Attempt.
Attempt contains:
- attempt_id
- parent stage/work item/case
- input snapshot/version
- producer worker/node/tool
- actions
- expected/actual/assertions
- evidence refs
- coverage output
- failure classification
- gaps/defects
- timestamps

Attempts are append-only.

## 6. Gap model

Gap is first-class:
- gap_id
- test_run_id
- source_stage/attempt/case/assertion
- gap_type
- severity
- description
- evidence_refs
- owner_stage
- repair_strategy
- invalidates[]
- status
- opened_at/closed_at
- closure_evidence

Canonical gap families:
- REQUIREMENT_UNCLEAR
- CODE_UNCERTAIN
- DESIGN_GAP
- COVERAGE_GAP
- SCRIPT
- SPEC
- ORACLE
- TEST_DATA
- PRECONDITION
- AUTH
- ROUTE
- ENVIRONMENT
- DEPENDENCY
- TOOL
- MODEL
- SESSION_RUNTIME
- FLAKY
- PRODUCT_DEFECT_LINKED
- UNKNOWN

## 7. Gap routing policy

Routing decisions are deterministic/policy-driven first and AI-assisted where needed.

Examples:
- CHANGED_BRANCH_UNCOVERED -> Test Design
- UNRESOLVED_CALL_CHAIN -> Code Analysis
- MISSING_BUSINESS_RULE -> Requirement Analysis
- STALE_ROUTE -> Route Discovery
- EXPIRED_AUTH -> Auth Runtime
- DATA_STATE_MISSING -> Test Data
- ASSERTION_EXPECTED_UNSOURCED -> Oracle Review
- PRODUCT_ASSERTION_MISMATCH -> Defect

No generic `retry same worker` route is allowed without a failure class and retry policy.

## 8. Invalidation graph

Every artifact/output declares dependencies.

Examples:
- RequirementAnalysis v2 invalidates dependent Risk/TestDesign/ExecutableSpec/Sufficiency results created from v1 when semantic delta affects them.
- CodeAnalysis v2 with new impacted method invalidates affected design/coverage/L1-L7 sufficiency.
- Oracle v2 invalidates PASS assertions based on Oracle v1.
- RouteKnowledge STALE invalidates future reuse qualification; prior historical execution remains historical truth but cannot prove current freshness.

Invalidation never deletes history; it creates runtime/domain state indicating old results are no longer current proof.

## 9. Sufficiency evaluator contract

Every evaluation returns:
- evaluator_id
- policy_version
- scope
- dimensions[]
- metrics[]
- satisfied_requirements[]
- unsatisfied_requirements[]
- unresolved_gap_ids[]
- accepted_waiver_ids[]
- result = SUFFICIENT / INSUFFICIENT / BASELINE_ONLY / BLOCKED
- explanation with evidence refs

Model prose alone cannot set result.

## 10. Mission sufficiency

`TEST_SUFFICIENT=YES` requires:
- applicable upstream analyses sufficient
- design sufficient
- applicable L1-L7 sufficiency results satisfy policy
- required evidence AVAILABLE
- unresolved required critical gaps = 0
- required product defects linked and release implications known
- no stale/invalidation blocking current result
- explicit governed waiver/hold for permitted residuals

No `all WorkItems completed` shortcut.

## 11. Release decision

Separate object:
- PASS
- HOLD
- BLOCKED

Examples:
- TEST_SUFFICIENT + no blocking defects -> PASS candidate
- TEST_SUFFICIENT + confirmed blocking product defect -> HOLD
- TEST_INSUFFICIENT -> HOLD/BLOCKED per policy

Testing can be successfully executed and sufficient while release remains HOLD due to real defects.

## 12. Human Gate / waiver

Human involvement is explicit:
- human_gate_id
- reason
- requested decision/action
- owner
- timeout
- evidence
- result

No implicit `wait for manual` completion.

Waiver contains:
- waived requirement/gap
- risk statement
- approver
- expiry/scope
- evidence

A waiver cannot fabricate PASS; it changes mission/release policy outcome explicitly.

## 13. Resource/state recovery

Mission must survive:
- DSH session rotation
- DSH crash
- Node process restart
- Center restart
- temporary Center outage

Recovery uses durable TestRun/Stage/WorkItem/Attempt/Gap/Artifact state, local queues, and leases.

Lost lease does not automatically replay non-idempotent actions. Recovery policy evaluates last runtime truth and action risk.

## 14. Context budget/rotation

Workers are bounded-context. Before budget threshold:
- checkpoint durable facts
- produce handoff summary with artifact/knowledge refs
- close/rotate session
- start new Worker session on same WorkItem/stage

Session continuation is never based solely on chat history.

## 15. Runtime event families

At minimum:
- MISSION_STARTED
- STAGE_READY/STARTED/COMPLETED
- WORKITEM_LEASED/STARTED/COMPLETED
- ATTEMPT_STARTED/COMPLETED
- ACTION_EXECUTED
- ASSERTION_EVALUATED
- COVERAGE_COLLECTED
- GAP_OPENED/ROUTED/CLOSED
- DEFECT_CANDIDATE_CREATED/CONFIRMED
- ARTIFACT_AVAILABLE
- STAGE_INVALIDATED
- SUFFICIENCY_EVALUATED
- HUMAN_GATE_OPENED/CLOSED
- MISSION_SUFFICIENT/INSUFFICIENT
- RELEASE_DECISION_RECORDED

All are runtime facts with producer/provenance.

## 16. Mission product projection

测试任务 page must show:
- stage graph/current stage
- Attempt timeline
- active/past workers/nodes
- coverage evolution
- gaps and route-back arrows
- invalidated/superseded results
- defects
- sufficiency decisions
- release decision

A final status badge without the loop history fails product acceptance.

## 17. First Reality mission acceptance

The first autonomous vertical mission MUST intentionally include at least one gap requiring a second Attempt. A one-shot green mission proves execution but not autonomous closure.

Recommended first L1 Reality scenario:
1. real Java change
2. initial tests leave a changed branch uncovered
3. JaCoCo detects gap
4. Gap Router sends to Test Design
5. delta case/script generated
6. targeted re-run
7. branch coverage closes
8. mission/layer sufficiency recalculated
9. full history visible in Center UI

Only this type of test proves the closed-loop model.