# RC8 Product Projection Map

Status: FROZEN-CANDIDATE
Purpose: ensure every user-facing page is a projection of durable domain/runtime truth, not disconnected CRUD or front-end inferred status.

## 1. Product rules

- Chinese-first, Apple-inspired, restrained, clear, spacious.
- No dashboard-first UX, no giant decorative cards, no large colored navigation.
- Left navigation + right list/detail content.
- Lists locate; details explain.
- Complex detail uses large page/modal (~90% viewport), tabs, evidence drilldown.
- Product state comes from Center projections, never local front-end heuristics.
- User must understand runtime truth without reading DSH logs.

## 2. Shared projection model

Required projections:
- ProductionProjection
- VersionProjection
- RequirementProjection
- RequirementAnalysisProjection
- CodeAnalysisProjection
- BusinessFlowProjection
- RouteApiProjection
- TestCaseProjection
- TestRunProjection
- StageProjection
- LayerProjection
- AttemptProjection
- CoverageProjection
- GapProjection
- DefectProjection
- EvidenceProjection
- KnowledgeProjection
- NodeProjection
- CapabilityProjection
- SystemDiagnosticProjection
- ReportProjection
- ReleaseProjection

Projection source must be durable domain + R1/runtime facts. Projection rebuild/replay must be deterministic where applicable.

## 3. Status policy

Front-end is forbidden from calculating complex PASS from raw counts.

Forbidden example:
`failed == 0 -> PASS`.

UI receives explicit scoped states:
- TOOL capability state
- STAGE execution/sufficiency state
- LAYER execution/sufficiency state
- MISSION TEST_SUFFICIENT
- RELEASE decision

UI displays scope labels to avoid green-state contamination.

## 4. 投产管理

### List
- 投产日期/批次
- 需求数
- 系统/版本
- 应用/SST
- TestRun状态
- 测试充分度
- Release decision

### Detail tabs
1. 需求范围
2. 系统版本
3. 测试任务
4. 测试进度/充分度
5. 缺陷
6. 残余Gap/风险

### Source
ProductionBatch + RequirementDeliveryScope + TestRun/Report/Release projections.

## 5. 版本管理

### List
- 系统
- 版本号/名称
- 投产批次
- 需求/SST数
- 最近测试
- Mission sufficiency
- Release

### Detail
- 投产关联
- 需求/SST
- CodeAnalysis snapshots
- TestRuns
- Layer sufficiency
- defects/gaps

### Rule
版本绿色不能仅由 case pass rate 推断。

## 6. 需求管理

### List
- 需求编号/名称
- 最近投产
- 涉及系统/应用
- SST数
- 分析状态
- 测试充分度
- 最近执行

### Detail tabs
1. 基本信息
2. 投产实现范围
3. 需求分析
4. 代码分析
5. 风险/验证点
6. 测试设计/用例
7. 执行记录
8. 缺陷
9. 知识

### 需求分析 tab
BR / SR / TR tabs + business rules + state/permission/data + unknowns + analysis attempts + sufficiency.

### Source
Requirement/DeliveryScope + analysis/domain projections.

## 7. 代码分析

### List
- 投产/版本/需求/SST/应用
- snapshot
- 分析轮次
- sufficiency
- critical unknown
- 最近分析时间

### Detail tabs
1. 变更摘要
2. 文件/类/方法
3. 调用链/依赖
4. API/服务/DB/配置影响
5. 业务状态影响
6. 风险
7. L1-L7测试影响
8. UNKNOWN/追加查询
9. Evidence
10. 历史版本/轮次

### Required fields
- Git base/head/working-tree snapshot
- graph_digest
- semantic analysis version
- evidence refs
- evaluator result

### Rule
One LLM paragraph is never the entire code analysis UI.

## 8. 业务流程

### List
- 流程名称
- 应用
- 起始页面
- 需求/SST
- 步骤数/API数
- 最近验证
- freshness/status

### Detail
Readable vertical business timeline first.
Each step shows:
- business operation
- page/action
- API request/response ref
- variable/data binding
- auth dependency
- state dependency
- Expected/Assertion
- Evidence

Secondary relation graph displays Page -> API -> Service -> Code -> DB/State where verified.

## 9. 测试接口

### List
- 应用/页面
- 方法/Route
- auth requirement
- source
- confidence
- last_verified_at
- freshness

### Detail
- route versions
- request/response samples
- auth
- producer/source (Browser/OpenAPI/Code/Runtime/Manual)
- evidence
- associated business flows
- associated code/DB where known

### Rule
Stale route is visibly STALE; UI must not present it as current verified route.

## 10. 测试用例

### List
- Case ID
- 投产/版本/需求/SST
- L1-L7
- 标题
- Risk/VerificationPoint
- scope type
- latest Attempt result
- sufficiency contribution

### Detail tabs
1. 基本信息
2. 关联风险/验证点
3. 前置条件
4. 测试数据
5. 执行步骤/Expected/Oracle
6. ExecutableSpec/脚本版本
7. Attempt历史
8. Evidence
9. Coverage contribution

