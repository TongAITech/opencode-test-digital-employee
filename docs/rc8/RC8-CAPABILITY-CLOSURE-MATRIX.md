# RC8 Capability Closure Matrix

Status: FROZEN-CANDIDATE
Purpose: make every RC8 capability traceable to architecture, implementation, automated proof, bank Reality proof, product projection, RC7 regression coverage, and closure state.

## 1. Closure rule

A row can become CLOSED only when all applicable columns are complete:

`Design -> Code -> Automated Test -> Reality Evidence -> Product Surface -> Regression -> Traceability`.

A missing column cannot be waived by a green tool run. Scope changes require explicit architecture/baseline decision history.

Status vocabulary:
- OPEN
- IMPLEMENTED
- CI_VERIFIED
- REALITY_VERIFIED
- SUFFICIENT
- CLOSED
- OPEN_INPUT
- PARTIAL

## 2. Foundation / architecture capabilities

| ID | Capability | Design anchor | Required code/domain | Automated proof | Bank Reality | Product surface | RC7 regression | Current state |
|---|---|---|---|---|---|---|---|---|
| ARCH-001 | ProductionBatch / RequirementDeliveryScope | Architecture §5 | domain models + persistence | contract tests | real version/scope import | 投产/版本/需求 | 后管 scope 漂移 | IMPLEMENTED_PARTIAL |
| ARCH-002 | TestRun/WorkItem/Attempt durable identity | Architecture §2/4/8 | Center domain/repository | restart/state tests | real mission restart | 测试任务 | Session丢任务 | CI_VERIFIED_PARTIAL |
| ARCH-003 | R1 runtime truth separation | Master §2; Architecture §8 | R1 ledger/event auth | idempotency/conflict tests | real tool events | 测试任务/报告 | plan污染runtime | CI_VERIFIED |
| ARCH-004 | Evidence contract | Architecture §9/10 | Artifact/Evidence/Assertion binding | upload/hash tests | real logs/xml/graph evidence | Evidence viewer | evidence弱/假执行 | CI_VERIFIED_PARTIAL |
| ARCH-005 | Task Lease | Architecture §14 | Center lease + Node client | ownership/late-write tests | real node execution | 执行节点/任务 | Director/Worker归属模糊 | CI_VERIFIED |
| ARCH-006 | Resource Lease | Architecture §14 | account/data/object leases | collision tests | real shared resource | 系统信息/任务 | 测试数据抢占 | OPEN |
| ARCH-007 | Mission Graph | Blueprint §6 | durable stage graph | transition tests | full SST mission | 测试任务-AI闭环 | 自循环不可见 | OPEN |
| ARCH-008 | Gap Router | Architecture §7 | Gap domain/router | route-class tests | real route-back | 测试任务-Gap | 后阶段不能回路 | OPEN |
| ARCH-009 | Dependency/Invalidation Engine | Architecture §7 | dependency graph + stale state | invalidation regression | upstream change reality | 任务/分析/用例 | 旧绿污染 | OPEN |
| ARCH-010 | Completion/Sufficiency Engine | Master §4 | scoped evaluators | gate tests | real convergence | 任务/报告 | PLAN_COMPLETE误完成 | OPEN |
| ARCH-011 | Session-independent checkpoint/recovery | Blueprint §23 | checkpoint/handoff | rotate/resume tests | DSH session rotation | 任务/节点 | context膨胀/会话丢失 | OPEN |
| ARCH-012 | Durable local Node queue | Architecture §3 | local queue/replay | outage/replay tests | Center断连恢复 | 执行节点 | 上传/任务中断 | OPEN |
| ARCH-013 | PostgreSQL/Redis/Artifact production persistence | Blueprint §24 | adapters/migrations | integration tests | server deployment | 系统信息 | fallback文件非正式架构 | OPEN |

## 3. Requirement / Code / Design intelligence

