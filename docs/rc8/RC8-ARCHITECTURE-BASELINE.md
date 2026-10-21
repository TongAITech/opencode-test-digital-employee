# RC8 Architecture Baseline v1

Status: FROZEN-CANDIDATE

## 1. System shape
RC8 adopts a shared-center / distributed-node architecture.

```text
                           RC8 中央测试平台
                                  │
                 ┌────────────────┼────────────────┐
                 │                │                │
            PostgreSQL          Redis          资产存储
                 │                │                │
                 └────────────────┼────────────────┘
                                  │
                      任务 / 事件 / 资产同步协议
                                  │
             ┌────────────────────┼────────────────────┐
             ▼                    ▼                    ▼
          执行节点A             执行节点B             执行节点C
          Node Agent            Node Agent            Node Agent
             │                    │                    │
            DSH                  DSH                  DSH
             │                    │                    │
       RC7 execution core   RC7 execution core   RC7 execution core
```

Center owns durable state; nodes own AI reasoning and real execution. DSH Session is replaceable.

## 2. Center modules
- 投产/版本/需求/需求投产范围
- 需求分析、代码分析、业务流程、接口、测试用例
- TestRun、WorkItem、Attempt、Mission Graph
- R1 事件接入与投影
- Gap Router / Dependency & Invalidation Engine / Completion Gate
- Node Registry / Capability Registry / Task Lease / Resource Lease
- Artifact Registry / Evidence projection / Report
- Defect
- Skill Registry
- Knowledge Store / System Behavior Graph
- Node package distribution
- Product API/UI

First implementation is a modular monolith with strong module boundaries.

## 3. Node Agent modules
- Registration & heartbeat
- Capability probe & reality qualification
- WorkItem lease client
- local durable queue/checkpoint
- RC7 adapters
- DSH worker bridge
- Artifact Sync client
- Knowledge resolver/cache client
- Skill sync/loader
- platform adapter

Node cannot write Center DB directly.

## 4. Shared identities
Minimum durable IDs:
- production_batch_id
- system_version_id
- requirement_id
- delivery_scope_id
- application_id
- sst_id
- test_run_id
- work_item_id
- node_id
- capability_id
- case_id
- attempt_id
- step_id
- assertion_id
- event_id
- artifact_id
- gap_id
- defect_id
- knowledge_id
- skill_id / skill_version

Execution facts must be traceable through these identities.

## 5. Production and requirement model
`ProductionBatch` anchors a production date/batch.
`Requirement` is stable business identity across iterations.
`RequirementDeliveryScope` is the canonical realization tuple:

```text
ProductionBatch
  └─ Requirement
       ├─ SystemVersion A / Application A / SST A
       ├─ SystemVersion A / Application B / SST B
       └─ SystemVersion B / Application C / SST C
```

One requirement can have multiple historical production iterations. Analysis/design/execution artifacts bind to the correct scope/snapshot, while requirement-level aggregation supports cross-scope behavior.

## 6. Test semantic chain
The canonical test chain is:
`Requirement -> BR/SR/TR -> Risk -> TestIntent -> VerificationPoint -> TestCase -> Preconditions/TestData -> Action -> Oracle/Assertion -> Actual -> Evidence -> Gap/Defect`.

Agent/tool identity is secondary to the business/test semantic chain.

## 7. Closed-loop engine
### Local loop
Plan -> Execute -> Collect Evidence -> Evaluate -> Gap -> Repair -> Re-evaluate.

### Stage routing
Example routing classes:
- AUTH -> authentication capability
- ROUTE -> business-flow/route discovery
- TEST_DATA -> data preparation
- PRECONDITION -> precondition builder
- SCRIPT -> executable-spec/script generation
- DESIGN_GAP -> test design
- CODE_UNCERTAIN -> code analysis
- REQUIREMENT_UNCLEAR -> requirement analysis
- ORACLE/ASSERTION_MISMATCH -> oracle/RCA/defect path
- ENVIRONMENT -> environment truth

