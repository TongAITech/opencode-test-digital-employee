# RC8 Requirement Traceability Matrix

Status values: OPEN -> IMPLEMENTED -> TESTED -> REALITY_VERIFIED -> CLOSED

| ID | Requirement | Design owner | Planned slice | Status |
|---|---|---|---|---|
| RC8-R001 | Preserve RC7 reality-verified capabilities | Master Contract / migration gates | W2 | OPEN |
| RC8-R002 | R1 remains sole durable runtime truth | Architecture Baseline | W0/W3 | OPEN |
| RC8-R003 | TestRun/Mission survives DSH session loss | Architecture Baseline | W1/W3 | OPEN |
| RC8-R004 | Single node supports full functional chain | Architecture Baseline | W1-W6 | OPEN |
| RC8-R005 | Multiple DSH nodes share one central platform | Architecture Baseline | W7 | OPEN |
| RC8-R006 | Central product is team-accessible shared system | Product Baseline | W1/W8 | OPEN |
| RC8-R007 | Node registers/heartbeats and exposes verified capabilities | Node control plane | W1 | TESTED |
| RC8-R008 | WorkItem leasing and safe lease recovery | Node control plane | W1/W3 | OPEN |
| RC8-R009 | Resource leasing for accounts/test data/business objects | Architecture Baseline | W7 | OPEN |
| RC8-R010 | Node downloadable from Center | Deployment | W9 | OPEN |
| RC8-R011 | Node package includes RC7 offline toolset/capability equivalents | Deployment | W2/W9 | OPEN |
| RC8-R012 | Windows node starts via Git Bash shell | Deployment | W9 | OPEN |
| RC8-R013 | Xinchuan Linux node starts via bash | Deployment | W9 | OPEN |
| RC8-R014 | Platform/CPU adapters are capability-based, not exact-version pinned | Architecture Baseline | W1/W9 | OPEN |
| RC8-R015 | Runtime artifacts upload through Node Agent, never direct DB writes | Artifact Sync | W3 | TESTED |
| RC8-R016 | Screenshot/video/log/HAR/JSON/script/data artifacts are centrally persisted | Artifact Sync | W3 | OPEN |
| RC8-R017 | Evidence binds to case/attempt/step/assertion | Artifact Sync | W3 | TESTED |
| RC8-R018 | Large artifacts support durable/resumable upload | Artifact Sync | W3 | OPEN |
| RC8-R019 | Node keeps durable upload queue during Center/network outage | Artifact Sync | W3 | OPEN |
| RC8-R020 | Center-to-node artifact sync supplies task-scoped assets | Artifact Sync | W3/W6 | OPEN |
| RC8-R021 | Business flow records operation steps | Business Flow | W4 | OPEN |
| RC8-R022 | Business flow records API call order | Business Flow | W4 | OPEN |
| RC8-R023 | Business flow records auth/data/state/business dependencies | Business Flow | W4 | OPEN |
| RC8-R024 | Business flow supports replay/validation before dependency promotion | Business Flow | W4 | OPEN |
| RC8-R025 | Route knowledge prevents repeated API guessing/404 exploration | Knowledge + Business Flow | W4/W6 | OPEN |
| RC8-R026 | Node-local closed loop execute/evaluate/gap/repair/re-evaluate | Loop Engine | W5 | OPEN |
| RC8-R027 | Downstream findings route gaps back to correct upstream node | Loop Engine | W5 | OPEN |
| RC8-R028 | Upstream change invalidates/reopens only impacted downstream outputs | Dependency Engine | W5 | OPEN |
| RC8-R029 | Mission completion requires test sufficiency/convergence | Loop Engine | W5 | OPEN |
| RC8-R030 | Retry is not a substitute for failure classification/gap routing | Loop Engine | W5 | OPEN |
| RC8-R031 | Skills are center-versioned/distributed and node-verified | Skill Registry | W6 | OPEN |
| RC8-R032 | Knowledge is center-durable, versioned and evidence-backed | Knowledge Registry | W6 | OPEN |
| RC8-R033 | Knowledge retrieval works without embeddings | Knowledge Registry | W6 | OPEN |
| RC8-R034 | Runtime learning improves later tasks through verified reuse | Evolution | W6 | OPEN |
| RC8-R035 | Test data supports discovery/construction/validation/lease/reuse/reclaim | Test Data | W5/W7 | OPEN |
| RC8-R036 | Production batch/date is top-level release scope | Domain Model | W0/W8 | OPEN |
| RC8-R037 | Requirement can span multiple system versions/apps/SSTs in one production | Domain Model | W0/W8 | TESTED |
| RC8-R038 | Requirement can iterate across multiple production batches | Domain Model | W0/W8 | OPEN |
| RC8-R039 | RequirementDeliveryScope is canonical implementation/testing scope identity | Domain Model | W0 | TESTED |
| RC8-R040 | Code analysis query by version/requirement/SST/application | Product | W8 | OPEN |
| RC8-R041 | Code analysis is snapshot/versioned and CodeGraph evidenced | Code Analysis | W2/W8 | OPEN |
| RC8-R042 | Test API management exposes runtime-captured request samples and auth behavior | Product / Flow | W4/W8 | OPEN |
| RC8-R043 | Case management supports CRUD/query and detailed precondition/steps/expected | Product | W8 | OPEN |
| RC8-R044 | Case detail preserves multiple execution attempts and assertion results | Product | W3/W8 | OPEN |
| RC8-R045 | Every execution TestRun creates a report record | Reporting | W8 | OPEN |
| RC8-R046 | Report shows each executed case actual/assertions/log/screenshot/video evidence | Reporting | W8 | OPEN |
| RC8-R047 | Defect is first-class and linked to execution/RCA/fix/regression | Defect | W5/W8 | OPEN |
| RC8-R048 | Node management page supports query/detail/capabilities/current task/history | Product | W1/W8 | OPEN |
| RC8-R049 | Center exposes node package and upgrade downloads | Product / Deployment | W9 | OPEN |
| RC8-R050 | System information manages environments/DB/accounts/apps/test resources | Product | W8 | OPEN |
| RC8-R051 | Knowledge page exposes AI runtime-produced knowledge | Product | W6/W8 | OPEN |
| RC8-R052 | Product UI is Chinese-first, Apple-inspired, clean and consistent | Product Baseline | W8 | OPEN |
| RC8-R053 | Large detail views avoid cramped layout and nested-card overload | Product Baseline | W8 | OPEN |
| RC8-R054 | Product pages explain what/why/how/actual/verdict/evidence without DSH logs | Product Baseline | W3/W8 | OPEN |
| RC8-R055 | Center uses PostgreSQL/Redis/artifact storage with durable truth independent of Redis | Architecture Baseline | W1/W3 | OPEN |
| RC8-R056 | Center and node packages support clean install, smoke, upgrade and rollback | Deployment | W9 | OPEN |
| RC8-R057 | Install PASS requires real end-to-end smoke | Deployment | W9 | OPEN |
| RC8-R058 | Restart of Center/node/DSH does not lose durable TestRun/knowledge/evidence | Recovery | W3/W9 | OPEN |
| RC8-R059 | Capability verification is execution/evidence based, not package-presence based | Capability Registry | W1/W2 | TESTED |
| RC8-R060 | Director/control plane cannot fabricate worker/tool execution evidence | Authority | W0/W2 | OPEN |

## Evidence notes for current TESTED rows

- RC8-R007 / RC8-R059: `rc8_control/models.py`, `rc8_control/node_registry.py`, `tests/test_rc8_node_registry.py`; automated RC8 Core Foundation gate. Runtime/package changes force capability requalification.
- RC8-R015 / RC8-R017: `rc8_control/runtime_contracts.py`, `runtime_ingest.py`, `rc8_node/agent.py`, `tests/test_rc8_runtime_contracts.py`, `tests/test_rc8_runtime_ingest.py`, `tests/test_rc8_single_node_vertical.py`. This is an automated in-process vertical slice; PostgreSQL/object-storage/real-network reality verification remains open.
- RC8-R037 / RC8-R039: `RequirementDeliveryScope` plus mapping tests prove the canonical relationship can represent one requirement spanning multiple system-version/application/SST scopes. Full production-batch CRUD/read model remains open.

Every row must eventually link to concrete implementation files, automated tests, reality evidence and closure decision. Code existence alone is insufficient.