# RC8 Requirement Traceability Matrix

Status: ACTIVE / NO-DISCOUNT
Rule: every requirement traces `requirement -> design -> code -> automated proof -> target-bank reality -> product surface -> RC7 regression -> closure`. `CLOSED` is forbidden when any applicable link is missing.

Binding design set:
- `RC8-MASTER-CONTRACT.md`
- `RC8-ARCHITECTURE-BASELINE.md`
- `RC8-PRODUCT-BASELINE.md`
- `RC7-TO-RC8-GAP-MATRIX.md`
- `RC8-NO-DISCOUNT-DELIVERY-CONTRACT.md`
- `RC8-IMPLEMENTATION-BLUEPRINT-v2.md`
- `RC8-CAPABILITY-CLOSURE-MATRIX.md`
- `RC8-L1-L7-ACCEPTANCE-CONTRACT.md`
- `RC8-MISSION-GRAPH-CONTRACT.md`
- `RC8-PRODUCT-PROJECTION-MAP.md`
- `RC8-RC7-REGRESSION-CATALOG.md`
- `RC8-WAVE-DELIVERY-GATES.md`

## A. Architecture / runtime truth

| ID | Requirement | Design anchor | Implementation evidence required | Product/Reality | Status |
|---|---|---|---|---|---|
| RC8-R001 | Preserve RC7 reality-verified capabilities without regression | Master §2/§17; Blueprint | adapter + regression catalog | bank reality comparison | OPEN |
| RC8-R002 | Single node is fully functional, not crippled mode | Architecture §15 | full single-node mission | 测试任务 | OPEN |
| RC8-R003 | Shared Center supports multiple users/nodes | Architecture §1/14 | concurrency/task lease | 节点/任务 | OPEN |
| RC8-R004 | TestRun durable state independent of DSH Session | Architecture §2/7; Mission Graph | durable domain/checkpoint | rotate/resume reality | PARTIAL |
| RC8-R005 | Node registration/heartbeat/status | Architecture §14 | Center/Node code | 执行节点 | CI_VERIFIED |
| RC8-R006 | Capability qualification uses real probes/evidence | Architecture §11/14 | qualification state machine | 节点能力证据 | CI_VERIFIED |
| RC8-R007 | Node downloadable from Center | Master §12 | package repository/API | 执行节点 | OPEN |
| RC8-R008 | Node contains frozen RC7 offline toolset | Master §12 | manifest/package gate | package reality | PARTIAL |
| RC8-R009 | No public-internet runtime install dependency | Master §12 | dependency manifest/check | clean bank install | OPEN |
| RC8-R010 | Windows Git Bash canonical startup | Master §12 | shell/platform adapter | bank Windows | REALITY_VERIFIED_PARTIAL |
| RC8-R011 | Xinchuang Linux bash startup | Master §12 | Linux adapter | bank Linux | OPEN |
| RC8-R012 | Platform differences behind adapters | Architecture §16 | platform abstraction | capability view | PARTIAL |
| RC8-R013 | Center owns durable task/event/evidence/knowledge truth | Architecture §1-3 | Center persistence/protocol | product projections | PARTIAL |
| RC8-R014 | Node durable queue protects outage periods | Architecture §3/10 | queue/replay | outage reality | OPEN |
| RC8-R015 | Task Lease controls WorkItem ownership | Architecture §14 | lease service/client | task/node history | CI_VERIFIED |
| RC8-R016 | Resource Lease prevents data/account/object collision | Architecture §14 | resource lease domain | task/system info | OPEN |
| RC8-R017 | R1 Event Stream is runtime truth | Architecture §8 | R1 ledger | replay/projection | CI_VERIFIED |
| RC8-R018 | Plan/future intent cannot enter runtime truth | Master §2 | auth/schema gates | regression | CI_VERIFIED |
| RC8-R019 | Evidence typed/hash/provenance/assertion-bound | Architecture §9/10 | Evidence domain | shared viewer | PARTIAL |
| RC8-R020 | Artifact Sync supports logs/screenshots/HAR/XML/SQL/scripts/data | Architecture §10 | artifact adapters | Evidence | PARTIAL |
| RC8-R021 | Artifact resumable upload + hash + AVAILABLE | Architecture §10 | protocol/repository | bank upload | CI_VERIFIED |
| RC8-R022 | Center-to-node task-scoped asset sync | Architecture §10 | download/cache | task runtime | OPEN |
| RC8-R023 | Skills Center-versioned/distributed/qualified | Architecture §11 | Skill Registry | 知识/节点 | OPEN |
| RC8-R024 | Knowledge Center-durable/versioned/evidence-backed/task-scoped | Architecture §12 | Knowledge Store/resolver | 知识库 | OPEN |
| RC8-R025 | Self-evolution accumulates verified assets, not hidden model training | Master §5 | candidate/verify/version | 知识库 | OPEN |
| RC8-R026 | Node cannot directly publish unverified global knowledge/skill | Master §5 | governance workflow | Knowledge/Skill UI | OPEN |
| RC8-R027 | Business flow captures human/page operation steps | Architecture §13 | flow domain | 业务流程 | OPEN |
| RC8-R028 | Business flow captures API/data/auth/state dependency/order | Architecture §13 | flow relation model | 业务流程 | OPEN |
| RC8-R029 | Flow requires replay/verification before trusted | Master §6 | replay state/evidence | 流程历史 | OPEN |
| RC8-R030 | System Behavior Graph connects Page/API/Auth/Service/Code/DB/State | Architecture §13 | graph domain | 业务流程/接口 | OPEN |