### Invalidation
Upstream change invalidates dependent downstream artifacts/results instead of leaving stale green states. Invalidation must be scope-aware and incremental.

### Mission completion
`PLAN_COMPLETE != TEST_SUFFICIENT`.
Mission closes only when completion/sufficiency gates have no unresolved required gaps or approved explicit hold/waiver state.

## 8. Event truth
R1 Event Stream remains runtime truth. Center stores canonical events and builds product projections.
Events include producer identity, node, TestRun/WorkItem/Case/Attempt/Step association, sequence/idempotency key, occurrence time, payload and artifact references.
Plans/future intents use separate records and never masquerade as runtime events.

## 9. Evidence contract
Evidence is typed and provenance-bound. A design document cannot prove execution. Typical evidence types:
- browser action/network capture
- API request/response
- DB query/result
- JUnit/pytest result
- log
- screenshot/video
- generated script + execution result
- codegraph query result

Completion may wait for required evidence assets to reach AVAILABLE even when runtime events have arrived.

## 10. Artifact Sync
Node Agent provides a durable sync path:
1. produce artifact locally;
2. create manifest with identity/provenance/hash/size;
3. request upload slot;
4. upload/chunk/resume;
5. Center hash verification;
6. metadata relation commit;
7. AVAILABLE.

Center-to-node sync delivers task-scoped documents, scripts, knowledge, flows, skills and data assets. Nodes cache locally but Center stays authoritative for shared assets.

## 11. Skills and tools
Tools/runtime are packaged with or discovered by Node. Skills are versioned capability packages in Center.
A skill declares provides/requires/platform/evidence/tests. Skill presence is not capability qualification. Node must run a reality probe before advertising a capability as VERIFIED.

## 12. Knowledge
Knowledge statuses: candidate -> verified -> stable; later execution can mark it stale and create a new version.
Knowledge is structured and scoped by requirement/system/version/application/SST/page/API/table/class/method/type as applicable. Retrieval is task-scoped; do not dump the full knowledge base into DSH context.
Vector embeddings are optional enhancement, not a hard dependency.

## 13. Business-flow / system-behavior graph
Business flow records:
- human/business steps;
- UI actions/page states;
- API sequence;
- variable/data bindings;
- auth dependencies;
- state dependencies;
- backend/service/DB associations where discovered;
- evidence and replay history.

Verified flows contribute to System Behavior Graph: page/action -> API -> auth -> application/service -> code -> DB/state.

## 14. Node control
Node states are simple: 在线 / 空闲 / 执行中 / 维护中 / 离线 / 异常.
Capabilities are independently qualified. A node may stay online while some capability is unavailable.

Task lease prevents ambiguous ownership. Lost lease does not imply blind replay; Center freezes/recovers based on last runtime truth and action idempotency/risk.
Resource leases protect shared test accounts/data/business objects/environment resources during write operations.

## 15. Single vs multi-node
Single-node is a full product mode.
Multi-node adds parallel execution, sharing and handoff. The same TestRun/WorkItem/event/artifact protocols apply in both modes.

## 16. Platform/deployment
Canonical shell entrypoints run under Windows Git Bash and Xinchuang Linux bash. Platform-specific binaries live behind adapters (`windows`, `linux`, architecture variants). Dispatch uses verified capability.

Node package is downloadable from Center and contains the frozen redistributable RC7 offline toolset plus RC8 Node Agent/adapters. Skills can update independently from the heavyweight tool package.

## 17. Migration strategy
Migration rule for each RC7 capability:
1. capture RC7 verified baseline/evidence;
2. wrap with RC8 adapter;
3. prove RC8 equivalent capability is not worse;
4. prove RC8 added behavior (central event/evidence/traceability/knowledge as applicable);
5. only then mark migration REALITY_VERIFIED.
