# G4 — Real Execution & Test Goal Convergence Formal Detailed Design v1

**Status:** FORMAL DETAILED DESIGN / IMPLEMENTATION-READY CANDIDATE  
**Governance owner:** 00.8｜ChatGPT Harness 总控与架构治理｜R5  
**Recommended engineering WorkItem:** 10.G4｜G4 Real Execution & Test Goal Convergence Product Integration WorkItem  
**Architecture baseline:** v7 / FROZEN  
**Prerequisites:** G1 = ENGINEERING_PASS; G2 = ENGINEERING_PASS; G2.1 = ENGINEERING_PASS; G3 = ENGINEERING_PASS / FROZEN  
**Durable truth:** R1 Event Stream remains the sole durable runtime truth  
**Session lifecycle authority:** G2.1 Session Router / Session Supervisor / Control Loop / R2.5  
**Testing intelligence authority:** G3  
**Actual incremental coverage authority:** Bank Incremental Code Coverage Platform  
**Defect truth boundary:** G5 remains HOLD during G4  
**Continuous closed-loop boundary:** G6 remains HOLD during G4  
**Bank readiness:** NO

---

## 0. G4 Mission

G4 is not “run test cases”.

G4 turns the existing G1–G3 foundation into a real execution-and-convergence loop:

```text
Testing Goal
  -> G3 Strategy / Standard Cases
  -> G4 Real Execution
  -> Oracle + Evidence
  -> Bank Actual Incremental Coverage Measurement
  -> Goal Evaluation
  -> Coverage / Risk / Blocker Gap
  -> G3 Replan
  -> Next Execution Batch
  -> ...
  -> Goal Satisfied / Completed With Accepted Gap / Explicitly Blocked
```

The first measurable goal family is incremental code coverage, for example:

```text
Effective Incremental Coverage >= 95%
```

but G4 must never optimize only the percentage. Completion also requires no unresolved critical changed-code gap and no unresolved mandatory execution blocker.

G4 keeps the two product North Stars:

1. **Reach** — reduce actual uncovered effective incremental code according to the bank coverage platform.
2. **Find** — create high-quality real execution observations that can become valid defect investigations in G5.

`CASE_EXECUTED != TEST_GOAL_SATISFIED`  
`COVERAGE_PERCENT >= TARGET != AUTOMATIC_COMPLETE`  
`TEST_FAIL != CONFIRMED_DEFECT`  
`G4_EXECUTION_OBSERVATION != G5_DEFECT_TRUTH`

---

# 1. Frozen boundaries inherited from G1–G3

G4 must preserve all of the following:

1. `R1_EVENT_STREAM = SOLE_DURABLE_RUNTIME_TRUTH`.
2. `legacy aitest.db` must not become a product write path.
3. G4 must not create a second Mission/Plan/Task/Attempt/Session truth.
4. All Worker Sessions are routed by G2.1; Executors must not create/manage their own Sessions.
5. G3 owns requirement/change/coverage reasoning, test strategy, DefectHypothesis and StandardTestCase design.
6. G4 may execute cases and emit observations, but must not confirm Defects; G5 remains defect-truth authority.
7. G6 continuous trigger/closed loop remains HOLD.
8. Actual incremental coverage can only come from the bank Incremental Code Coverage Platform.
9. Static Git/CodeGraph analysis remains Change Truth / Coverage Objective only.
10. Human credentials, OTP, captcha content, face images and passwords must never become durable testing knowledge.
11. `DOM_SCAN_IS_NOT_PAGE_MODEL`.
12. `AUTH_IS_RUNTIME_PREREQUISITE`.
13. `E2E_VERIFIED_REQUIRES_REAL_RUNTIME_EXECUTION`.
14. `PLAN_COMPLETE != TEST_SUFFICIENT`.

---

# 2. Core product outcome: Test Goal Convergence

## 2.1 TestingGoal

G4 introduces a durable `TestingGoal` as an additive R1 Event Stream fact.

Minimum fields:

```text
goal_id
mission_id
project_id
release_id
requirement_scope[]
affected_applications[]

goal_type
  - COVERAGE_CONVERGENCE
  - FOCUSED_CASE_EXECUTION
  - API_EXECUTION
  - UI_EXECUTION
  - SECURITY_EXECUTION
  - PERFORMANCE_EXECUTION
  - MIXED

coverage_policy:
  source = BANK_INCREMENTAL_COVERAGE_PLATFORM
  target_pct
  aggregation_policy
  critical_gap_policy

execution_policy:
  allowed_capabilities[]
  safety_constraints
  batch_policy
  retry_policy
  time/budget constraints

defect_discovery_objective:
  enabled
  high_value_hypothesis_refs[]

status
created_at
updated_at
```

### Default coverage policy

For a goal such as `95%`, the default must be:

```text
PER_AFFECTED_APPLICATION
```

not an average that can hide a badly covered application.

A goal is not satisfied merely because the weighted/average percentage is >= 95%.

Default completion requirement:

```text
for each affected application:
  actual effective incremental coverage >= target_pct

AND

no unresolved CRITICAL changed-code coverage gap

AND

no mandatory execution remains READY_NOT_EXECUTED

AND

no required measurement is pending

AND

no unresolved mandatory HumanTask/HumanGate blocks the goal
```

A different aggregation policy is allowed only if it is explicit and durable.

---

# 3. G4 core state model

## 3.1 TestingGoal state

```text
PROPOSED
-> ACTIVE
-> EXECUTING
-> MEASURING
-> REPLANNING
-> EXECUTING
...

Possible waiting states:
WAITING_HUMAN
WAITING_COVERAGE_REFRESH
WAITING_ENVIRONMENT
WAITING_APPROVAL

Terminal:
SATISFIED
COMPLETED_WITH_ACCEPTED_GAP
BLOCKED
CANCELLED
STOPPED
```

A single blocked branch must not automatically force the entire Mission into `WAITING_HUMAN`. Independent ready work remains schedulable through G2.

## 3.2 ExecutionAttempt state

Reuse the canonical ExecutionAttempt; G4 adds execution semantics around it:

```text
READY
-> RUNNING
-> SUSPENDED_HUMAN
-> WAITING_EXTERNAL
-> RUNNING
-> PASSED | FAILED | ERROR | BLOCKED | CANCELLED
```

`FAILED` means the expected oracle did not hold. It does not mean confirmed defect.

## 3.3 Step cursor

Each real case execution must durably maintain:

```text
case_id
case_version
attempt_id
current_step_index
completed_step_ids[]
pending_step_id
last_safe_checkpoint
```

Human takeover, process restart, OpenCode Session rotation and Control Loop restart must recover from this cursor instead of restarting the entire case unless the case contract requires restart.

---

# 4. Execution architecture

```text
User / Test Goal
       |
       v
G2 Mission / Plan / Scheduler
       |
       v
G2.1 Session Router
       |
       v
G4 Executor Session
       |
       v
G4 Execution Coordinator
       |
       +---------------------------+
       |            |              |
       v            v              v
 Browser/UI      API/HTTP       DB/Data
       |            |              |
       +------------+--------------+
                    |
              CAT / Log / Manual
                    |
                    v
              Oracle Evaluator
                    |
                    v
              Evidence Recorder
                    |
                    v
              R1 Event Stream
                    |
                    v
        Test Objective Controller
                    |
              Coverage Measurement
                    |
                    v
           G3 Replan when needed
```

There is still only one canonical runtime.

---

# 5. Capability Executor model

G4 must use capabilities, not create one new Runtime per test type.

## 5.1 Common Executor contract

All executors implement a canonical contract:

```text
capability_id
capability_status = AVAILABLE | PARTIAL | UNAVAILABLE | AUTH_REQUIRED | APPROVAL_REQUIRED

prepare(step, runtime_facts)
execute(step, execution_context)
observe(result)
collect_evidence(result)
cleanup(result)

must expose:
- safety profile
- auth requirements
- input provenance
- side-effect classification
- retry semantics
- evidence channels
```

Unknown capability must fail closed.

## 5.2 Browser/UI Executor

Responsibilities:

- reuse controlled browser context;
- navigate only within authorized test scope;
- validate page identity before actions;
- execute ordered UI steps;
- capture screenshots/DOM/network refs according to evidence policy;
- preserve auth context;
- integrate BrowserLease and Human Takeover;
- support Journey/E2E execution through existing frozen R3.5/E3 foundations;
- never treat a raw DOM scan as the canonical page model.

