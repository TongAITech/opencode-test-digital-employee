# RC8 Architecture Baseline

Status: FROZEN FOR W0/W1

## Architecture layers

### Central control and product plane

Responsibilities:
- production batch/version/requirement/SST master data;
- durable TestRun/Mission/WorkItem state;
- node registry, capability registry and leasing;
- closed-loop Gap routing, dependency invalidation and mission sufficiency;
- central R1 projection and read models;
- artifact/evidence registry;
- knowledge and skill registries;
- reports, defects and product APIs/UI.

### Node Agent layer

Runs on office PCs. Responsibilities:
- register and heartbeat;
- capability discovery and reality qualification;
- lease/renew/release WorkItems;
- start DSH/worker/tool execution through adapters;
- append local runtime records and synchronize R1 events;
- upload artifacts/evidence with durable retry;
- synchronize released skills and task-scoped knowledge;
- survive transient Center/network failure without losing facts.

### RC7 execution core

RC7 runtime and proven offline capabilities remain reusable. RC8 wraps them with identity, node, event and artifact adapters rather than rewriting them.

## Canonical identities

RC8 durable identities:
- production_batch_id
- requirement_id / requirement_iteration_id
- requirement_delivery_scope_id
- system_version_id
- application_id
- sst_id
- test_run_id
- mission_id
- work_item_id
- node_id
- lease_id
- case_id
- attempt_id
- step_id
- assertion_id
- event_id
- artifact_id
- gap_id
- defect_id
- knowledge_id / knowledge_version
- skill_id / skill_version

Session/provider/model IDs may appear as execution metadata but cannot define durable task truth.

## Control flow

`Product -> TestRun -> Mission Graph -> WorkItem -> Lease -> Node Agent -> RC7 Worker/Tool -> R1 Event + Artifact -> Evaluator -> Gap/Pass -> Loop Engine`

A WorkItem is executable only if its dependencies are valid and the chosen node has reality-verified required capabilities.

## Leasing

Node leases are time-bound and renewed by heartbeat. Lease expiry does not automatically authorize destructive replay. Recovery examines R1 truth and the last side-effect boundary before deciding resume, safe retry or human confirmation.

Resource leases cover test accounts, test data and business objects where concurrent mutation can interfere.

## Event protocol

R1 remains sole durable runtime truth. Center accepts idempotent events with node/test-run/work-item identity and sequence/idempotency key. Product pages are projections from durable truth plus business master data.

Planned/intended events are never mixed with executed runtime facts.

## Artifact sync protocol

Two-phase logical lifecycle: declare metadata -> transfer -> hash/size verification -> AVAILABLE. Large files may use chunks/resume. Critical completion gates can require referenced artifacts to be AVAILABLE.

Center-to-node sync supplies task manifests, released skills, relevant knowledge, reusable scripts/data assets and referenced source artifacts.

## Skill model

Skill lifecycle: DRAFT -> TESTED -> RELEASED -> DEPRECATED. A released skill can still be unavailable on a node if its dependencies or reality checks fail.

Node capability state is independent from package presence: DISCOVERED -> REGISTERED -> EXECUTED -> ASSERTED -> EVIDENCE_PERSISTED -> VERIFIED, with ERROR/UNAVAILABLE paths.

## Knowledge model

Knowledge is structured and versioned. Required fields include scope identities, knowledge type, facts/relations, evidence refs, confidence/status, source and last_verified_at.

No new verified knowledge may be created solely from model prose. Promotion requires runtime/document/code evidence appropriate to knowledge type.

## Business behavior graph

RC8 incrementally links:
`Page -> BusinessAction -> API -> Auth/Data Dependency -> Application/Service -> Code -> DB/State -> Observable Result`.

This graph supports flow replay, route reuse, code-risk fusion, test design and cross-application/system E2E design.

## Closed-loop routing examples

- REQUIREMENT_UNCLEAR -> Requirement Analysis
- CODE_UNCERTAIN -> Code Analysis / CodeGraph
- DESIGN_GAP -> Test Design
- TEST_DATA -> Test Data Preparation
- AUTH -> Auth capability
- ROUTE -> Business Flow / Route discovery
- SCRIPT -> Script generation/repair
- ORACLE -> Oracle analysis
- ENVIRONMENT -> Environment preparation/human gate
- PRODUCT_DEFECT -> Defect qualification/RCA

Downstream outputs affected by repaired upstream facts become STALE/REVALIDATION_REQUIRED and are selectively reopened.

## Single-node guarantee

One Center + one Node must support the complete functional chain. Multi-node adds parallelism, collaboration and shared learning only.

## Platform adapters

Common shell lifecycle and protocol, platform adapters below it:
- Windows x86_64 via Git Bash;
- Xinchuan Linux x86_64 via bash;
- Xinchuan Linux aarch64 via bash when required binaries are available.

Unknown/unsupported platform capabilities remain unavailable rather than simulated.

## Initial construction slices

W0: truth, identity, contracts and traceability foundation.
W1: Center skeleton + single Node registry/heartbeat/capability/lease vertical slice.
W2: RC7 capability migration through Node adapters.
W3: central runtime truth, evidence and recovery.
W4: business flow/API/behavior graph.
W5: cross-node closed loop and invalidation.
W6: knowledge, skills and evolution.
W7: multi-node collaboration/resources.
W8: full product completion.
W9: packaging/Windows/Xinchuan Linux/upgrade.
W10: reality audit and bank delivery qualification.