## B. Mission / closed-loop / completion

| ID | Requirement | Design anchor | Required proof | Status |
|---|---|---|---|---|
| RC8-R031 | Node-local Plan->Execute->Evidence->Evaluate->Gap->Repair->Reevaluate loop | Master §4; Mission Graph | real multi-attempt loop | OPEN |
| RC8-R032 | Gap is durable first-class object with owner/route/evidence | Mission Graph §6/7 | Gap domain/router | OPEN |
| RC8-R033 | Upstream change invalidates dependent downstream results | Architecture §7; Mission Graph §8 | invalidation tests/reality | OPEN |
| RC8-R034 | PLAN_COMPLETE != TEST_SUFFICIENT | Master §2/4 | domain/API cannot cross-promote | PARTIAL |
| RC8-R035 | Stage execution separated from Stage sufficiency | No-Discount §1 | scoped status/state machine | OPEN |
| RC8-R036 | Layer execution separated from Layer sufficiency | L1-L7 Contract | scoped layer state | OPEN |
| RC8-R037 | Mission sufficiency separate from Release decision | Mission Graph §10/11 | mission/release objects | OPEN |
| RC8-R038 | Retry requires failure class/policy; no blind retry | Mission Graph §7 | failure router tests | OPEN |
| RC8-R039 | Human Gate/waiver explicit, governed and evidence-backed | Mission Graph §12 | human gate domain | OPEN |
| RC8-R040 | Session rotation/restart continues same WorkItem/TestRun | Mission Graph §13/14 | checkpoint/handoff reality | OPEN |

## C. Delivery/scope domain

| ID | Requirement | Design anchor | Product | Status |
|---|---|---|---|---|
| RC8-R041 | Production batch/date is top-level delivery context | Architecture §5 | 投产管理 | PARTIAL |
| RC8-R042 | Requirement maps to multiple versions/apps/SSTs per batch | Architecture §5 | 投产/需求 | PARTIAL |
| RC8-R043 | Same requirement iterates across production batches | Architecture §5 | 需求历史 | OPEN |
| RC8-R044 | Scope-local/cross-app/cross-system/E2E cases supported | Product §9 | 用例/任务 | OPEN |

## D. Requirement analysis / code analysis / design