## 5.3 API Executor

Responsibilities:

- exact endpoint/method/headers/body from governed test input;
- auth-context reuse;
- request/response evidence;
- latency measurement;
- idempotency/retry contract;
- safe handling of mutating methods;
- explicit distinction between transport failure, business failure and oracle failure.

It must not guess an API address.

## 5.4 DB/Data Executor

Default is read-only.

Writes require:

```text
explicit test intent
AND allowed environment
AND authorized scope
AND Human Gate / project policy approval when required
```

Evidence should include safe query/row/result references with secret/sensitive-field redaction.

No destructive cleanup unless it is explicitly governed.

## 5.5 CAT / Log Executor

Read-only by default:

- authenticated CAT/log session;
- trace/query correlation;
- timestamp / request-id / trace-id provenance;
- evidence references;
- Human Gate on auth expiry.

## 5.6 Manual Executor

Represents unavoidable human actions:

- environment action;
- test-data preparation;
- business decision;
- external-system operation;
- browser takeover;
- physical/offline action.

It is a durable Human Gate, not a chat-memory note.

## 5.7 Security Executor

G3 provides the design profile; G4 executes only when all of these exist:

```text
authorized_scope
target_environment
allowed_methods/tools
rate/volume limits
destructive=false by default
oracle
stop_conditions
```

No authorization -> fail closed.

Security execution observations remain G4 evidence; confirmed vulnerabilities remain G5 defect truth.

## 5.8 Performance Executor

G3 provides:

```text
SLO / baseline
load model
concurrency / rate / duration
warmup
test data
latency/error/resource oracle
stop conditions
```

G4 may bind to k6 or another verified provider if available.

No SLO / no authorized scope / no resource limits -> fail closed.

---

# 6. Evidence & Oracle model

Every executed step must create a durable execution result with:

```text
step_id
attempt_id
started_at
completed_at
executor_capability
input_ref
expected
actual
oracle_result
oracle_reason
evidence_refs[]
source_identity
execution_node
auth_context_ref (non-secret)
side_effect_summary
```

Oracle statuses:

```text
PASS
FAIL
INCONCLUSIVE
BLOCKED
ERROR
```

Evidence may be stored outside the Event Stream as immutable artifacts, but R1 must contain authoritative typed references and lifecycle events.

G4 must not create a second evidence-truth database.

## Required evidence examples

UI:
- screenshot
- page identity
- DOM/state refs where appropriate
- network refs
- business-state observation

API:
- request/response
- status
- business code
- latency
- correlation id

DB:
- query identity
- safe row/result snapshot ref

CAT/log:
- trace refs
- correlated log refs

Manual:
- human action completion event
- resume verification evidence

---

# 7. Human Gate and controlled-browser takeover

This is a mandatory G4 capability.

## 7.1 Fundamental invariant

```text
WAITING_HUMAN != RUNNING_AI_TURN
HUMAN_TAKEOVER_MUST_YIELD_CHAT_TURN = TRUE
```

When human action is required:

1. persist Human Gate;
2. persist ExecutionAttempt / Step Cursor;
3. transfer browser lease when applicable;
4. emit user-facing instruction;
5. **end the current AI turn** so OpenCode input becomes sendable.

A tool call must never remain blocked for minutes/hours waiting for a human.

## 7.2 BrowserLease state machine

```text
AI_CONTROLLED
-> TAKEOVER_REQUESTED
-> HUMAN_CONTROLLED
-> HUMAN_COMPLETED_PENDING_VERIFY
-> AI_RECLAIMING
-> AI_CONTROLLED

Exceptional:
CONTEXT_EXPIRED
BLOCKED
CANCELLED
```

While `HUMAN_CONTROLLED`:

```text
AI click = forbidden
AI navigation = forbidden
AI form-fill = forbidden
AI close = forbidden
automation timeout must not close the human-owned browser
```

## 7.3 Same-browser-context requirement

Human takeover must use the same controlled browser context/window that AI opened.

Forbidden pattern:

```text
AI browser A -> user logs into unrelated browser B -> AI browser A still unauthenticated
```

The authenticated cookie/session must remain on the governed browser context.

