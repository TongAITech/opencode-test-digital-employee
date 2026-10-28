# RC7.2 N1-N10 Runtime State Machine Contract

Status: FROZEN SUB-CONTRACT

## 1. Goal

Make N1-N10 a real persisted mission state machine with explicit inputs, outputs, gates, transitions and semantic back-edges. Agent prompts may help execute a node but may not define node truth.

## 2. Core runtime objects

Minimum persisted objects:

```text
Mission
MissionNode
NodeDelivery
NodeGate
Gap
Transition
BackEdge
ImpactSet
```

### MissionNode minimum fields

```text
mission_node_id
mission_id
node_type: N1..N10
scope_ref
state
active_delivery_version
entered_at
exited_at
blocked_reason
```

Allowed high-level states:

```text
NOT_STARTED
READY
RUNNING
REVIEW_PENDING
PASS
NEEDS_REVISION
BLOCKED
HUMAN_GATE
STALE
```

### NodeDelivery minimum fields

```text
delivery_id
mission_node_id
version
input_refs[]
artifact_refs[]
evidence_refs[]
known_gaps[]
created_by_workitems[]
created_at
```

### NodeGate minimum fields

```text
gate_id
mission_node_id
delivery_id
criteria[]
passed[]
failed[]
evidence_refs[]
decision
return_node
reviewer_worker_id
reviewer_session_id
```

Gate decision enum is exactly:

```text
PASS
NEEDS_REVISION
BLOCKED
HUMAN_GATE
```

## 3. State transition rules

General forward flow is N1 -> N2 -> N3 -> N4 -> N5 -> N6 -> N7 -> N8/N9 -> N10, but this is not a one-pass pipeline.

A node may advance only when its current delivery is PASS and all mandatory upstream delivery refs are non-STALE.

A node marked STALE cannot dispatch new execution work until regenerated/reviewed.

A node may never become PASS solely because an Agent textual response says “completed”.

## 4. N1 contract — Reality

Inputs:

```text
ReleaseBatch scope
deployment/config refs
tool registry
model/provider config
environment config
route/deployment skills
```

Required delivery categories:

```text
ENVIRONMENT
DEPLOYMENT
API_ROUTE
DB
CAT
LIBRA
CODEGRAPH
BROWSER
AUTH
MODEL
MCP
TOOLS_SKILLS
WORKER_NODE
```

Each category result:

```text
READY | DEGRADED | BLOCKED | UNKNOWN
```

UNKNOWN may not silently equal READY.

N1 BLOCKED routes to N1 recovery or Human Gate. N1 changes that invalidate later assumptions must mark affected downstream assets STALE.

## 5. N2 contract — Requirement

Inputs: ReleaseBatch/Requirement/SST source material and approved knowledge.

Required delivery:

```text
BR/SR/TR mapping
business_rules
roles
states
state_transitions
positive_rules
negative_rules
boundary_rules
permission_rules
data_rules
unknowns
source_refs
```

Gate requirements:

- all in-scope Requirements and SSTs represented;
- critical rules have source evidence;
- roles/states/transitions identified where applicable;
- negative/boundary/permission/data rule analysis performed;
- unresolved unknowns explicitly classified.

A Requirement/SST may not proceed to canonical test design if mandatory N2 fields are unresolved.

## 6. N3 contract — Code Analysis

Inputs: PASS N2 delivery, version/app/change set, source repositories.

Mandatory chain:

```text
Requirement/SST
 -> changed code
 -> Controller/entry
 -> DTO/schema
 -> Service/domain rules
 -> persistence/DB constraints
 -> external dependencies
 -> side effects/errors/branches
```

Mandatory artifacts:

```text
requirement_code_mapping
sst_code_mapping
forward_impact
backward_impact
api_contracts
dto_required_fields
business_validation
db_constraints
state_constraints
branch_targets
external_dependencies
coverage_targets
graph_evidence
unknowns
```

CodeGraph evidence is mandatory for supported source scopes. If unavailable, the limitation is explicit and N3 gate follows configured fail-closed policy for the affected scope.

## 7. N4 contract — Test Design

Inputs: PASS/non-stale N2 and N3, release risk, history, feedback signals.

Required sequence:

```text
N2/N3 facts
 -> TestObligation
 -> Case set
 -> Design sufficiency review
```

Coverage feedback may influence priority or expose missing obligations but may not bypass Requirement/SST lineage.

Every executable Case requires:

```text
release_batch_id
requirement_id
sst_id
obligation_id
test_level
preconditions
input/data requirements
steps
expected results
oracles
evidence requirements
code trace
```

“TBD / guess during execution / find data later” blocks PASS for executable cases.

## 8. N5 contract — Test Data

Inputs: PASS N4 and N3 data constraints.

Responsibilities:

```text
discover
construct
verify
reserve
reuse
release
cleanup
```

Output is DataRef with verifiable preconditions, for example:

```text
data_ref
source_or_constructor
verification
reservation_owner
validity_window
cleanup_policy
```

N7 may not replace an invalid DataRef with arbitrary data without routing through N8->N5 or an explicitly permitted equivalent-data policy.

## 9. N6 contract — Executable Readiness

Inputs: non-stale N4 Case and N5 DataRefs plus N1 tool/route reality.

