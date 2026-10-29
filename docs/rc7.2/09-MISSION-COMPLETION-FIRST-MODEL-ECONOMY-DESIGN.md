# RC7.2 Mission-Completion-First Model Economy Design

Status: **DESIGN BASELINE — CONSTRUCTION REQUIRED — NOT FIELD VERIFIED**

This design refines RC7.2 model/token economy after the RC7.1 field symptom of roughly 40M tokens being consumed in about 1.5 hours.

It does **not** change the final objective of RC7.2: complete the real ReleaseBatch test mission with sufficient analysis, design, execution, evidence, defect/RCA/recovery and convergence. Token control exists only to reduce waste and improve execution efficiency.

## 1. Governing principle

The priority order is frozen as:

```text
TEST MISSION COMPLETION
  > test sufficiency / risk coverage
  > mission critical path
  > execution correctness / evidence truth
  > execution success and recovery
  > model/token efficiency
```

Model economy MUST optimize **HOW / WHEN / WHICH MODEL / WHICH CONTEXT / WHICH BATCH**.

It MUST NOT change **WHAT MUST BE TESTED** merely to save quota.

A ReleaseBatch or mandatory TestObligation may not be dropped, merged away, silently skipped, downgraded, relabeled PASS or declared converged because a token target was reached.

## 2. Compatibility with existing RC7.2 architecture

The frozen business hierarchy remains:

```text
ReleaseBatch
 -> Requirement
 -> SST
 -> TestObligation
 -> L1-L7
 -> TestCase
 -> ETU
 -> WorkItem
 -> Attempt
 -> Evidence
```

The frozen runtime hierarchy remains:

```text
Mission
 -> MissionNode(N1-N10)
 -> Stage
 -> WorkItem
 -> Attempt
 -> Team/Worker
 -> Tool/Skill
 -> Evidence/R1
```

The Adaptive Task Decomposer remains responsible for creating small cohesive ETUs and preserving ReleaseBatch/Requirement/SST/TestObligation lineage.

This design adds a horizontal model-economy control plane. It does not create N11 and does not replace the N1-N10 state machine.

## 3. Separate four granularities

RC7.2 MUST explicitly separate these four granularities:

### 3.1 Business test granularity

TestObligation / TestCase / ETU determine what must be covered. This granularity is quality-driven.

### 3.2 Scheduling granularity

WorkItem / Attempt determine durable lifecycle, dependency, retry, evidence and recovery. Fine WorkItems remain independently observable even when they share one model context.

### 3.3 Agent execution-batch granularity

Related READY WorkItems may be grouped into an `ExecutionBatch` when they have compatible context/capability affinity. ExecutionBatch exists to reuse context and reduce model-call multiplication. It is **not** a replacement super-task.

Every member WorkItem keeps independent:

```text
workitem_id
attempt_id
state
actual_result
assertion_result
evidence_refs
gap_refs
```

### 3.4 Model-call granularity

A model call is the smallest semantic inference invocation. One WorkItem does not imply one model call. Many deterministic WorkItems require zero model calls; multiple semantic WorkItems may share a bounded model call/batch when independence and output traceability are preserved.

Frozen rule:

```text
business task granularity != scheduling granularity != execution-batch granularity != model-call granularity
```

## 4. Execution mode classification

Each WorkItem or semantic sub-step MUST be classifiable as:

```text
DETERMINISTIC
SEMANTIC
HYBRID
```

Examples of deterministic-first work include R1 lookup/state sync, known route lookup, deployment lookup, file/SHA validation, structured DB assertions, API execution, CAT query, CodeGraph query and other tool operations whose decision does not need generative reasoning.

`DETERMINISTIC` work MUST NOT launch an LLM simply because it is represented as a WorkItem.

`HYBRID` work runs deterministic/tool steps first and invokes a model only for the unresolved semantic part.

## 5. ExecutionBatch contract

An ExecutionBatch may be formed when READY WorkItems have compatible affinity, including:

```text
same Requirement/SST or tightly related obligation lineage
same semantic objective
same N-node/stage where practical
same code/change slice or service
same data/auth/environment family
same oracle/tool family
compatible capability requirements
bounded size and bounded context
```

A batch MUST NOT collapse unrelated SSTs, test levels, auth/browser contexts, data lifecycles or unrelated business goals merely to reduce model calls.

The batch output must be machine-separable back into each WorkItem/Attempt. If per-WorkItem result/evidence cannot be reconstructed, the batch is invalid.