| ID | Requirement | Design anchor | Acceptance | Product | Status |
|---|---|---|---|---|---|
| RC8-R045 | Requirement analysis outputs BR/SR/TR/rules/states/roles/data/risks/VP/unknowns | Blueprint §8 | structured evidence-backed output | 需求管理 | OPEN |
| RC8-R046 | Requirement analysis is iterative with independent sufficiency evaluator | Blueprint §8 | gap->delta analysis | 需求/任务 | OPEN |
| RC8-R047 | Git is code-change/snapshot authority | Blueprint §9 | snapshot/diff freshness | 代码分析 | CI_VERIFIED |
| RC8-R048 | Java changes require real CodeGraph structural evidence | Blueprint §9 | context/caller/callee/dependency/impact | 代码分析 | TOOL_BANK_REALITY_VERIFIED |
| RC8-R049 | Code analysis includes semantic impact/risk/L1-L7 test impact | Blueprint §9 | real DSH semantic analysis | 代码分析 | IMPLEMENTED_PARTIAL |
| RC8-R050 | Code analysis iterates until sufficiency or explicit gap | Blueprint §9 | follow-up query loop | 代码分析 | OPEN |
| RC8-R051 | Test design model Risk->Intent->VerificationPoint->Case->Oracle | Blueprint §10 | traceability tests | 测试用例 | OPEN |
| RC8-R052 | Design evaluates multidimensional coverage, not case count | Blueprint §10 | coverage matrix | 用例/任务 | OPEN |
| RC8-R053 | Design insufficient -> Delta Design -> re-evaluate | Blueprint §10 | real iterative design | AI闭环 | OPEN |
| RC8-R054 | Oracle has source/version/provenance and independent change review | Blueprint §11/No-Discount | oracle governance | 用例/缺陷 | OPEN |
| RC8-R055 | ExecutableSpec required before execution dispatch | Blueprint §11 | contract validator | 用例详情 | OPEN |

## E. Test data / precondition / auth / route

| ID | Requirement | Design anchor | Acceptance | Status |
|---|---|---|---|---|
| RC8-R056 | Test data Discover->Build/Select->Validate->Lease->Prepare->Use->Readback->Cleanup/Release | Blueprint §17 | full lifecycle | OPEN |
| RC8-R057 | Hidden manual preconditions are not normal autonomous path | No-Discount §12 | explicit assets | OPEN |
| RC8-R058 | Fresh 4A each login/re-auth; no stale cookie/history fallback | Blueprint §18 | bank auth regression | OPEN |
| RC8-R059 | Expired auth re-auths and resumes same WorkItem | Blueprint §18 | expiry/recovery | OPEN |
| RC8-R060 | API routes are observed/verified, never guessed | Blueprint §19 | no-route-guess regression | OPEN |
| RC8-R061 | Route knowledge has source/confidence/version/freshness/revalidation | Blueprint §19 | stale->revalidate | OPEN |

## F. L1 autonomous testing

| ID | Requirement | Design anchor | Acceptance | Product | Status |
|---|---|---|---|---|---|
| RC8-R062 | L1 tests derive from requirement/code risk/VP | L1-L7 §2 | trace Risk/VP->Case | 用例 | OPEN |
| RC8-R063 | JUnit/TestNG/pytest scripts generated from ExecutableSpec | L1-L7 §2 | fidelity + compile | 用例 | OPEN |
| RC8-R064 | Script validation checks assertion/fixture/tool/no forbidden skip | L1-L7 §2 | validator tests | 用例 | OPEN |
| RC8-R065 | Maven/JUnit real runner uses current fresh evidence | L1-L7 §2 | bank tool reality | Attempt | TOOL_BANK_REALITY_VERIFIED |
| RC8-R066 | pytest real runner supported where applicable | L1-L7 §2 | target reality | Attempt | OPEN |
| RC8-R067 | JaCoCo real collection is mandatory for Java changed-code coverage | L1-L7 §2 | fresh XML/artifact | Coverage | OPEN |
| RC8-R068 | coverage.py supported for Python | L1-L7 §2 | real report | Coverage | OPEN |
| RC8-R069 | Changed method/line/branch coverage maps Git+CodeGraph+coverage | L1-L7 §2 | mapper reality | Coverage | OPEN |
| RC8-R070 | Critical requirement/method/branch policy gates L1 sufficiency | L1-L7 §2 | threshold policy | Coverage | OPEN |
| RC8-R071 | Global project coverage alone cannot close L1 | L1-L7 §2 | negative gate test | Coverage | OPEN |
| RC8-R072 | Mutation/assertion-strength used for configured high-risk scope | L1-L7 §2 | mutation reality | Coverage | OPEN |
| RC8-R073 | Coverage gap becomes durable Gap and routes to Test Design | Mission Graph | gap route reality | AI闭环 | OPEN |
| RC8-R074 | Delta test/script generated only for uncovered/insufficient scope | L1-L7 §2 | delta trace | AI闭环 | OPEN |
| RC8-R075 | Targeted rerun creates new Attempt and preserves old history | L1-L7 §2 | attempt history | 用例/任务 | OPEN |
| RC8-R076 | Coverage recalculated after rerun | L1-L7 §2 | old/new comparison | Coverage | OPEN |
| RC8-R077 | L1 convergence loop continues until sufficient/hold | Wave W-B | multi-attempt bank mission | AI闭环 | OPEN |
| RC8-R078 | JUnit all-green alone cannot set L1 SUFFICIENT | No-Discount | status regression | 任务 | OPEN |