Output: ExecutableContract

```text
case_ref
environment
endpoint/target
tool_route
request/input
data_refs
preconditions
steps
assertions
oracles
evidence_required
cleanup
required_capabilities
required_resources
```

Gate fails closed if endpoint/schema/data/tool/capability/oracle/evidence is unresolved.

## 10. N7 contract — Execution

N7 is intentionally thin.

Allowed responsibilities:

```text
load ExecutableContract
acquire approved leases
materialize defined preconditions
execute defined actions
observe actual result
perform defined assertions
capture evidence
```

N7 may perform local mechanical transformations explicitly allowed by the ExecutableContract, but it may not perform broad analysis/design/data redesign.

When execution cannot honor the contract, N7 emits FailureEvidence and transitions to N8.

## 11. N8 contract — Diagnosis & Recovery

N8 is independent from N7 and normally uses a fresh diagnosis worker.

FailureClass enum:

```text
ENVIRONMENT_GAP
REQUIREMENT_GAP
ANALYSIS_GAP
TEST_DESIGN_GAP
TEST_DATA_GAP
EXECUTABLE_GAP
PRODUCT_DEFECT
PROVIDER_AUTH
PROVIDER_QUOTA
PROVIDER_TIMEOUT
CAPABILITY_GAP
RESOURCE_CONFLICT
VALID_TEST_FAILURE
FLAKY
UNKNOWN
```

Required routing:

```text
ENVIRONMENT_GAP -> N1
REQUIREMENT_GAP -> N2
ANALYSIS_GAP -> N3
TEST_DESIGN_GAP -> N4
TEST_DATA_GAP -> N5
EXECUTABLE_GAP -> N6
PRODUCT_DEFECT -> N9
PROVIDER_* -> runtime recovery
CAPABILITY_GAP -> CapabilityBroker
RESOURCE_CONFLICT -> ResourceManager
VALID_TEST_FAILURE -> N9 or controlled regression path
FLAKY -> bounded retry policy + evidence
UNKNOWN -> remain diagnosis/BLOCKED, never auto-PASS
```

N8 output includes evidence, classification confidence/rationale, responsible node, affected asset refs and requested remediation.

## 12. N9 contract — Defect

A defect requires evidence traceability:

```text
ReleaseBatch
Requirement/SST
TestObligation/Case
Attempt
request/response or equivalent action/result
DB/CAT/browser/log evidence where relevant
code refs/RCA where available
regression refs
```

LLM narrative alone is insufficient.

N9 owns defect lifecycle semantics; N7 may report a candidate failure but may not mark a product defect final without N9 criteria.

## 13. N10 contract — Release Convergence

N10 evaluates the entire ReleaseBatch.

Mandatory convergence dimensions:

```text
Requirement completion
SST completion
TestObligation completion
required L1-L7 completion
high-risk scenario completion
incremental coverage threshold
critical/open defect status
blocked workitems
unresolved gaps
evidence completeness
runtime integrity/stale assets
```

N10 result:

```text
CONVERGED
NOT_CONVERGED
HUMAN_GATE
BLOCKED
```

`coverage >= target` alone can never produce CONVERGED.

When NOT_CONVERGED, N10 emits structured gaps, each with `gap_reason`, `responsible_node`, `scope_refs`, `priority` and evidence.

## 14. Semantic back-edge persistence

Every back-edge is persisted as a first-class event/object:

```text
backedge_id
from_node
from_delivery
failure/gap_ref
return_node
reason
created_at
resolved_by_delivery
state
```

The scheduler may not infer back-edges solely from chat context.

## 15. ImpactResolver and stale propagation

When upstream truth changes, downstream assets may be invalid.

Examples:

- N2 business rule change -> affected N3/N4/N5/N6 assets STALE.
- N3 DTO/DB constraint change -> affected N4/N5/N6 STALE.
- N4 case change -> related N5/N6 and pending execution work STALE.
- N5 DataRef invalidation -> related N6/queued attempts STALE.

ImpactResolver must use explicit dependency refs; broad “invalidate everything” is allowed only as a safe fallback and must be observable.

## 16. Review policy

Node PASS requires a gate decision. Important node gates use a fresh reviewer session where practical, especially N3/N4/N6/N10. Reviewer input is current NodeDelivery + criteria + evidence, not the executor's accumulated chat history.

## 17. Concurrency

Different scopes/ETUs may execute concurrently when dependencies and leases allow. State machine correctness is per canonical object and version; concurrency must not allow two conflicting deliveries to both become active without conflict detection/versioning.

## 18. Required tests

At minimum implement tests for:

- forward transition only after PASS;
- non-PASS blocks dependent node;
- N7->N8 classification routes to N1/N2/N3/N4/N5/N6/N9;
- upstream change marks downstream STALE;
- STALE contract cannot dispatch N7;
- UNKNOWN never auto-PASS;
- N10 coverage-only false convergence is rejected;
- duplicate/conflicting active delivery protection;
- persisted back-edge survives session restart;
- fresh reviewer identity recorded in NodeGate.

## 19. Acceptance rule

The N1-N10 state machine is NOT implemented if the same behavior exists only through prompts, Agent role names or report text. Acceptance requires persisted runtime state, queryable transitions, gate enforcement and contract tests.
