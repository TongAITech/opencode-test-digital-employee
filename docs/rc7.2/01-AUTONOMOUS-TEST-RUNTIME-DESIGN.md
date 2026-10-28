# RC7.2 Autonomous Test Runtime — Detailed Design

Status: FROZEN DESIGN

## 1. Scope

RC7.2 is an execution-kernel upgrade over RC7.1. It preserves validated tools/integrations and replaces prompt-centric orchestration with a persisted autonomous runtime.

Preserved capabilities include DSH, AgentTeams, R1/runtime-state, PostgreSQL/Redis, Libra, CodeGraph, CAT, TDSQL, BrowserSkill/BSK, 4A, API/deployment routing, L1-L7 tooling, Field Full Access for coordinator, Worker STRICT signed lease, Evidence/Defect/Report assets.

RC7.2 MUST NOT be implemented as “more agents + more prompts”.

## 2. Architecture

```text
ReleaseBatch
  -> ReleaseBatchMission
     -> MissionGraph(N1-N10)
        -> NodeDelivery
        -> SufficiencyGate
        -> TestObligation
        -> AdaptiveTaskDecomposer
        -> ETU
        -> WorkItem
        -> Attempt
        -> AgentTeams Role
        -> Fresh Worker Session
        -> Capability/Resource Leases
        -> Tool/Skill
        -> Evidence
        -> Canonical R1
        -> Fresh Reviewer
        -> NodeGate
        -> Transition / Semantic Back-edge
     -> N10 Release Convergence
```

Control plane and execution plane are separated.

### Control plane

- ReleaseBatchMission
- MissionGraph / MissionNode
- Gate / Transition / BackEdge
- Gap classification
- Decomposer
- Scheduler
- CapabilityBroker
- ResourceManagers
- Convergence

### Execution plane

- AgentTeams roles
- Fresh workers
- real tools/skills
- attempts
- evidence production

Captain/Mission Director belongs to control plane. It should coordinate, authorize and schedule; it should not become a universal business executor.

## 3. Canonical asset model

### 3.1 ReleaseBatch

Required fields:

```text
release_batch_id
name
planned_release_time
versions[]
applications[]
requirements[]
mission_id
status
readiness
```

### 3.2 Requirement

```text
requirement_id
release_batch_id
version_ids[]
app_ids[]
sst_ids[]
risk
status
```

### 3.3 SST

```text
sst_id
requirement_id
release_batch_id
source_ref
risk
analysis_status
design_status
execution_status
```

### 3.4 TestObligation

TestObligation is the central design object. Canonical meaning:

```text
Requirement
x SST
x Business Scenario / Rule
x Change Slice
x Risk
x Test Level
x Oracle
```

Minimum schema:

```text
obligation_id
release_batch_id
requirement_id
sst_id
app_id
business_scenario
business_rule
risk_level
code_slice_refs[]
change_refs[]
test_level
oracle_refs[]
coverage_targets[]
status
```

### 3.5 TestCase

```text
case_id
obligation_id
release_batch_id
requirement_id
sst_id
test_level
preconditions[]
data_requirements[]
steps[]
expected_results[]
oracles[]
code_targets[]
coverage_targets[]
evidence_requirements[]
readiness_status
```

A canonical Case may not contain unresolved “TBD / execute then discover / guess later” fields at execution entry.

### 3.6 ETU — Execution Task Unit

```text
etu_id
node_id
obligation_id
case_ids[]
primary_goal
primary_code_slice
test_level
primary_oracle
data_domain
required_capabilities[]
estimated_duration
estimated_cost
status
```

Default design target: 3-8 homogeneous cases, one primary business target, one primary code slice, one test level, one main data strategy, one main oracle family, one primary execution-tool family, normally <=15 minutes predicted execution.

### 3.7 WorkItem / Attempt

WorkItem describes requested work. Attempt describes one concrete execution by one worker under one set of leases.

```text
WorkItem:
  workitem_id
  mission_id
  mission_node_id
  etu_id
  role
  priority
  input_refs[]
  expected_delivery
  required_capabilities[]
  required_resources[]
  state

Attempt:
  attempt_id
  workitem_id
  worker_id
  session_id
  lease_refs[]
  started_at
  ended_at
  actual_result
  assertion_result
  evidence_refs[]
  failure_classification
  state
```

## 4. N1-N10 semantics