## 7.4 HumanBrowserTakeoverRequest

Durable fields:

```text
takeover_id
human_gate_id
mission_id
task_id
attempt_id
step_id
browser_context_id
execution_node_id
reason
required_action
current_url
allowed_scope
resume_mode
resume_condition
status
```

## 7.5 Resume modes

```text
AUTO
EXPLICIT
AUTO_OR_EXPLICIT
```

Examples:

- 4A login: `AUTO_OR_EXPLICIT`
- Coverage platform login: `AUTO_OR_EXPLICIT`
- offline data preparation: `EXPLICIT`
- business decision: `EXPLICIT`

## 7.6 Explicit completion

User may send:

```text
完成
```

or a future UI may invoke `complete_human_gate(gate_id)`.

If exactly one open compatible gate exists, Runtime can resolve it.

If multiple gates exist, Runtime must ask which one; never guess.

## 7.7 Auto-resume

A background Human Gate / Browser Supervisor may observe a deterministic `resume_condition`.

Example:

```text
login page disappeared
AND authenticated landing marker exists
AND protected query succeeds
```

Then:

```text
verify
-> HUMAN_GATE_COMPLETED
-> BrowserLease HUMAN -> AI
-> wake Scheduler / Objective Controller
-> continue same Attempt / Step Cursor
```

This must not depend on the original Conversation or original OpenCode Session.

## 7.8 Revalidation after human control

Human may navigate or alter business state.

After reclaiming:

```text
validate current URL
validate auth state
validate page identity
validate expected business state
```

Possible result:

```text
REPOSITION_ONLY
STATE_CHANGED_BY_HUMAN
RESUME_SAFE
RESUME_BLOCKED
```

No silent assumptions.

## 7.9 Secrets and evidence

Never persist:

- password;
- OTP;
- captcha response;
- face image;
- secret question answers.

During sensitive entry, screenshot/video evidence must be suspended or redacted.

Persist only facts such as:

```text
AUTH_COMPLETED_BY_HUMAN
platform
time
browser_context_id
verification result
```

---

# 8. ExecutionBatch

Coverage should not be queried after every normal case.

Introduce durable `ExecutionBatch`:

```text
batch_id
goal_id
case_refs[]
target_application
target_coverage_gaps[]
target_hypotheses[]
expected_value
status
started_at
completed_at
```

Batch selection comes from G3 strategy.

G4 decides execution batching based on:

- dependency/order;
- target application;
- shared setup/auth;
- measurement cost;
- risk;
- safety limits.

G4 must not invent new case semantics.

---

# 9. Bank Actual Coverage measurement

G4 uses the existing G3 Bank Incremental Coverage Provider contract.

## 9.1 Measurement flow

```text
ExecutionBatch COMPLETED
-> CoverageMeasurementRequested
-> auth check
-> Bank Platform query
-> CoverageSnapshot
-> freshness / source identity check
-> Goal Evaluation
```

## 9.2 Coverage freshness

Coverage platform data may update asynchronously.

States:

```text
REQUESTED
AUTH_REQUIRED
WAITING_REFRESH
AVAILABLE
STALE
SOURCE_UNAVAILABLE
SOURCE_IDENTITY_MISMATCH
FAILED
```

A stale snapshot must not be interpreted as “the new cases added no coverage”.

Field Validation must determine real refresh/latency behavior.

## 9.3 Source identity

Every snapshot must retain:

```text
application
target_version
baseline_identity
observed_at
provider_profile
source mode
```

If only `master` alias exists:

```text
baseline_identity = MASTER_ALIAS_ONLY
```

Cross-time numeric trend comparisons remain prohibited unless source equivalence is proven.

---

# 10. Test Objective Controller

G4 introduces a non-LLM runtime service:

```text
TestObjectiveController
```

It is not a new Agent and not a new truth store.

It reads R1 Event Stream and decides whether the test goal is converging.

## 10.1 Events that wake the controller

Examples:

```text
TESTING_GOAL_CREATED
CASE_REVIEW_APPROVED
EXECUTION_BATCH_COMPLETED
COVERAGE_SNAPSHOT_AVAILABLE
COVERAGE_SNAPSHOT_STALE
HUMAN_GATE_COMPLETED
ENVIRONMENT_RECOVERED
RISK_ACCEPTANCE_DECIDED
```

