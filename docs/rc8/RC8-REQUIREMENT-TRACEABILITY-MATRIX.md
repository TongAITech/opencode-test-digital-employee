# RC8 Requirement Traceability Matrix

Status: ACTIVE
Rule: every requirement must trace to design -> code -> automated test -> reality evidence -> product surface (if applicable). Final state is `CLOSED` only after reality verification.

| ID | Requirement | Design anchor | Target wave | Status |
|---|---|---|---|---|
| RC8-R001 | Preserve RC7 reality-verified capabilities; no regression | Master Contract §2/§17 | W0-W2 | OPEN |
| RC8-R002 | Single node is fully functional, not a crippled mode | Architecture §15 | W1 | OPEN |
| RC8-R003 | Shared Center supports multiple users/DSH nodes testing different requirements | Architecture §1/§14 | W7 | OPEN |
| RC8-R004 | TestRun durable state is independent of DSH Session | Architecture §2/§7 | W1/W3 | OPEN |
| RC8-R005 | Node registration, heartbeat, status and query management | Architecture §14; Product §14 | W1 | OPEN |
| RC8-R006 | Node capability qualification uses real probes, not installed-package claims | Architecture §11/§14 | W1/W2 | OPEN |
| RC8-R007 | Node can be downloaded from Center | Master Contract §12 | W1/W9 | OPEN |
| RC8-R008 | Node package contains frozen redistributable RC7 offline toolset | Master Contract §12 | W2/W9 | OPEN |
| RC8-R009 | No public-internet install dependency for bank runtime | Master Contract §12 | W9 | OPEN |
| RC8-R010 | Windows startup via Git Bash shell entrypoint | Master Contract §12 | W1/W9 | OPEN |
| RC8-R011 | Xinchuang Linux startup via bash | Master Contract §12 | W1/W9 | OPEN |
| RC8-R012 | Platform differences behind adapters; common protocol | Architecture §16 | W1 | OPEN |
| RC8-R013 | Center owns task/event/knowledge/evidence truth; Node does not write DB directly | Architecture §1-3 | W0/W1 | OPEN |
| RC8-R014 | Node local durable queue protects events/assets during temporary Center outage | Architecture §3/§10 | W3 | OPEN |
| RC8-R015 | Task leases control WorkItem ownership and safe recovery | Architecture §14 | W1/W3 | OPEN |
| RC8-R016 | Resource leases prevent test account/data/business-object collisions | Architecture §14 | W5/W7 | OPEN |
| RC8-R017 | R1 Event Stream remains runtime truth | Architecture §8 | W0/W3 | OPEN |
| RC8-R018 | Plan/future intent cannot be written as runtime execution truth | Master Contract §2 | W0 | OPEN |
| RC8-R019 | Evidence typed, hashed, provenance-bound and linked to Assertion | Architecture §9/§10 | W0/W3 | OPEN |
| RC8-R020 | Screenshots/video/log/HAR/JSON/SQL/scripts/data assets upload via Artifact Sync | Architecture §10 | W3 | OPEN |
| RC8-R021 | Large assets support resumable/chunk upload and AVAILABLE state | Architecture §10 | W3 | OPEN |
| RC8-R022 | Center-to-node asset sync delivers task-scoped docs/scripts/skills/knowledge/data | Architecture §10 | W3/W6 | OPEN |
| RC8-R023 | Skills are Center-versioned/distributed and node-verified | Architecture §11 | W6 | OPEN |
| RC8-R024 | Knowledge is Center-durable, versioned, evidence-backed and task-scoped | Architecture §12 | W6 | OPEN |
| RC8-R025 | Self-evolution improves shared knowledge/skills/strategies/assets, not model-training dependency | Master Contract §5 | W6 | OPEN |
| RC8-R026 | A node cannot directly publish unverified knowledge/skills to all nodes | Master Contract §5 | W6 | OPEN |
| RC8-R027 | Business-flow recording captures operation steps and page actions | Architecture §13; Product §7 | W4 | OPEN |
| RC8-R028 | Business-flow recording captures API order, data dependency, auth dependency and state dependency | Architecture §13 | W4 | OPEN |
| RC8-R029 | Recorded flow supports replay/verification before becoming trusted knowledge | Master Contract §6 | W4 | OPEN |
| RC8-R030 | Page/API/Auth/Service/Code/DB relationships can form System Behavior Graph | Architecture §13 | W4/W6 | OPEN |
| RC8-R031 | Closed loop exists at node-local, cross-stage and mission levels | Master Contract §4 | W5 | OPEN |
| RC8-R032 | Gap is a durable object and routes failure back to correct stage | Architecture §7 | W5 | OPEN |
| RC8-R033 | Upstream changes invalidate dependent downstream artifacts/results | Architecture §7 | W5 | OPEN |
| RC8-R034 | `PLAN_COMPLETE != TEST_SUFFICIENT` and release follows truth gates | Master Contract §2/§4 | W0/W5 | OPEN |
| RC8-R035 | Test data discovery/build/validate/lease/reuse/release loop | Master Contract §10 | W4/W5 | OPEN |
| RC8-R036 | Test-data sensitivity/desensitization is not a blocking RC8 delivery scope | Master Contract §10 | W4/W5 | OPEN |
| RC8-R037 | Production date/batch is top-level delivery context | Architecture §5; Product §3 | W0/W8 | OPEN |
| RC8-R038 | One requirement may map to multiple system versions/apps/SSTs in one batch | Architecture §5 | W0/W8 | OPEN |
| RC8-R039 | Same requirement may iterate across multiple production batches | Architecture §5 | W0/W8 | OPEN |
| RC8-R040 | Scope-local and cross-application/cross-system/E2E cases are supported | Architecture §5/§6; Product §9 | W5/W8 | OPEN |
| RC8-R041 | Version management supports query/create/edit/save/delete and requirement/SST association | Product §4 | W8 | OPEN |
| RC8-R042 | Requirement management supports query/create/edit/save/delete and large detail with BR/SR/TR/code/cases/execution | Product §5 | W8 | OPEN |
| RC8-R043 | Code analysis supports version/requirement/SST/application query and structured snapshots | Product §6 | W2/W8 | OPEN |
| RC8-R044 | Test interface management exposes real captured API samples and auth/request knowledge | Product §8 | W4/W8 | OPEN |
| RC8-R045 | Test case management supports version/requirement/SST/layer query, CRUD and detailed execution history | Product §9 | W8 | OPEN |
| RC8-R046 | Every TestRun creates a report showing every executed case, Actual, Assertion and evidence | Product §11 | W3/W8 | OPEN |
| RC8-R047 | System information manages environment/database/test-account/application/resource info | Product §15 | W8 | OPEN |
| RC8-R048 | Knowledge management exposes AI runtime knowledge such as route summaries | Product §13 | W6/W8 | OPEN |
| RC8-R049 | Defect is first-class with evidence/RCA/regression linkage | Product §12 | W5/W8 | OPEN |
| RC8-R050 | Node management page shows node, operator, status, capability, task, heartbeat, install/qualification | Product §14 | W1/W8 | OPEN |
| RC8-R051 | UI is Chinese-first, Apple-inspired, simple/clear/spacious and avoids noisy dashboards/cards | Product §1 | W8 | OPEN |
| RC8-R052 | Product must explain what was tested without reading DSH Web/logs | Product §17 | W1/W8 | OPEN |
| RC8-R053 | Large detail layout must avoid cramped content/nested small dialogs | Product §1 | W8 | OPEN |
| RC8-R054 | Center hosts node package/upgrade entries and offline-tool manifest | Product §14 | W1/W9 | OPEN |
| RC8-R055 | Clean install verification is mandatory before delivery | Master Contract §11/§12 | W9 | OPEN |
| RC8-R056 | Installation PASS requires real end-to-end smoke | Master Contract §11/§12 | W9 | OPEN |
| RC8-R057 | Upgrade preserves Center data/assets; rollback supported | Master Contract §11 | W9 | OPEN |
| RC8-R058 | Center restart, Node restart and DSH restart preserve truthful recoverability | Master Contract §12 | W3/W9 | OPEN |
| RC8-R059 | Product and runtime status come from truthful projections, not disconnected CRUD/file views | Master Contract §2/§9 | W3/W8 | OPEN |
| RC8-R060 | RC7 canonical gaps all follow OPEN -> IMPLEMENTED -> REALITY_VERIFIED -> CLOSED | Gap Matrix §4 | W0-W10 | OPEN |

## Trace columns to add during construction
For each requirement, implementation commits must progressively add:
- architecture/design decision ID
- code paths
- automated test paths
- reality evidence path/ID
- product page/surface
- current HEAD verified
- closure status

No requirement is deleted to make implementation easier. A scope change requires explicit baseline decision/history.