ExecutionBatch is a **context reuse unit**, not a new business truth root.

## 6. Minimum Context Envelope

Model prompts MUST be compiled from canonical refs and bounded projections instead of repeatedly copying complete mission history.

Preferred inputs are:

```text
ReleaseBatchContextRef
RequirementContextRef
SSTContextRef
CodeImpactRef
TestObligationRef
CaseRef
Environment/Deployment/RouteRef
EvidenceRef
GapRef
previous AttemptSummaryRef
```

`ContextEnvelopeBuilder` hydrates only the minimum content needed by the current semantic decision.

Examples:

- an L3 API assertion normally needs API contract, route/deployment, data, oracle and relevant evidence, not the full UI DOM or unrelated SST history;
- an N8 retry normally needs the previous attempt summary + classified gap + delta evidence, not full re-ingestion of unchanged requirements and code analysis.

The runtime MUST record context digest/bytes and lineage so repeated-context amplification is measurable.

## 7. Retry delta contract

A retry/recovery model call MUST default to:

```text
previous_attempt_summary
+ explicit_gap
+ changed/new evidence
+ changed dependency refs
```

Unchanged upstream artifacts are referenced by digest/ref and hydrated only when the retry reason genuinely requires them.

Full-context retry requires an explicit reason, such as upstream delivery revision, major deployment baseline change or evaluator finding that invalidates the prior projection.

Infinite or no-progress retry loops are a correctness failure, not a valid way to complete a mission.

## 8. Evaluator economy without weakening independence

Worker and independent Evaluator remain logically independent.

Evaluation MUST be deterministic-first:

1. schema/lineage/state/evidence completeness checks;
2. known assertion/oracle checks;
3. only unresolved semantic uncertainty is sent to an LLM evaluator.

Compatible sibling outputs may be `EvaluatorBatch` reviewed under one shared bounded context, provided every WorkItem receives an independent verdict/gap result and the evaluator is not the producer session.

Only failed/insufficient WorkItems are repaired; PASS siblings are not regenerated merely because one member failed review.

## 9. Model cost windows

The bank quota schedule is a runtime scheduling input, not a test-scope rule.

Default bank-local schedule for RC7.2 is:

```text
workday normal working time before 18:00:
  quota pool: 40M
  quota_cost_factor: 1.0

18:00 <= local time < 21:00:
  quota accounting: 10:1
  quota_cost_factor: 0.1

local time >= 21:00:
  quota_limited: false
```

The implementation MUST make timezone and window configuration explicit. Bank deployment defaults to `Asia/Shanghai`; tests must not depend on the machine timezone.

The scheduler may defer a **non-blocking, high-semantic-cost** call to a cheaper window while continuing useful deterministic/tool work.

The scheduler MUST NOT defer a model call when it is on the active mission critical path and delaying it would prevent required testing from progressing, unless an explicit operational policy/Human Gate says otherwise.

## 10. Model economy decision inputs

Each schedulable semantic unit should expose runtime metadata including:

```text
execution_mode: DETERMINISTIC | SEMANTIC | HYBRID
semantic_cost_class: LOW | MEDIUM | HIGH
mission_criticality: BLOCKING | NON_BLOCKING
context_affinity: requirement/sst/service/environment/data/oracle/tool keys
batch_eligibility
retry flag / retry reason
estimated_context_bytes
```

These attributes affect execution strategy only. They do not change canonical TestObligation identity or required coverage.

## 11. Budget semantics: soft economy target, not mission kill-switch

Mission/ReleaseBatch token budgets remain useful as telemetry, forecasting and warning thresholds.

They are **not** a hard stop for legitimate mandatory testing.

Budget or cost-window exhaustion may cause:

```text
WARN
REPLAN_EXECUTION_MODE
BATCH_MORE
HYDRATE_LESS_CONTEXT
DEFER_NON_BLOCKING_SEMANTIC_WORK
PREFER_DETERMINISTIC_WORK
PREFER_CHEAPER_WINDOW
```

It MUST NOT cause:

```text
drop TestObligation
skip mandatory Case/ETU
mark WorkItem PASS without execution
mark N-node sufficient without evidence
mark ReleaseBatch CONVERGED solely to save tokens
```

## 12. Hard guards are allowed only for waste/correctness conditions

A model call may be hard-blocked when execution is demonstrably invalid or wasteful, for example:

```text
DETERMINISTIC step attempting to call an LLM
exact same-context loop beyond configured guard
retry loop with no semantic/evidence progress
invalid/missing lineage needed to attribute the call
invalid model/provider/capability assignment
known duplicate call already satisfied by canonical output
```

These are `WASTE_GUARD` / correctness protections, not token-budget exhaustion gates.

When a hard guard fires, the owning WorkItem remains incomplete/blocked and must be replanned; it is never silently discarded.

## 13. Unknown usage truth rule

If DSH/provider does not expose usable token counters:

```text
usage_status = UNKNOWN
```

Never record guessed usage as MEASURED and never convert UNKNOWN to zero.

UNKNOWN usage does **not** automatically stop mandatory test execution. It blocks only claims that measured token efficiency/Q7 economy qualification has been proven.

Mission test completion truth and model-efficiency truth are separate dimensions.

## 14. R1 telemetry

The model economy ledger must support at least:

```text
actual model calls
input/output/total tokens when MEASURED
usage status/source
N-node/stage/workitem/attempt/agent lineage
retry lineage
context bytes and digest
repeated-context ratio / reuse factor
retry amplification
review/evaluator amplification
model calls per TestObligation / executed Case
cost-window classification and quota-equivalent consumption
batch id / batch member count when applicable
cache/ref reuse when implemented
```

No shadow truth store may supersede R1.

## 15. Q7 acceptance semantics

Q7 still primarily proves a real ReleaseBatch can complete N1-N10 truthfully.

Model economy is a mandatory **quality/efficiency evidence dimension**, not the primary business completion gate.

For a Q7 field run, report at least two independent outcomes:

```text
MISSION_COMPLETION_STATUS
MODEL_ECONOMY_STATUS
```

Examples:

- Mission incomplete + economy good => Q7 cannot pass.
- Mission complete + token usage UNKNOWN => functional result may be complete, but model-economy qualification remains HOLD and BANK_FINAL cannot claim economy verified.
- Mission complete + measured economy + no waste regressions => eligible to satisfy the economy sub-contract.

A hard numerical reduction target must not be invented before field baseline measurement. Reduction claims require same-scope measured evidence.

## 16. Compatibility statement

This design is compatible with the existing Adaptive Task Decomposer because:

- the Decomposer still decides **what work exists** and preserves fine ETU/WorkItem lineage;
- the Scheduler still decides **when/where work runs**;
- the model-economy layer decides **how semantic work reuses context and when non-critical expensive calls run**.

Therefore RC7.2 MUST NOT coarsen real test decomposition as the primary token optimization.

## 17. Required construction slices

Implementation should proceed in narrow slices:

1. change current hard budget admission into warning/replan semantics while preserving deterministic/repeat-loop hard guards;
2. add explicit cost-window policy and quota-equivalent telemetry;
3. persist economy decision/outcome in R1;
4. add minimum-context/retry-delta contract support;
5. add ExecutionBatch/EvaluatorBatch where compatibility is provable;
6. integrate economy metadata into scheduling without changing canonical task scope;
7. add Q7 dual-status qualification/reporting;
8. field-measure BLOAN-PF1.2.1 (or the then-current real ReleaseBatch) before claiming savings.

## 18. Mandatory regression tests

At minimum prove:

1. token budget warning does not delete/block a mandatory WorkItem solely for cost;
2. deterministic work still cannot invoke an LLM;
3. exact same-context/no-progress loops are hard-blocked and replanned;
4. a BLOCKING semantic WorkItem can proceed in an expensive window;
5. a NON_BLOCKING HIGH-cost semantic unit may be deferred while deterministic work remains runnable;
6. 18:00-21:00 is classified with cost factor 0.1;
7. >=21:00 is classified quota-unlimited;
8. timezone is explicit and testable;
9. UNKNOWN token usage is never reported as measured/zero;
10. UNKNOWN usage does not silently mark mission work complete or automatically cancel mandatory execution;
11. ExecutionBatch keeps per-WorkItem result/evidence lineage;
12. retry-delta does not resend unchanged full context by default;
13. fine ETU decomposition remains unchanged by token optimization;
14. N10 cannot converge merely because model-cost targets are met.

## 19. Field validation rule

Repository CI can prove the policy and contracts. It cannot prove real bank quota accounting, DSH provider usage emission, scheduler effectiveness or actual savings.

Field validation must compare equivalent ReleaseBatch scope and report both mission completeness and measured economy. Until then, any percentage savings claim is prohibited.