## 10.2 Main loop

```text
read TestingGoal
read current G3 strategy
read executed cases and evidence
read latest actual coverage snapshot
read open blockers/human gates

if no executable batch:
    request G3 replan or wait/block

execute batch
measure coverage
evaluate progress

if goal satisfied:
    SATISFIED

elif progress exists:
    request/execute next G3-ranked batch

elif plateau:
    classify gap cause
    request targeted G3 replan / human resolution / risk acceptance

else:
    BLOCKED / WAIT
```

G4 never generates new StandardTestCase logic itself.

---

# 11. Coverage convergence algorithm

## 11.1 Coverage goal example

User:

```text
测试 1.0.2，目标有效增量覆盖率 95%，重点发现真实缺陷。
```

Durable policy:

```text
target_pct = 95
source = BANK_INCREMENTAL_COVERAGE_PLATFORM
aggregation = PER_AFFECTED_APPLICATION
critical_gap_policy = ZERO_UNRESOLVED_CRITICAL
```

## 11.2 Iteration

Each iteration stores:

```text
iteration_id
goal_id
coverage_before
coverage_after
coverage_delta
new_changed_lines_covered
remaining_coverage_gaps[]
cases_executed[]
new_execution_failures[]
new_observations[]
human_blockers[]
strategy_revision_ref
status
```

Iteration status:

```text
PROGRESSING
PLATEAU
BLOCKED
TARGET_REACHED
WAITING_MEASUREMENT
```

## 11.3 Gap classification

Remaining coverage gaps must be classified, for example:

```text
TEST_DESIGN_GAP
TEST_DATA_GAP
AUTH_GAP
PERMISSION_GAP
ENVIRONMENT_GAP
SOURCE_DATA_GAP
DEPLOYMENT_GAP
MANUAL_ACTION_REQUIRED
POSSIBLY_UNREACHABLE
COVERAGE_SOURCE_STALE
COVERAGE_SOURCE_MISMATCH
UNKNOWN
```

Unknown -> explicit HumanTask / investigation, not guess.

## 11.4 Plateau protection

G4 must prevent infinite loops.

Plateau policy is configurable, not hard-coded into business truth.

A plateau is detected only from fresh comparable coverage snapshots after non-redundant execution batches.

When plateau is reached:

```text
do not blindly rerun same cases
-> diagnose gap cause
-> G3 targeted replan
-> resolve human/environment blocker
-> or request risk acceptance
```

---

# 12. G3 Replan contract

G4 may request G3 replan with durable evidence:

```text
REPLAN_REQUEST
goal_id
strategy_revision
actual_coverage_snapshot_ref
remaining_coverage_gap_refs[]
execution_result_refs[]
unresolved_observation_refs[]
blocker_refs[]
budget/safety status
```

G3 then owns:

- new test strategy;
- new case design;
- duplicate suppression;
- changed priority;
- new DefectHypothesis discriminating cases.

G4 only executes the governed result.

---

# 13. Goal completion and accepted gaps

## 13.1 SATISFIED

Default:

```text
all affected apps >= target
AND no unresolved critical coverage gap
AND no required execution pending
AND no required measurement pending
AND no mandatory blocker/human gate pending
```

## 13.2 COMPLETED_WITH_ACCEPTED_GAP

Example:

```text
target = 95%
actual = 93.8%
remaining 6 lines:
  4 = verified unreachable environment-only branch
  2 = external system unavailable
```

Completion is allowed only after explicit human `RISK_ACCEPTANCE`.

The system must report:

- requested target;
- actual;
- exact remaining files/classes/lines where available;
- why they remain;
- who/when accepted;
- risk.

It must never display 93.8% as if 95% were achieved.

---

# 14. G4 observation vs G5 defect truth

G4 may emit:

```text
UnexpectedObservation
OracleFailure
ExecutionAnomaly
ReproSignalCandidate
EvidenceBundle
```

It may strengthen an existing G3 `DefectHypothesis`.

It may not emit:

```text
CONFIRMED_DEFECT
FINAL_ROOT_CAUSE
DEFECT_CLOSED
```

Those belong to G5.

