# RC7.2 AgentTeams Worker / Session / Lease Contract

Status: FROZEN SUB-CONTRACT

## 1. Goal

Make AgentTeams a reliable execution substrate for N1-N10 runtime. Separate persistent logical roles from disposable worker sessions, and make resource/capability ownership explicit and auditable.

## 2. Role model

Allowed role templates may include:

```text
requirement-analyst
code-analyst
test-designer
data-preparer
executable-builder
test-executor
diagnosis-worker
coverage-auditor
quality-reviewer
defect-manager
```

Roles are logical capability profiles, not permanent chat sessions and not MissionNodes.

A MissionNode may use multiple roles. A role may create many workers.

## 3. Captain / Mission Director contract

Captain is control-plane coordinator.

Allowed responsibilities:

```text
read R1 truth
advance MissionGraph
invoke decomposer
create/assign WorkItems
request/issue/revoke leases through runtime services
pause/resume/reassign workers
classify control-plane blockers
perform session handoff
invoke convergence review
```

Captain SHOULD NOT normally:

```text
run L4 business actions
run API test cases
mutate test DB as an executor
perform hidden code-analysis work for N7
repair test data inside executor flow
share its credentials with workers
```

`FIELD_FULL_ACCESS` means control-plane authority for registered capabilities; it does not mean Captain should occupy every execution resource.

## 4. Worker lifecycle

Default lifecycle:

```text
WorkItem READY
 -> scheduler selects role
 -> create Worker session
 -> bind Attempt
 -> acquire scoped leases
 -> execute
 -> emit Evidence/Delivery
 -> checkpoint R1
 -> close/recycle Worker
```

Default target is one ETU per worker session. Reuse is allowed only under explicit configurable thresholds and compatible context.

## 5. Session rotation policy

Runtime must monitor at least:

```text
worker_session_age
workitem_count
step_count
token/cumulative usage where available
tool_call_count
compaction_count
failure/retry count
context-estimate or equivalent pressure metric
```

Rotation triggers are configurable. Reaching a trigger yields:

```text
ROTATION_REQUIRED
 -> finish/checkpoint safe boundary
 -> close old worker
 -> create fresh worker
 -> load minimal canonical inputs
 -> continue next WorkItem/Attempt
```

Normal architecture must not rely on a single executor/designer/reviewer remaining alive across dozens of rounds.

## 6. Minimal context assembly

Fresh worker input should be assembled from canonical refs, normally:

```text
WorkItem/ETU spec
current NodeDelivery refs
ExecutableContract or task-specific contract
required DataRefs
EvidenceRefs needed for the work
current Gap/Failure context if retry/diagnosis
relevant coverage snapshot
lease/resource assignments
```

Do not hydrate entire prior chat history by default.

## 7. Fresh reviewer contract

Important reviews use fresh reviewer sessions.

Reviewer input:

```text
NodeDelivery
GateCriteria
EvidenceRefs
explicit prior-review refs if required
```

Reviewer must not require executor/designer chat history to understand the delivery.

NodeGate records reviewer worker/session identity.

## 8. Captain session handoff

A Captain handoff is supported without duplicating the Mission.

Safe flow:

```text
Captain A
 -> stop dispatching new work
 -> allow active Attempts to safe checkpoint
 -> persist HANDOFF_CHECKPOINT
 -> Captain B reads R1
 -> verifies same mission/team/work state
 -> assumes dispatch responsibility
```

Handoff checkpoint minimum data:

```text
mission_id
release_batch_id
current node(s)
latest NodeDeliveries/Gates
completed WorkItems
active/blocked WorkItems
active leases
coverage snapshot
unresolved gaps/defects
next schedulable work
```

New Captain must not reconstruct truth from old chat transcripts.

## 9. Worker authority model

Workers remain `SIGNED_LEASE_STRICT`.

A WorkItem/Attempt carries exact allowed capabilities. Wildcard Full Access is prohibited for normal workers.

Missing capability produces:

```text
CAPABILITY_GAP
 -> CapabilityRequest
 -> CapabilityBroker decision
```

Decision enum:

```text
AUTO_GRANT_TEMP_LEASE
DELEGATE_TO_SPECIALIST
HUMAN_GATE
DENY
```

A temporary grant is scoped to Mission/WorkItem/Attempt/Worker and expires or is revoked at completion.

Captain credentials/tokens are never copied into worker context as a shortcut.

## 10. CapabilityLease schema

Minimum fields:

```text
lease_id
mission_id
workitem_id
attempt_id
worker_id
capabilities[]
scope_constraints
issued_at
expires_at
issued_by
decision_reason
state
```

Lease versions/renewals must be auditable.

## 11. Delegation instead of privilege escalation

If a capability belongs to a specialist role, prefer delegation.

Example:

```text
test-executor needs privileged DB mutation
 -> CapabilityRequest
 -> Broker chooses DELEGATE_TO_SPECIALIST
 -> data-preparer WorkItem
 -> DataRef/Evidence returned
 -> executor resumes
```

Do not grant broad DB write merely to keep executor moving.

## 12. Browser resource contract

Browser is a leased runtime resource, not a shared global singleton.

Objects:

```text
BrowserPool
BrowserInstance
BrowserLease
```

BrowserInstance minimum metadata:

```text
browser_instance_id
profile_dir
cdp_endpoint/port
bsk_session/endpoint
auth_asset_ref if any
state
```

BrowserLease minimum metadata:

```text
lease_id
browser_instance_id
mission_id
workitem_id
attempt_id
worker_id
access_mode: READ | WRITE
issued_at
expires_at
state
```