| ID | Capability | Required outputs | Sufficiency loop | Reality requirement | Product | Current state |
|---|---|---|---|---|---|---|
| REQ-AN-001 | Requirement analysis | BR/SR/TR/rules/states/roles/data/risks/VP/unknowns | analyze->evaluate->gap->delta | real design document/SST | 需求管理 | OPEN |
| REQ-AN-002 | Requirement sufficiency evaluator | coverage + critical unknown | independent evaluator | real incomplete->repair cycle | 需求详情/任务 | OPEN |
| CODE-AN-001 | Git snapshot/diff authority | changed files/lines/snapshot | freshness gate | bank repo | 代码分析 | CI_VERIFIED |
| CODE-AN-002 | CodeGraph structural analysis | context/callers/callees/dependency/impact | add queries when gaps | bank real CodeGraph | 代码分析 | TOOL_REALITY_VERIFIED |
| CODE-AN-003 | Semantic code analysis | change meaning/API/service/DB/state/risk/test impact | semantic evaluate->requery | bank DSH worker | 代码分析 | IMPLEMENTED_PARTIAL |
| CODE-AN-004 | Code sufficiency evaluator | unknown/risk/evidence/test-impact completeness | iterative | real multi-round analysis | 代码分析 | OPEN |
| DESIGN-001 | Risk/TestIntent/VerificationPoint model | risk->intent->VP | coverage driven | real requirement/code input | 测试用例 | OPEN |
| DESIGN-002 | Test case designer | cases/oracles/layer/scope | design->evaluate->delta | real SST | 测试用例 | OPEN |
| DESIGN-003 | Design sufficiency evaluator | requirement/risk/VP/code/state/auth/data/E2E coverage | mandatory loop | real gap->delta cycle | 用例/任务 | OPEN |
| SPEC-001 | ExecutableSpec | preconditions/data/steps/expected/oracle/evidence/cleanup | validation/repair | real generated scripts | 用例详情 | OPEN |
| ORACLE-001 | Oracle governance | source/version/assertion/evidence | independent change review | real product fail vs oracle error | 用例/缺陷 | OPEN |

## 4. Tool capabilities (dependency only)

| ID | Tool capability | Reality gate | Current state | Must NOT imply |
|---|---|---|---|---|
| TOOL-001 | Maven/JUnit | real bank Maven + fresh JUnit evidence | BANK_REALITY_VERIFIED | L1 sufficient |
| TOOL-002 | CodeGraph | real structural graph queries | BANK_REALITY_VERIFIED | code analysis sufficient |
| TOOL-003 | pytest | real target project execution | PENDING | L1/L2 sufficient |
| TOOL-004 | JaCoCo | agent/report/XML real collection | OPEN | changed coverage sufficient |
| TOOL-005 | coverage.py | real Python coverage | OPEN | L1 sufficient |
| TOOL-006 | mutation/PIT | real mutation run | OPEN | overall sufficiency |
| TOOL-007 | Browser/Playwright | real Chromium/actions/network | PENDING | L4 sufficient |
| TOOL-008 | 4A | fresh login/re-auth | PENDING | L3/L4/L5 sufficient |
| TOOL-009 | DB adapters | real query/write/readback | PENDING | L2 sufficient |
| TOOL-010 | CAT/log | real authenticated log evidence | PENDING | product failure proven alone |
| TOOL-011 | k6/perf runner | real workload | PENDING | L6 sufficient without NFR |
| TOOL-012 | security scanner | real approved scan | PENDING | L7 sufficient |
| TOOL-013 | AnyDoc | real doc parsing | inherited/prove migration | requirement analysis sufficient |

## 5. L1 autonomous loop

| ID | L1 capability | Acceptance proof | Product projection | Current state |
|---|---|---|---|---|
| L1-001 | L1 case selection/design from risks | trace Risk/VP->Case | 用例详情 | OPEN |
| L1-002 | JUnit/TestNG/pytest script generation | compilable executable spec fidelity | 用例脚本/版本 | OPEN |
| L1-003 | Script validation | compile/syntax/assertion/no forbidden skip | 用例执行准备 | OPEN |
| L1-004 | Real execution | Attempt + JUnit/pytest Actual | 用例Attempt | TOOL substrate verified only |
| L1-005 | JaCoCo/coverage collection | fresh coverage artifact | Coverage view | OPEN |
| L1-006 | Changed method/line/branch mapper | Git+CodeGraph+coverage correlation | Coverage detail | OPEN |
| L1-007 | Requirement/risk/VP coverage evaluator | coverage matrix | Coverage summary | OPEN |
| L1-008 | Assertion strength evaluator | explicit oracle + mutation where configured | 用例/报告 | OPEN |
| L1-009 | Failure classifier | PRODUCT/SCRIPT/... | Attempt failure details | OPEN |
| L1-010 | RCA router | correct owner/evidence | Gap/缺陷 | OPEN |
| L1-011 | Coverage Gap generator | durable Gap | 任务-Gap | OPEN |
| L1-012 | Delta Test Design | only missing coverage repaired | AI闭环 | OPEN |
| L1-013 | Delta Script Generation | spec-aligned scripts | 用例版本 | OPEN |
| L1-014 | Targeted re-execution | new Attempt, old history preserved | Attempt history | OPEN |
| L1-015 | Coverage recalculation | old/new comparison | Coverage history | OPEN |
| L1-016 | Convergence controller | loop until sufficient/hold | AI闭环 | OPEN |
| L1-017 | L1 sufficiency evaluator | critical coverage/gaps policy | 任务/报告 | OPEN |
| L1-018 | L1 bank mission proof | real changed code causing at least one gap/repair cycle | full trace | OPEN |

