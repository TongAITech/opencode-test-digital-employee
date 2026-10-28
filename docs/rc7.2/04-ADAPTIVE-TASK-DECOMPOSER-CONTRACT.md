# RC7.2 Adaptive Task Decomposer Contract

Status: FROZEN SUB-CONTRACT

## 1. Goal

Replace fixed large rounds and coverage-gap-first planning with release-batch/SST-centric adaptive task decomposition. The decomposer converts canonical TestObligations and current gaps into small, cohesive, independently executable ETUs.

The decomposer is invoked repeatedly as mission truth changes. It is not a one-time case batching utility.

## 2. Required planning hierarchy

All planning starts from:

```text
ReleaseBatch
 -> Requirement
 -> SST
 -> TestObligation
 -> L1-L7
 -> TestCase
 -> ETU
```

Coverage, defect history, risk, code impact and runtime feedback influence priority and gap repair. They do not become the hierarchy root.

## 3. TestObligation generation

Canonical TestObligation meaning:

```text
Requirement
x SST
x Business Scenario / Rule
x Change Slice
x Risk
x Test Level
x Oracle
```

Obligation generation MUST consume N2/N3 outputs. An obligation without Requirement/SST traceability is rejected unless explicitly classified as investigation/exclusion work.

Obligations should cover at least:

```text
positive business paths
negative business rules
boundary rules
role/permission rules
state transitions
data constraints
change-impact risks
historical defect risks
integration effects
applicable L1-L7 levels
```

## 4. Decomposer inputs

Every decomposition decision must be based on a snapshot containing at least:

```text
release_batch_id
mission_id
current_node
requirement/sst scope
active TestObligations
current Cases
remaining gaps
risk scores
code impact/change slices
coverage snapshot/gaps
historical execution metrics
resource/capability availability
active leases/conflicts
blocked/stale assets
```

The snapshot reference/version must be recorded so a later reviewer can explain why an ETU was formed.

## 5. ETU definition

ETU is the smallest schedulable cohesive test-work unit.

Default target:

```text
3 <= case_count <= 8
predicted_duration <= 15 minutes
one primary business target
one primary code slice
one test level
one main data strategy
one main oracle family
one primary tool family
```

These are defaults, not blind constants. The decomposer may create 1-2-case ETUs for expensive/high-risk journeys or more than 8 only when explicit cohesion/cost evidence justifies it.

## 6. Cohesion scoring

Implement an explainable cohesion score. Exact weights may be tuned, but the following dimensions are mandatory inputs:

```text
same_requirement
same_sst
same_obligation
same_business_scenario
same_code_slice
same_test_level
same_data_domain
same_auth_role
same_oracle_family
same_execution_tool
same_browser_context
same_environment
```

Recommended conceptual form:

```text
cohesion = weighted_similarity(dimensions)
          - split_penalties
```

Every ETU should store an explanation summary, not only a numeric score.

## 7. Split penalties / triggers

An ETU MUST be considered for split when one or more thresholds are exceeded:

```text
multiple unrelated business goals
multiple unrelated SSTs
multiple primary code slices
mixed test levels requiring different workers/tools
mixed auth/browser contexts
mixed data lifecycle strategies
mixed oracle families
predicted duration high
predicted token/tool cost high
browser/data lease contention high
failure types heterogeneous
repeated diagnosis loops
session/context growth high
low historical completion probability
```

Split output preserves lineage and parent-child relation:

```text
parent_etu_id
split_reason
child_etu_ids[]
```

## 8. Merge conditions

Small ETUs may be merged only when:

```text
same Requirement/SST/Obligation lineage
same test level
overlapping code target
compatible data setup
compatible auth/browser context
same or compatible oracle/tool family
low predicted execution cost
no lease conflict
```

Merge must not cross unrelated SSTs merely to fill a target case count.

## 9. Priority scoring

Priority must not be `coverage_gap_only`.

Required dimensions:

```text
business_risk
requirement_priority
SST criticality
change_impact
historical defect density
uncovered changed code
coverage yield estimate
production blast radius
blocked downstream work
execution cost
resource contention
learning value / uncertainty reduction
```

Recommended conceptual score:

```text
priority = risk_value
         + change_value
         + defect_value
         + gap_reduction_value
         + uncertainty_reduction_value
         - execution_cost
         - contention_cost
```

Weights are configurable and must be visible in runtime/config, not hidden in prompts.

## 10. Coverage feedback routing

Coverage feedback processing is mandatory:

```text
Libra uncovered change
 -> CodeSlice
 -> Requirement/SST mapping
 -> TestObligation mapping
 -> GapReason
 -> ResponsibleNode
```

GapReason routing:

```text
NO_REQUIREMENT_MAPPING -> investigation at N2/N3
ANALYSIS_MISSING       -> N3
CASE_MISSING           -> N4
DATA_BLOCKED           -> N5
EXECUTABLE_BLOCKED     -> N6
PATH_NOT_REACHED       -> N8
UNREACHABLE            -> CoverageExclusionCandidate
ALREADY_COVERED_NO_GAIN-> deprioritize / investigate measurement
```

Coverage may create a `Gap` or reprioritize an existing obligation. It may not create a canonical Case without lineage.

## 11. Coverage yield learning

The runtime should record per ETU/Attempt:

```text
predicted_coverage_yield
actual_coverage_delta
changed_classes_touched
changed_methods/branches_touched where available
execution_duration
tool_calls
token/cost metrics
failure_classification
```

Use history to improve later prioritization and ETU sizing.

Low-yield pattern example:

```text
many cases + high cost + near-zero delta
```

should trigger reprioritization or diagnosis, not automatic generation of another similar round.

## 12. Requirement/SST sufficiency before coverage optimization

The decomposer must distinguish two planning modes:

### Mode A — Baseline sufficiency

Before broad coverage chasing, ensure each in-scope Requirement/SST has required obligations for business/risk/L1-L7 scope.

### Mode B — Gap repair / convergence

After baseline obligations exist, use risk/code/coverage/defect feedback to identify missing or insufficient obligations.

The runtime may interleave modes, but may not skip baseline business sufficiency solely because coverage tasks are available.

## 13. L1-L7 decomposition

L1-L7 are test levels/capability routes, not agents.

A TestObligation may yield multiple ETUs across levels when justified.

Examples:

```text
same SST/business rule
 -> L1 changed method unit ETU
 -> L3 API integration ETU
 -> L4 UI validation ETU
 -> L5 journey ETU
```

Do not bundle L1/L3/L4/L5 cases into one ETU when they require different tools/resources/workers.

L6/L7 are generated only when scope/risk/requirements require them and must use proper performance/security tooling rather than relabeling functional negative cases.

## 14. Data-aware decomposition

ETU grouping must account for test-data lifecycle:

- same immutable/reference data may favor grouping;
- exclusive mutable data may force separation;
- expensive setup can justify grouping compatible cases;
- conflicting state transitions require isolation;
- cleanup requirements must be included in cost estimation.

The decomposer consumes N5 readiness; it does not invent data during execution.

## 15. Browser/auth-aware decomposition

L4/L5 ETUs must include browser/auth resource requirements.

Cases requiring different roles, independent sessions or destructive browser state should split into separate ETUs unless multi-context execution is explicitly modeled.

Browser lease contention influences scheduling, not case semantic identity.

## 16. Dynamic replanning events

Re-decomposition may be triggered by:

```text
NodeDelivery revision
new Gap
coverage snapshot
new defect
failure classification
DataRef invalidation
resource conflict
provider degradation
worker rotation threshold
ETU duration/cost threshold
new deployment/change baseline
```

Replanning must preserve completed Evidence and avoid duplicate execution unless regression/retry policy explicitly requests it.

## 17. Scheduler relationship

Decomposer decides what work units should exist and their priority/dependencies.

Scheduler decides when/where/by which worker they execute subject to leases/resources.

These concerns must not be collapsed into one prompt.

## 18. Required explainability

For each ETU, runtime must be able to answer:

```text
Why does this ETU exist?
Which ReleaseBatch/Requirement/SST/Obligation does it serve?
Why are these cases grouped together?
Why this test level?
Why this priority?
Which coverage/risk/defect signal influenced it?
What resources/capabilities are required?
What is the expected completion/yield?
```

## 19. Required tests

Implement at least:

1. Cases from unrelated SSTs do not merge merely due to same API/tool.
2. 20+ heterogeneous cases are split into cohesive ETUs.
3. Same obligation/same API/same data/oracle small cases can merge.
4. Mixed L3/L4 cases split by tool/resource needs.
5. Coverage gap with valid mapping reprioritizes or repairs an obligation.
6. Coverage gap without mapping cannot create an orphan Case.
7. Low-yield ETU history reduces priority or triggers diagnosis/replan.
8. Data conflict forces split.
9. Browser-role conflict forces split or separate BrowserLease requirements.
10. Completed WorkItems are not recreated on replan without an explicit reason.
11. All generated ETUs preserve ReleaseBatch/Requirement/SST/Obligation lineage.
12. Decomposer output is deterministic for the same frozen input/config, except where explicitly randomized and seeded.

## 20. Acceptance rule

The adaptive decomposer is NOT complete if the implementation still behaves primarily as:

```text
coverage gap
 -> generate 30-40 cases
 -> execute entire round
 -> coverage check
 -> next round
```

Acceptance requires small cohesive ETUs, lineage preservation, runtime feedback-driven split/merge/reprioritization and semantic coverage-gap routing.