Invariant:

> one BrowserInstance may have only one active WRITE owner at a time.

Conflicting write request returns `RESOURCE_CONFLICT` and is routed to ResourceManager, not resolved by two Agents racing for control.

## 13. AuthKeeper contract

Auth/session keepalive runs as a dedicated worker/resource owner when needed.

AuthKeeper uses a separate BrowserInstance/BrowserLease from L4/L5 workers.

Where technically safe, Auth Asset (cookie/token/state bundle) may be exported/imported through a defined mechanism. Browser control itself is never shared.

If authentication is device/profile/session-bound and cannot be safely cloned, each worker performs its own 4A Skill login or uses a dedicated authenticated browser instance.

## 14. DataLease contract

Mutable/exclusive test data can be reserved by DataLease.

Minimum fields:

```text
data_lease_id
data_ref
mission_id
workitem_id
attempt_id
owner
mode
issued_at
expires_at
cleanup/release policy
state
```

Data collision must be surfaced as resource/data gap, not silently repaired by executor guessing a replacement.

## 15. Model assignment and failover

Model is bound to worker/attempt, not entire Mission.

ModelAssignment metadata:

```text
assignment_id
worker_id
attempt_id
provider
model
capability_profile
fallback_chain[]
state
```

Provider failure classes:

```text
PROVIDER_AUTH
PROVIDER_QUOTA
PROVIDER_TIMEOUT
PROVIDER_UNAVAILABLE
PROVIDER_CONFIG_INVALID
```

Failover flow:

```text
provider failure
 -> persist FailureEvidence/checkpoint
 -> current Attempt becomes BLOCKED_PROVIDER or retry-eligible
 -> scheduler selects approved fallback according to policy
 -> fresh Worker session
 -> new Attempt for same WorkItem or controlled continuation
 -> canonical Evidence/R1 preserved
```

Do not rely on hot-swapping the model of an already long-running AgentTeams member.

## 16. Startup/model readiness relationship

AgentTeams dispatch requiring a model must not start until the model/provider readiness gate is satisfied.

Readiness states include:

```text
MODEL_AUTH_READY
MODEL_AUTH_EXPIRED
MODEL_PROVIDER_READY
MODEL_PROVIDER_UNAVAILABLE
MODEL_CONFIG_INVALID
MODEL_READY_TIMEOUT
MODEL_READY
```

Auth refresh must invalidate/recreate stale provider clients before re-probe.

## 17. Resource ordering/deadlock policy

When WorkItems require multiple exclusive resources, runtime must define deterministic acquisition ordering or reservation strategy to avoid deadlocks.

Recommended logical ordering:

```text
Capability authority
 -> DataLease
 -> BrowserLease / environment-exclusive lease
 -> execution
```

If acquisition fails, release/retry policy is explicit; workers must not hold resources indefinitely while waiting on another unavailable resource.

## 18. Lease expiry and orphan recovery

All non-permanent leases require TTL/heartbeat/owner state.

If a worker/session dies:

```text
runtime detects orphan
 -> marks Attempt interrupted
 -> releases/reclaims safe leases
 -> persists recovery event
 -> scheduler decides retry/fresh takeover
```

Lease truth is stored in R1/runtime persistence, not only process memory.

## 19. Provider/browser/capability failures versus SUT failures

The runtime must keep these namespaces distinct:

```text
SUT_TEST_FAILURE
PRODUCT_DEFECT
ENVIRONMENT_FAILURE
PROVIDER_FAILURE
CAPABILITY_FAILURE
RESOURCE_CONFLICT
TEST_DESIGN/DATA/ANALYSIS_GAP
```

Only SUT/product paths feed product-quality conclusions directly. Infrastructure/control failures remain visible but do not become fake defects or test FAILs.

## 20. Parallelism rules

Parallel workers are allowed only when dependencies and exclusive leases do not conflict.

Examples:

- independent L3 ETUs can execute in parallel when data is isolated;
- independent L4 ETUs require separate BrowserLease write ownership;
- AuthKeeper and L4 cannot write same BrowserInstance;
- same exclusive mutable data forces serialization or separate copies;
- N3/N4 workers may parallelize by SST/code slice if merge/review semantics are defined.

Parallelism is not measured by number of persistent Agent members.

## 21. Required tests

At minimum:

1. one role creates multiple fresh workers across ETUs;
2. worker session rotation preserves R1 truth;
3. fresh reviewer can review without prior chat history;
4. Captain handoff resumes same Mission and avoids duplicate completed work;
5. worker capability gap produces scoped request/grant/delegation;
6. worker never receives Captain Full Access token/authority;
7. Browser write conflict is rejected by runtime;
8. AuthKeeper and L4 receive separate browser instances/leases;
9. orphaned Browser/Data/Capability leases are reclaimed safely;
10. provider quota creates fresh fallback worker without Mission loss;
11. provider failure is not classified as SUT failure;
12. data conflict is not silently fixed by executor;
13. active lease state survives process/session restart;
14. lease expiration/revocation prevents further tool calls;
15. parallel ETUs cannot violate exclusive resource ownership.

## 22. Acceptance rule

AgentTeams integration is NOT complete if RC7.2 still depends on a fixed handful of long-lived members carrying all mission history, if resource conflicts are coordinated only by LLM conversation, or if worker permission/model/browser failures require manual session surgery. Acceptance requires persisted worker/attempt/lease semantics, fresh-session execution, auditable authority and runtime-enforced resource ownership.