## 6. L2-L7 professional layer closure

| ID | Layer | Dedicated requirements | Reality proof | Current state |
|---|---|---|---|---|
| L2-001 | L2 Component/Repository/DB | ORM/CRUD/constraint/transaction/rollback/idempotency/readback | real bank DB | OPEN |
| L2-002 | L2 sufficiency | DB behavior + risk/data/state coverage | gap->repair cycle | OPEN |
| L3-001 | L3 API/service | verified route/auth/request/response/schema/business assertions/backend readback | real API | OPEN |
| L3-002 | L3 sufficiency | affected API/risk/negative/boundary/permission coverage | gap->repair cycle | OPEN |
| L4-001 | L4 Browser/UI | real steps/DOM/network/screenshot/trace/fresh auth | real cfg-admin | OPEN |
| L4-002 | L4 sufficiency | journey/state/permission/assertion coverage | zero-step regression + gap cycle | OPEN |
| L5-001 | L5 Business E2E | single coherent journey/correlation/cross-app/final state | real business flow | OPEN |
| L5-002 | L5 sufficiency | required journey 100% or explicit defect/hold | real end-to-end | OPEN |
| L6-001 | L6 Performance | workload/TPS/P95/P99/error/resource | real environment | OPEN |
| L6-002 | L6 NFR semantics | PASS/FAIL only with authoritative threshold; else BASELINE_ONLY | real baseline/NFR | OPEN |
| L7-001 | L7 Security/Authz | authz matrix/negative/privilege/input/audit/scanner where available | real approved tests | OPEN |
| L7-002 | L7 sufficiency | threat/role/critical finding gate | real security scope | OPEN |

## 7. Runtime prerequisites and shared execution services

| ID | Capability | Closure criteria | Current state |
|---|---|---|---|
| AUTH-001 | Fresh 4A auth | foura_auth/runtime skill, expiry/re-auth, no history cookie | OPEN |
| AUTH-002 | Human Lease for unavoidable challenge | explicit pause/ownership/evidence/resume | OPEN |
| ROUTE-001 | Observe-first route discovery | Browser network/OpenAPI/code/runtime, no guessing | OPEN |
| ROUTE-002 | Route knowledge freshness | version/source/confidence/last_verified/stale | OPEN |
| DATA-001 | Data discover/build/select | usable asset found/created | OPEN |
| DATA-002 | Data validate/lease/prepare | precondition verified before execution | OPEN |
| DATA-003 | Data readback/release/cleanup/reuse | lifecycle evidence | OPEN |
| ENV-001 | Environment truth | capability/env real probes | PARTIAL |
| LOG-001 | CAT/log evidence adapter | login/query/correlation/artifact | OPEN |

## 8. Failure/defect closure

| ID | Capability | Closure criteria | Current state |
|---|---|---|---|
| FAIL-001 | Canonical failure ownership | PRODUCT/SCRIPT/SPEC/ORACLE/DATA/AUTH/ROUTE/ENV/DEPENDENCY/FLAKY/TOOL/MODEL/SESSION/UNKNOWN | OPEN |
| FAIL-002 | No blind retry | retry requires class/policy | OPEN |
| DEFECT-001 | Product defect candidate | Expected/Actual/Assertion/Evidence/RCA | OPEN |
| DEFECT-002 | Fix/regression linkage | fix snapshot -> regression Attempt | OPEN |
| DEFECT-003 | Product failure does not mark testing execution failed | mission/release semantics separated | OPEN |

## 9. Knowledge / Skill / Behavior graph

| ID | Capability | Closure criteria | Current state |
|---|---|---|---|
| KNOW-001 | Knowledge lifecycle | candidate->verified->stable->stale/version | OPEN |
| KNOW-002 | Task-scoped resolver | no full-context dump | OPEN |
| KNOW-003 | Session-loss reuse | new DSH session retrieves same verified knowledge | OPEN |
| SKILL-001 | Center Skill Registry | version/provides/requires/platform/evidence/tests | OPEN |
| SKILL-002 | Skill reality qualification | presence != capability | OPEN |
| SBG-001 | System Behavior Graph | page/action->API->auth->service->code->DB/state | OPEN |