- N1 Reality: environment/deployment/routes/tools/auth/model/browser/DB/CAT/Libra/CodeGraph readiness.
- N2 Requirement: BR/SR/TR, rules, roles, states, transitions, negative/boundary/permission/data rules and unknowns.
- N3 Code Analysis: requirement/SST -> changed code -> Controller/DTO/Service/DB/external dependency/side effects; CodeGraph evidence mandatory.
- N4 Test Design: Test Obligations, Cases, Oracles, risk and traceability.
- N5 Test Data: discover/construct/verify/reserve/reuse/release/cleanup, producing DataRefs.
- N6 Executable Readiness: Case -> ExecutableContract including endpoint, payload, data refs, route, assertions, evidence and cleanup.
- N7 Execution: prepare defined preconditions, execute, observe, assert, capture evidence. No upstream redesign.
- N8 Diagnosis & Recovery: independent failure classification and routing.
- N9 Defect: evidence-backed defect/RCA/regression.
- N10 Release Convergence: convergence of entire ReleaseBatch, not a round or a single version.

## 5. Sufficiency gates

Each node MUST produce `NodeDelivery` and `NodeGate`.

NodeGate decisions are strictly:

```text
PASS
NEEDS_REVISION
BLOCKED
HUMAN_GATE
```

No fuzzy completion states.

### N2 gate

Must prove Requirement/SST coverage, rule/role/state/boundary coverage and acceptable unknowns.

### N3 gate

Must prove requirement/SST-code mapping, API/DTO validation, DB constraints, branches, downstream/side-effects and graph evidence. Missing graph evidence means no PASS.

### N4 gate

Every executable case must have precondition, input, steps, expected result, oracle, data requirements, evidence requirements and Requirement/SST/code traceability.

### N5 gate

Required execution data exists or has an explicit constructor/reservation plan and can be verified before execution.

### N6 gate

Endpoint/tool route/input/data/permissions/oracle/evidence are resolvable before N7.

## 6. Semantic back-edge design

N7 failure always goes to N8 before upstream mutation.

N8 classification is persisted and routed:

```text
ENVIRONMENT_GAP  -> N1
REQUIREMENT_GAP  -> N2
ANALYSIS_GAP     -> N3
TEST_DESIGN_GAP  -> N4
TEST_DATA_GAP    -> N5
EXECUTABLE_GAP   -> N6
PRODUCT_DEFECT   -> N9
PROVIDER_AUTH    -> runtime recovery
PROVIDER_QUOTA   -> runtime recovery
PROVIDER_TIMEOUT -> runtime recovery
CAPABILITY_GAP   -> CapabilityBroker
RESOURCE_CONFLICT-> ResourceManager
VALID_TEST_FAILURE -> N9 or controlled N7 regression
FLAKY            -> controlled retry policy
UNKNOWN          -> BLOCKED/diagnosis continuation, never auto-PASS
```

When an upstream NodeDelivery changes, an `ImpactResolver` marks affected downstream assets STALE. Stale cases/data/contracts may not be executed until revalidated.

Example:

```text
N7 -> N8 -> ANALYSIS_GAP -> N3 v4
                         -> ImpactResolver
                         -> affected N4/N5/N6 = STALE
                         -> re-gate
                         -> fresh Attempt at N7
```

## 7. Coverage design

Libra is authoritative coverage feedback, not the planning root.

Flow:

```text
Libra Coverage Gap
 -> changed/uncovered Code Slice
 -> Requirement/SST mapping
 -> existing TestObligation mapping
 -> GapReason classification
 -> responsible node
```

Gap reasons:

```text
NO_REQUIREMENT_MAPPING -> N2/N3 investigation
ANALYSIS_MISSING       -> N3
CASE_MISSING           -> N4
DATA_BLOCKED           -> N5
EXECUTION_BLOCKED      -> N6/N7
PATH_NOT_REACHED       -> N8
UNREACHABLE            -> CoverageExclusionCandidate
```

Direct `uncovered method -> generate arbitrary case` is prohibited.

N10 uses coverage as one mandatory convergence gate alongside Requirement/SST/TestObligation completion, L1-L7 expectations, high-risk coverage, defects, evidence completeness and unresolved blockers.

## 8. Task decomposition design

The decomposer operates per current node and current canonical gap set, not once per mission.

Inputs:

```text
release_batch
current_node
test_obligations
remaining_gaps
risk
code_impact
coverage_gap
resource_state
historical_execution
```

Cohesion signals:

```text
same_requirement
same_sst
same_obligation
same_business_scenario
same_code_slice
same_test_level
same_data_domain
same_oracle
same_execution_tool
```

Anti-cohesion / split signals:

```text
multiple business goals
multiple code slices
mixed test levels
mixed data setup
mixed oracle families
mixed browser/auth contexts
high predicted duration
repeated RCA
tool-call explosion
context growth
high failure heterogeneity
```

The decomposer may split, merge, reprioritize or regenerate ETUs after every meaningful feedback event.

## 9. AgentTeams integration

Role templates may include:

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

These are roles, not permanent sessions.

Normal lifecycle:

```text
WorkItem -> select role -> create fresh worker -> issue leases -> execute -> Evidence/R1 -> close worker
```

A reviewer is fresh for each important NodeDelivery/ETU batch/convergence review and reads canonical delivery/evidence rather than long executor history.

## 10. Session and handoff model

Session is disposable. Persisted truth includes at least:

```text
ReleaseBatch
Mission/MissionNode
NodeDelivery/NodeGate
TestObligation
ETU/WorkItem/Attempt
Worker/session metadata
Capability/Browser/Data/Model leases
Evidence/Defect
CoverageSnapshot
Gap/BackEdge/Transition
```

Captain handoff:

```text
Captain A -> HANDOFF_CHECKPOINT -> R1 -> Captain B -> resume same mission
```

No new mission/team may be created merely because the Captain session changed.

## 11. Capability and resource model

Worker remains STRICT. Missing capability produces `CapabilityRequest`, not automatic failure and not Full Access.

Decision outcomes:

```text
AUTO_GRANT_TEMP_LEASE
DELEGATE_TO_SPECIALIST
HUMAN_GATE
DENY
```

Captain Full Access means control-plane authority; Captain credentials are never delegated to workers.

Resource leases include at least CapabilityLease, BrowserLease, DataLease and ModelAssignment/ModelLease.

## 12. Browser isolation

Browser is not a shared singleton.

```text
BrowserPool
 -> BrowserInstance
 -> BrowserLease
```

Each instance has isolated profile, CDP target/port, BSK session and owner metadata. One browser instance permits one WRITE owner at a time.

AuthKeeper, L4 workers and L5 Journey workers use separate browser ownership. Auth material may be shared when technically safe; browser control may not be shared.

## 13. Model failover

Model assignment belongs to Attempt/Worker, not Mission.

Provider quota/auth/timeout must not fail the mission. The runtime checkpoints current evidence/state, closes/reclassifies the attempt, selects an approved fallback model, starts a fresh worker and resumes the same WorkItem. Existing long-running Agent sessions are not hot-swapped in place.

## 14. Startup readiness

Required readiness chain:

```text
PROCESS_READY
 -> MODEL_AUTH_READY
 -> MODEL_PROVIDER_READY
 -> MODEL_PROBE_READY
 -> MCP_READY
 -> PLUGIN_READY
 -> RUNTIME_READY
 -> WEB_READY
```

401/auth expiry requires refresh, provider-client invalidation/recreation and bounded re-probe. Infinite “loading model” state is prohibited.

## 15. Journey Teaching

Journey Teaching is part of N4/N6 and canonical test assets:

```text
Human Teaching
 -> capture URL/DOM/action/network/request-response/waits/screenshots/role/page-state
 -> Journey Compiler
 -> Journey Candidate
 -> Replay
 -> Benchmark
 -> Human Review
 -> Official Journey Asset
 -> L4/L5 consumption
```

Journey asset must trace to ReleaseBatch/Requirement/SST/TestObligation.

## 16. N10 Release convergence

N10 evaluates the ReleaseBatch across:

```text
Requirement completion
SST completion
TestObligation completion
L1-L7 expected completion
high-risk scenario coverage
incremental coverage threshold
open/blocked defect state
unresolved gap state
evidence completeness
runtime integrity
```

If any mandatory criterion fails, N10 classifies remaining gaps and routes each to its responsible node. `coverage < target -> simply next round` is explicitly insufficient.

## 17. Target behavior example

```text
ReleaseBatch Mission
 -> N2 discovers Requirement/SST rules
 -> N3 proves code/data/API impact
 -> N4 creates obligations/cases
 -> N5 prepares data
 -> N6 compiles executable contracts
 -> Decomposer forms 3-8-case ETUs
 -> Fresh N7 workers execute in parallel where leases allow
 -> Failure enters N8
 -> ANALYSIS_GAP routes back to N3
 -> downstream assets become STALE and are regenerated
 -> fresh N7 attempt verifies
 -> Libra feedback maps to existing obligations
 -> N10 classifies residual gaps
 -> convergence only when release gates are met
```

This behavior, not a fixed number of agents or rounds, is the RC7.2 architecture target.