This boundary must be enforced in product tools and tests.

---

# 15. Interaction with G2.1

Two different control loops must remain distinct.

## G2.1 Session Control Loop

Manages:

```text
Session health
Session observation
rotation
resume
reconciliation
LogicalAgent / Attempt / Session lifecycle
```

## G4 Test Objective Controller

Manages:

```text
TestingGoal
execution progress
coverage measurement
coverage delta
replan
plateau
blocker/risk acceptance
```

Both read/write through R1 Event Stream.

Neither owns a second state database.

---

# 16. OpenCode product behavior

## 16.1 Normal autonomous goal

User:

```text
测试这个版本，增量覆盖率目标95%。
```

Expected product flow:

```text
Director
-> durable TestingGoal
-> G3 strategy
-> approved/ready cases
-> G2/G2.1 route executor work
-> G4 execute
-> evidence
-> coverage query
-> objective evaluation
-> G3 replan if needed
-> repeat
```

## 16.2 Focused execution

User:

```text
执行 TC-018
```

G4 creates governed execution work for that case only. It does not bypass R1/G2/G2.1.

## 16.3 Human takeover chat behavior

When human action is needed, AI must respond and end the current turn:

```text
需要你在已打开的受控浏览器完成4A认证。
我已暂停浏览器自动操作。
完成后可以告诉我“完成”，或等待系统自动验证并恢复。
```

At this point the OpenCode input must be sendable.

---

# 17. G4 implementation plan

Implementation must occur in a dedicated `10.G4` WorkItem, not in 00.8.

## G4-A — Goal Contracts & R1 extension

Implement:

- `TestingGoal`
- goal policy/status
- TestLoopIteration
- GoalEvaluation
- blocker/gap facts
- additive R1 extension/projection
- product status/query surfaces

Acceptance:
- new process can recover active goal from R1;
- no second DB;
- G1 truth regression PASS.

## G4-B — Case Execution Runtime

Implement:

- governed execution request;
- canonical ExecutionAttempt binding;
- Step Cursor;
- pause/resume;
- outcome transition;
- case/version identity;
- idempotent resume after process crash.

Acceptance:
- mid-case restart resumes same Attempt/Step;
- no duplicate case execution without explicit retry/replay.

## G4-C — Capability Executor Framework

Implement common executor interfaces and capability registry.

Initial capabilities:
- Browser/UI
- API
- DB/Data
- CAT/Log
- Manual
- Security
- Performance

Acceptance:
- AVAILABLE/PARTIAL/UNAVAILABLE/AUTH_REQUIRED/APPROVAL_REQUIRED explicit;
- unknown provider fails closed.

## G4-D — Browser/UI Execution + BrowserLease

Implement:

- controlled browser context registry;
- BrowserLease;
- HumanBrowserTakeoverRequest;
- same-context takeover;
- pause automation;
- state revalidation;
- explicit/auto resume;
- sensitive-evidence suppression.

Acceptance:
- Human takeover ends AI turn;
- user can send a message;
- same browser context retained;
- AI cannot act while HUMAN_CONTROLLED;
- new OpenCode Session/process can complete the same Human Gate;
- original ExecutionAttempt/Step resumes.

## G4-E — API / DB / CAT / Manual Executors

Implement real execution contracts with deterministic providers for construction testing.

Acceptance:
- exact input/provenance;
- side-effect policy;
- evidence refs;
- auth/approval Human Gates;
- fail closed on missing binding.

## G4-F — Oracle & Evidence

Implement:

- step oracle;
- cross-source oracle;
- evidence bundle/reference model;
- redaction/sensitive handling;
- Observation/Anomaly output.

Acceptance:
- every executed step has expected/actual/oracle/evidence;
- no FAIL => Confirmed Defect shortcut.

## G4-G — Security / Performance Execution

Activate only from G3 governed profiles.

Security acceptance:
- authorized scope required;
- rate/safety limit required;
- destructive disabled by default.

Performance acceptance:
- SLO/load model/limits required;
- stop conditions enforced;
- no default invented SLA.

## G4-H — ExecutionBatch

Implement batch creation/execution and target-gap linkage.

Acceptance:
- cases retain G3 value links;
- batch completion is durable;
- restart does not duplicate completed case work.