### Attempt detail
Per step:
- action/input
- Expected
- Actual
- Assertion
- result
- Evidence
- failure classification

Old FAIL/BLOCKED remains visible after later PASS.

## 11. 测试任务

This is the primary operating surface.

### List
- 任务编号
- 投产/版本/范围
- 节点/执行人
- 开始时间
- 当前阶段
- applicable L1-L7
- executed cases
- open gaps
- defects
- mission sufficiency
- release

### Detail tabs
1. 概要
2. 测试范围
3. AI闭环
4. 分析与设计
5. 用例执行
6. Coverage
7. Gap
8. 缺陷
9. Evidence
10. 运行/恢复历史

### AI闭环 view
Must show:
- Mission Graph
- Stage/Attempt timeline
- evaluator decisions
- gaps
- route-back arrows
- delta design/repair
- invalidation
- targeted re-run
- convergence

Final 完成 badge alone is insufficient.

### Coverage view
Multi-dimensional:
- requirement/risk/VP
- changed method/line/branch
- API/flow/state/permission/data/E2E
- oracle/mutation
- L6/L7 dimensions where applicable

## 12. 测试报告

### First section answers
- 本次为什么测
- 测了什么范围
- 哪些Requirement/Risk/VP验证了
- 哪些未验证以及原因
- changed-code coverage
- applicable L1-L7 sufficiency
- defects found
- unresolved gaps/residual risk
- why TEST_SUFFICIENT yes/no
- Release recommendation

### Detail
Every executed case -> Attempts -> Actual/Assertion/Evidence.

Report snapshot is versioned. Upstream invalidation marks old report OUTDATED; history remains.

## 13. 缺陷管理

### List
- 缺陷号
- 投产/版本/需求/SST
- source case/attempt
- severity
- state
- first/last observed
- regression state

### Detail
- business context
- Expected
- Actual
- assertion
- evidence
- logs/network/DB/screenshot
- failure classification
- RCA
- CodeGraph/code impact
- fix snapshot
- regression attempts

### Rule
Product defect remains a successful testing finding even when Release=HOLD.

## 14. 知识库

Categories:
- 业务流程
- 接口/路由
- 认证
- 页面
- 数据库
- 测试数据
- 业务规则
- 代码
- 失败模式
- 环境
- 历史缺陷

### List/detail fields
- scope
- source
- provenance/evidence
- confidence
- version
- last_verified_at
- status candidate/verified/stable/stale
- consumers/reuse history

### Rule
Model output cannot silently overwrite trusted knowledge.

## 15. 执行节点

### List
- 节点名称/ID
- operator
- status
- OS/arch
- current task
- heartbeat
- package version
- capability summary

### Detail tabs
1. 基本信息
2. 能力
3. 技能
4. 当前任务
5. 历史任务
6. 资源租约
7. 运行记录
8. 包/升级

### Capability table
Show separately:
- discovery/install state
- qualification state
- latest real verification time
- evidence
- degradation/unavailable reason

Presence != VERIFIED.

## 16. 系统信息

Tabs:
1. 测试环境
2. 数据库
3. 测试帐号
4. 应用配置
5. 测试资源
6. 技能管理
7. 系统诊断
8. Package/版本

Diagnostics:
- Center
- PostgreSQL
- Redis
- Artifact storage
- Node communication
- capability checks
- queue/backlog
- projection lag

## 17. Cross-navigation / global traceability

Recognizable entities are navigable:
Production -> Requirement/Scope -> Requirement Analysis -> Code Analysis -> Risk/VP -> Case -> TestRun -> Attempt -> Flow/API -> Gap/Defect -> Knowledge -> Evidence.

No page should be an isolated CRUD island.

## 18. Evidence viewer

Shared component supports:
- text/log
- JSON
- JUnit/coverage XML summary + raw download
- screenshot
- HAR/request-response
- SQL result
- CodeGraph graph evidence
- generated script
- trace/video metadata

Shows provenance/hash/producer/snapshot/associated assertion.

## 19. Invalidation/history UX

When upstream data changes:
- old result remains historical
- clearly label STALE/INVALIDATED/SUPERSEDED
- show why invalidated and new version/attempt
- no silent overwrite from green to green

## 20. Product acceptance

A page fails acceptance when:
- status is inferred client-side from raw counts
- user must read DSH logs to understand runtime truth
- Attempt history is overwritten
- Expected/Actual/Assertion/Evidence cannot be traced
- Gap route-back/convergence is invisible
- stale knowledge/result looks current
- product text mixes unnecessary Chinese/English
- page devolves into dashboard/card noise instead of readable work surface

## 21. First vertical slice product requirement

The first L1 autonomous slice is not complete until UI can show:
- requirement/code risk
- generated case/spec/script
- Attempt 1
- JaCoCo changed-code coverage
- uncovered branch Gap
- route-back to Test Design
- delta case/script
- Attempt 2
- coverage improvement
- L1 sufficiency decision
- mission decision
- all supporting evidence.