## G. Failure / RCA / defect

| ID | Requirement | Design anchor | Acceptance | Status |
|---|---|---|---|---|
| RC8-R079 | Canonical failure ownership classes implemented | No-Discount §9 | classifier | OPEN |
| RC8-R080 | PRODUCT fail creates defect candidate, not test repair-to-green | No-Discount §9/16 | defect route | OPEN |
| RC8-R081 | SCRIPT/SPEC/ORACLE/DATA/AUTH/ROUTE/ENV failures route correctly | Mission Graph | route tests/reality | OPEN |
| RC8-R082 | Defect links Expected/Actual/Assertion/Evidence/RCA/code impact | Product §12 | defect detail | OPEN |
| RC8-R083 | Defect fix snapshot links regression Attempt | Product §12 | regression history | OPEN |
| RC8-R084 | Testing mission success may coexist with Release HOLD due to defect | Mission Graph §11 | state semantics | OPEN |

## H. L2-L7 professional layers

| ID | Requirement | Design anchor | Key acceptance | Status |
|---|---|---|---|---|
| RC8-R085 | L2 dedicated repository/DB worker | L1-L7 §3 | real ORM/CRUD/transaction/readback | OPEN |
| RC8-R086 | L2 sufficiency evaluates DB/data/risk coverage | L1-L7 §3 | not single SQL | OPEN |
| RC8-R087 | L3 dedicated API/service worker | L1-L7 §4 | verified route/auth/request-response/backend oracle | OPEN |
| RC8-R088 | L3 sufficiency covers positive/negative/boundary/permission/side effects | L1-L7 §4 | gap loop | OPEN |
| RC8-R089 | L4 dedicated real Browser worker | L1-L7 §5 | meaningful page actions/network/evidence | OPEN |
| RC8-R090 | Zero-step/awaiting-worker cannot be EXECUTED_PASS | L1-L7 §5 | permanent regression | OPEN |
| RC8-R091 | L4 sufficiency covers journeys/states/permissions/oracles | L1-L7 §5 | gap loop | OPEN |
| RC8-R092 | L5 requires one coherent correlated business journey | L1-L7 §6 | cannot combine fragmented green | OPEN |
| RC8-R093 | L5 requires final business-state readback | L1-L7 §6 | E2E reality | OPEN |
| RC8-R094 | L6 workload/NFR/percentile/error/resource model | L1-L7 §7 | perf reality | OPEN |
| RC8-R095 | L6 without authoritative NFR = BASELINE_ONLY | L1-L7 §7 | no fabricated PASS | OPEN |
| RC8-R096 | L7 authn/authz/privilege/negative/security coverage | L1-L7 §8 | real role/security tests | OPEN |
| RC8-R097 | Scanner unavailable does not block all L7 | L1-L7 §8 | partial capability regression | OPEN |
| RC8-R098 | L7 findings lifecycle PROBE->CANDIDATE->CONFIRMED | L1-L7 §8 | evidence gate | OPEN |

## I. Product system

| ID | Requirement | Product projection anchor | Status |
|---|---|---|---|
| RC8-R099 | UI Chinese-first, Apple-inspired, restrained; no dashboard/giant cards | Product Projection §1 | OPEN |
| RC8-R100 | 投产管理 shows batch/scope/TestRun/sufficiency/release | Product Projection §4 | OPEN |
| RC8-R101 | 版本管理 shows requirement/SST/TestRun/layer sufficiency/defects/gaps | §5 | OPEN |
| RC8-R102 | 需求管理 shows BR/SR/TR/code/risk/VP/cases/execution/defect/knowledge | §6 | OPEN |
| RC8-R103 | 代码分析 structured snapshot/change/call/impact/risk/test/evidence/history | §7 | OPEN |
| RC8-R104 | 业务流程 shows human steps/API/data/auth/state/evidence/replay | §8 | OPEN |
| RC8-R105 | 测试接口 shows observed route/auth/sample/source/confidence/freshness | §9 | OPEN |
| RC8-R106 | 测试用例 shows Risk/VP/precondition/data/steps/Expected/Oracle/Attempts/Evidence | §10 | OPEN |
| RC8-R107 | 测试任务 shows Mission Graph/Attempt/Coverage/Gap/route-back/invalidation/convergence | §11 | OPEN |
| RC8-R108 | 测试报告 answers tested/not-tested/coverage/gap/defect/risk/sufficiency/release | §12 | OPEN |
| RC8-R109 | 缺陷管理 shows Expected/Actual/Evidence/RCA/code/fix/regression | §13 | OPEN |
| RC8-R110 | 知识库 shows lifecycle/provenance/freshness/reuse | §14 | OPEN |
| RC8-R111 | 执行节点 separates installed/discovered/qualified/reality capability | §15 | PARTIAL |
| RC8-R112 | 系统信息 shows env/DB/accounts/resources/skills/diagnostics/package | §16 | OPEN |
| RC8-R113 | Global cross-navigation traces requirement->analysis->case->attempt->defect/knowledge/evidence | §17 | OPEN |
| RC8-R114 | Front-end cannot infer PASS from counts | §3 | OPEN |
| RC8-R115 | Invalidated/stale/history states visible; no silent overwrite | §19 | OPEN |