## 10. Product surface closure

| ID | Surface | Mandatory truth | Current state |
|---|---|---|---|
| UI-001 | 投产管理 | batch/scope/test status from domain | OPEN |
| UI-002 | 版本管理 | requirement/SST/TestRun/sufficiency | OPEN |
| UI-003 | 需求管理 | BR/SR/TR/code/cases/execution/defect/knowledge | OPEN |
| UI-004 | 代码分析 | snapshots/changes/call graph/risks/test impact/evidence/sufficiency history | OPEN |
| UI-005 | 业务流程 | human steps/API/data/auth/state/evidence/replay | OPEN |
| UI-006 | 测试接口 | observed route/auth/sample/freshness/evidence | OPEN |
| UI-007 | 测试用例 | Risk/VP/precondition/data/steps/Expected/Oracle/Attempts/Evidence | OPEN |
| UI-008 | 测试任务 | Mission Graph/Attempt/Gap/route-back/invalidation/convergence | OPEN |
| UI-009 | 测试报告 | tested/not-tested/coverage/gaps/defects/evidence/release | OPEN |
| UI-010 | 缺陷管理 | Expected/Actual/Evidence/RCA/fix/regression | OPEN |
| UI-011 | 知识库 | runtime knowledge lifecycle/provenance/freshness | OPEN |
| UI-012 | 执行节点 | node/capability reality/skills/tasks/package | PARTIAL |
| UI-013 | 系统信息 | env/DB/accounts/resources/skills/diagnostics | OPEN |
| UI-014 | Projection consistency | UI status cannot infer own PASS | OPEN |

## 11. Deployment / package closure

| ID | Capability | Acceptance | Current state |
|---|---|---|---|
| DEP-001 | Separate Center package | clean deploy/start/check | OPEN |
| DEP-002 | Complete Node package | Center-downloadable, RC7 offline tools | PARTIAL |
| DEP-003 | Windows Git Bash | clean reality smoke | PARTIAL_REALITY |
| DEP-004 | Xinchuang Linux bash | clean reality smoke | OPEN |
| DEP-005 | x86_64/aarch64 variants | capability-qualified | OPEN |
| DEP-006 | No public internet runtime install | offline/internal-only manifest | OPEN |
| DEP-007 | Persistent Node state outside package | upgrade keeps identity/queue | IMPLEMENTED_DIRECTION |
| DEP-008 | Restart recovery | Center/Node/DSH restart | OPEN |
| DEP-009 | Upgrade/rollback | state/assets preserved | OPEN |
| DEP-010 | Complete-package-only handoff | ZIP/hash/manifest/integrity | CI_VERIFIED_PARTIAL |

## 12. RC7 canonical gap closure mapping

| RC7 gap | Required RC8 rows |
|---|---|
| CG-TIME-VOCAB | ARCH-003 + Event schema |
| CG-TRUTH-CHAIN | ARCH-003 + UI-014 |
| CG-EVIDENCE-REF | ARCH-004 |
| CG-PROVENANCE-OWNER | ARCH-002/005 + worker provenance |
| CG-EXEC-KERNEL | Tool adapters + L1-L7 reality |
| CG-CODEGRAPH | CODE-AN-001..004 |
| CG-DESIGN-GATE | DESIGN-001..003 |
| CG-DATA-LIFECYCLE | DATA-001..003 + ARCH-006 |
| CG-ENV-TRUTH | ENV-001 + tool qualification |
| CG-COVERAGE | L1-005..017 + layer-specific coverage |
| CG-DEFECT | DEFECT-001..003 |
| CG-WAIVER-HUMAN | AUTH-002 + governed mission waiver |
| CG-COMPLETION-RELEASE | ARCH-010 + Mission/Release state |
| GAP-ADD-03/06/10 | OPEN_INPUT until authoritative final wording imported |

## 13. Closure audit

Before changing any row to CLOSED, record:
- exact commit SHA
- code paths
- automated test paths
- CI run
- target-bank reality evidence/artifact IDs
- product page/API/projection
- RC7 regression scenario(s)
- current source/config snapshot
- reviewer/decision record where human gate applies

No row may be deleted because implementation is inconvenient.