## G4-I — Actual Coverage Measurement

Reuse G3 bank provider contract.

Implement:
- post-batch measurement requests;
- auth Human Gate;
- stale/waiting-refresh handling;
- source identity;
- application/file/class/line snapshot refs.

Construction uses deterministic fixtures. Bank parity remains Field Validation.

## G4-J — Test Objective Controller

Implement event-driven controller over R1.

Acceptance:
- after batch completion it measures;
- after fresh snapshot it evaluates;
- target not reached -> G3 replan request;
- target reached but critical gap remains -> not complete;
- target and critical policy satisfied -> SATISFIED.

## G4-K — Plateau / Blocker / Risk Acceptance

Implement:
- progress/plateau classification;
- gap-cause classification;
- independent work continues while one branch waits human;
- explicit risk acceptance for unreachable/blocked residuals.

Acceptance:
- no infinite blind rerun;
- one Human Gate does not freeze unrelated ready tasks.

## G4-L — Product Entry / Tools / Commands / Agent contracts

Open only authorized G4 actions.

Maintain:
- G5 Defect Truth HOLD;
- G6 closed loop HOLD;
- no Agent-owned Session lifecycle;
- command -> tool -> product_entry -> R1 contract tests.

## G4-M — Product-level E2E + independent review

Mandatory construction E2E:

```text
User/OpenCode
-> TestingGoal 95%
-> G3 strategy/cases
-> G2.1 Router
-> G4 executor
-> execution evidence
-> bank coverage fixture snapshot
-> Goal Evaluation
-> G3 replan
-> second batch
-> coverage target reached
```

Also force:

- process restart mid-case;
- Session rotation;
- Control Loop restart;
- Human browser takeover;
- AI turn yield;
- explicit completion;
- auto-resume;
- auth expiry;
- stale coverage snapshot;
- multi-application target;
- plateau;
- risk acceptance;
- provider unavailable;
- G5 boundary.

---

# 18. G4 formal Product Gate

G4 can be an Engineering PASS candidate only if fresh evidence proves at least:

1. R1 Event Stream remains sole durable truth.
2. legacy `aitest.db` product write remains forbidden.
3. TestingGoal is durable and restartable.
4. coverage target is policy-driven, not conversation memory.
5. per-affected-application target policy works.
6. critical uncovered code blocks completion despite percentage target.
7. canonical ExecutionAttempt is used.
8. Step Cursor survives restart.
9. case identity/version is preserved.
10. all execution Sessions route through G2.1.
11. no Executor owns Session lifecycle.
12. Browser/UI executor is governed.
13. API executor is governed.
14. DB executor fails closed without required authorization.
15. CAT/log auth gaps create Human Gate.
16. Human/Manual executor is durable.
17. Human takeover yields current AI turn.
18. same browser context is preserved through human takeover.
19. AI cannot control browser while lease owner = HUMAN.
20. explicit human completion verifies resume condition.
21. auto-resume verifies resume condition.
22. multiple open Human Gates are not guessed.
23. sensitive auth data is not durable evidence.
24. human completion resumes original Attempt/Step.
25. unrelated work can continue while one branch waits human.
26. every executed step has expected/actual/oracle/evidence.
27. FAIL never becomes Confirmed Defect in G4.
28. ExecutionBatch is durable.
29. Actual Coverage comes only from bank provider semantics.
30. stale coverage is not treated as no-gain.
31. `MASTER_ALIAS_ONLY` semantics remain correct.
32. Test Objective Controller measures and evaluates after batch completion.
33. unmet target creates governed G3 replan request.
34. G4 does not author replacement test cases itself.
35. Coverage iteration records before/after/delta.
36. plateau prevents blind repeated execution.
37. blocker classification is explicit.
38. risk acceptance is human-authorized and durable.
39. `SATISFIED` cannot occur with unresolved critical gap.
40. `COMPLETED_WITH_ACCEPTED_GAP` reports target/actual/residual risk.
41. security execution fails closed without scope/safety limits.
42. performance execution fails closed without SLO/load/stop limits.
43. G5 defect truth remains HOLD.
44. G6 continuous closed loop remains HOLD.
45. G1 regression PASS.
46. G2 regression PASS.
47. G2.1 regression PASS.
48. G3 regression PASS.
49. process restart recovery PASS.
50. Session rotation / Control Loop restart recovery PASS.
51. command/tool/product-entry alignment PASS.
52. Architecture Drift = NO.