## J. Knowledge / Skill / evolution

| ID | Requirement | Design anchor | Status |
|---|---|---|---|
| RC8-R116 | Knowledge lifecycle candidate->verified->stable->stale/version | Blueprint §20 | OPEN |
| RC8-R117 | Task-scoped knowledge resolver avoids full context dump | Blueprint §20 | OPEN |
| RC8-R118 | New DSH session reuses verified knowledge | RC7 Regression 160 | OPEN |
| RC8-R119 | Skill Registry versions provides/requires/platform/evidence/tests | Blueprint §20 | OPEN |
| RC8-R120 | Skill presence != capability qualification | Blueprint §20 | OPEN |

## K. Deployment / recovery

| ID | Requirement | Design anchor | Acceptance | Status |
|---|---|---|---|---|
| RC8-R121 | Separate RC8-CENTER and RC8-NODE complete deliverables | Blueprint §24 | clean package | OPEN |
| RC8-R122 | Node state/identity outside versioned package | Blueprint §4/24 | upgrade keeps identity | IMPLEMENTED_DIRECTION |
| RC8-R123 | Complete package only; no patch-only bank handoff | No-Discount §22 | manifest/hash/zip | CI_VERIFIED_PARTIAL |
| RC8-R124 | Center restart preserves domain/R1/projections | Blueprint §23/24 | restart reality | OPEN |
| RC8-R125 | Node restart preserves queue/work identity | Blueprint §23 | restart reality | OPEN |
| RC8-R126 | DSH restart/session rotation preserves mission | Mission Graph §13/14 | bank rotate/resume | OPEN |
| RC8-R127 | Upgrade preserves Center data/assets/Node identity; rollback supported | Wave W-J | upgrade/rollback reality | OPEN |
| RC8-R128 | Center deploys PostgreSQL/Redis/artifact production persistence | Blueprint §24 | server deployment | OPEN |

## L. RC7 permanent regression requirements

All items in `RC8-RC7-REGRESSION-CATALOG.md` are mandatory acceptance inputs. They are not repeated here as separate RC8-Rxxx rows; each implementation row must link applicable `RC7-REG-*` IDs in closure evidence.

Critical clusters that must never disappear:
- Director self-execution/runtime truth contamination
- Session/context loss
- Node identity/package upgrade
- Maven false block/stale Surefire/all-green != L1
- CodeGraph not invoked/stale/one-query != analysis
- requirement/design one-pass insufficiency
- test data/precondition weakness
- stale-cookie/manual-history 4A
- guessed route/404
- L2 weak DB evidence
- L3 weak request/assertion evidence
- L4 zero-step/awaiting-worker fake PASS
- L5 fragmented E2E
- L6 BASELINE/NFR ambiguity
- L7 scanner-all-blocked mistake
- product/evidence/projection drift
- knowledge loss across sessions
- autonomous loop/route-back/invalidation failure

## M. Trace evidence schema

For every RC8-Rxxx row, construction must progressively record:
- architecture/design decision ID
- capability closure row ID
- code paths and commit SHA
- automated test paths
- CI run ID/result
- bank Reality evidence/artifact IDs
- product projection/API/page
- RC7-REG IDs covered
- source/config snapshot
- current status
- closure rationale

No requirement is deleted or weakened to make implementation easier. Any scope change requires explicit baseline decision and history.