---

# 19. Mandatory independent post-implementation code review

After implementation, the WorkItem must not self-close solely because tests are green.

An independent design-to-code review must inspect actual code and product entry for **G1 + G2 + G2.1 + G3 + G4**.

## G1 review

Verify:

- one canonical product entry;
- sole physical Event Stream authority;
- no workspace-local fallback DB;
- no legacy `aitest.db` product writes;
- process-launch isolation remains intact.

## G2 review

Verify:

- Mission/Goal/Plan/Task governance;
- Planner -> Scheduler handoff;
- worker outcome -> next task;
- Mission dedup/resume;
- no hidden second orchestration path.

## G2.1 review

Verify:

- Session Router remains sole lifecycle routing authority;
- Supervisor/Control Loop remains background/autonomous;
- rotation/reconciliation/root Attempt preservation;
- G4 executors did not add bespoke Session creation.

## G3 review

Verify:

- Requirement/Code/Coverage/Test Strategy facts remain correct;
- static change is still not Actual Coverage;
- bank provider semantics remain canonical;
- CaseValueLink / Reach+Find logic not bypassed;
- G4 execution activation did not mutate G3 DefectHypothesis into Defect Truth.

## G4 review

Verify:

- goal convergence works through real product entry;
- Human takeover truly yields AI turn;
- BrowserLease enforced;
- Attempt/Step recovery;
- coverage measurement/replan;
- plateau/blocker/risk acceptance;
- evidence/oracle integrity;
- security/performance safety boundaries;
- G5/G6 still HOLD.

---

# 20. Fresh regression expectations after G4

The final G4 WorkItem must output:

1. `G4_IMPLEMENTATION_EVIDENCE_PACK.md/json`
2. `G4_DESIGN_TO_CODE_REVIEW.md`
3. `G1_G2_G2_1_G3_G4_REGRESSION_RESULT.md/json`
4. `G4_REMAINING_FIELD_VALIDATION_GAPS.md`
5. final Construction ZIP + SHA256
6. source delta / manifest / static audit results

Required result form:

```text
G1 = PASS
G2 = PASS
G2.1 = PASS
G3 = PASS
G4 = ENGINEERING_PASS_CANDIDATE | REPAIR_REQUIRED | REPLAN | STOP

ARCHITECTURE_DRIFT = NO | YES
R1_R2_REOPEN_REQUIRED = NO | YES

G5_DEFECT_TRUTH = HOLD
G6_R4_CLOSED_LOOP = HOLD
BANK_INTERNAL_PILOT_READY = NO
```

G4 WorkItem must stop at G4. Closure authority remains 00.8.

---

# 21. Mandatory bank Field Validation carried into/after G4

Construction must not fake:

- real OpenCode 1.18.3 observation/auth payload;
- real Windows Git Bash/Control Loop lifecycle;
- real controlled-browser ownership/takeover behavior;
- real 4A login/resume behavior;
- real Coverage Platform UI/API/export parity;
- real coverage refresh delay/staleness semantics;
- real DB/CAT auth/write constraints;
- real Security/Performance tool/runtime binding;
- actual coverage gain on PFC/KYB;
- valid defect yield;
- real AI case quality on bank requirements.

Construction may prove contracts and deterministic product paths only.

---

# 22. Final architecture invariant summary

```text
R1 remembers everything.
G2 decides what work exists and what is next.
G2.1 decides who/where executes and keeps Sessions alive.
G3 decides how to test and why.
G4 executes, measures, and drives the testing goal toward convergence.
G5 decides whether an observed failure is a real defect.
G6 later closes the continuous change/fix/retest loop.
```

G4 completion must make the following user experience possible:

```text
User:
测试当前版本，目标有效增量覆盖率95%，重点发现真实缺陷。

System:
analyze
-> design
-> execute
-> ask for human only when required
-> automatically resume
-> measure bank coverage
-> find remaining gap
-> ask G3 to replan
-> execute next batch
-> repeat
-> report goal satisfied or exactly why it cannot be reached
```

