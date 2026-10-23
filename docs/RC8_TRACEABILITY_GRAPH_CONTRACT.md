# RC8 需求—页面—接口—代码—数据库追溯关系合同

## 1. 目标

RC8 将以下关系建设为正式一等业务能力，而不是一次性分析报告：

```text
需求 -> 业务能力 -> 页面 -> 页面操作 -> 接口 -> Controller -> Service -> Repository/Mapper -> SQL -> 数据库表 -> 测试用例 -> 执行证据
```

统一产物名称：`TraceabilityGraph`（测试影响与追溯关系图）。

必须同时支持：

- 正向：需求 -> 页面 -> 接口 -> 代码 -> 数据库表 -> 测试用例
- 反向：代码/表/API 变更 -> 页面 -> 需求 -> 测试用例 -> 回归范围
- 跨测试轮次：CodeSourceSnapshot N -> N+1 差异 -> 选择性失效 -> 增量回归

模型输出只能形成候选关系，不得直接成为运行时真相或 PASS 依据。

---

## 2. 事实与证据规则

### 2.1 关系来源

| 关系 | 首选证据 |
|---|---|
| 需求 -> 业务能力/候选页面 | 需求文档、需求分析产物 |
| 页面 -> 页面操作 -> API | 受控浏览器真实 Network Capture |
| API -> Controller | Spring/网关/路由真实映射 |
| Controller -> Service -> Repository/Mapper | CodeGraph/AST/真实代码 |
| Repository/Mapper -> SQL | MyBatis/JPA/JDBC/SQL 解析 |
| SQL -> Table | 真实 SQL/ORM 映射 |
| TraceNode/TraceEdge -> TestCase | 测试设计正式覆盖映射 |
| TestCase -> Runtime Evidence | 真实执行 Attempt/Evidence |

### 2.2 禁止事项

- 禁止模型猜接口地址后把关系标记为已确认。
- 禁止仅凭类名猜数据库表。
- 禁止 CodeGraph 不可用时由模型补调用链并判定 CODE_ANALYSIS 通过。
- 禁止浏览器未真实执行时将 Page -> API 标记为运行时已验证。
- 禁止关系没有 Evidence 仍进入已验证状态。

---

## 3. 核心领域对象

### 3.1 TraceabilityGraph

一个 TraceabilityGraph 必须绑定：

```text
ProductionBatch
TestRound
ScopeRevision
CodeSourceSnapshot
```

一个 TestRound 的关系分析必须使用冻结的 ScopeRevision 和 CodeSourceSnapshot。

### 3.2 TraceNode

```text
TraceNode
- node_id
- graph_id
- node_type
- business_key
- display_name
- scope_revision_id
- code_source_snapshot_id (nullable for pure requirement nodes)
- attributes
- created_at
```

`node_type` 至少支持：

```text
REQUIREMENT
BUSINESS_CAPABILITY
PAGE
PAGE_ACTION
API
CONTROLLER
METHOD
SERVICE
REPOSITORY
MAPPER
SQL
DATABASE
TABLE
TEST_CASE
```

### 3.3 TraceEdge

```text
TraceEdge
- edge_id
- graph_id
- from_node_id
- to_node_id
- relation_type
- verification_state
- confidence
- evidence_count
- created_at
- invalidated_at
```

`relation_type` 至少支持：

```text
REQUIREMENT_AFFECTS
CAPABILITY_PRESENTED_ON
PAGE_HAS_ACTION
PAGE_CALLS_API
API_IMPLEMENTED_BY
CALLS
EXECUTES_SQL
READS_TABLE
WRITES_TABLE
TEST_COVERS
TEST_VERIFIES
```

### 3.4 VerificationState

```text
CANDIDATE
STATIC_VERIFIED
RUNTIME_VERIFIED
MULTI_SOURCE_VERIFIED
CONFLICTED
INVALIDATED
```

只有确定性验证器可把 CANDIDATE 升级为 STATIC_VERIFIED / RUNTIME_VERIFIED / MULTI_SOURCE_VERIFIED。

### 3.5 TraceEvidence

```text
TraceEvidence
- evidence_id
- graph_id
- edge_id
- evidence_type
- source
- artifact_id
- test_run_id
- stage_id
- work_item_id
- attempt_id
- code_source_snapshot_id
- captured_at
- integrity_hash
```

`evidence_type` 至少支持：

```text
REQUIREMENT_DOCUMENT
BROWSER_NETWORK
PAGE_RUNTIME
SPRING_MAPPING
CODEGRAPH
SOURCE_CODE
MYBATIS_MAPPING
SQL
DATABASE_METADATA
APPLICATION_LOG
STARLINK
TEST_EXECUTION
```

---

## 4. MissionGraph 集成合同

不新建第二套生命周期，继续使用现有阶段：

```text
SCOPE_INTAKE
REQUIREMENT_ANALYSIS
REQUIREMENT_SUFFICIENCY
CODE_ANALYSIS
CODE_SUFFICIENCY
RISK_TEST_MODEL
TEST_DESIGN
DESIGN_SUFFICIENCY
EXECUTABLE_SPEC
PRECONDITION_DATA_PREP
APPLICABLE_LAYER_EXECUTION
FAILURE_COVERAGE_EVALUATION
MISSION_SUFFICIENCY
REPORT_RELEASE
```

职责：

- REQUIREMENT_ANALYSIS：建立 REQUIREMENT / BUSINESS_CAPABILITY / 候选 PAGE 节点。
- CODE_ANALYSIS：基于冻结 CodeSourceSnapshot 建立 API / CODE / SQL / TABLE 节点与 Edge。
- Browser Worker：通过 fresh 4A 登录和真实 Network 建立 PAGE -> PAGE_ACTION -> API 运行关系。
- CODE_SUFFICIENCY：确定性检查关键关系和 Evidence 是否充分。
- RISK_TEST_MODEL：消费 TraceabilityGraph 做风险建模。
- TEST_DESIGN：将 TestCase 映射到 TraceNode/TraceEdge。
- APPLICABLE_LAYER_EXECUTION：真实执行后补充运行时 Evidence。
- MISSION_SUFFICIENCY：检查关键风险、关键关系及执行证据是否达到测试充分度。

CODE_ANALYSIS 无真实 CodeGraph Evidence 时必须 BLOCKED/FAILED/GAP，不得 PASS。

---

## 5. 查询合同

### 5.1 查询维度

必须支持按以下任一入口查询完整关系：

- ProductionBatch
- TestRound
- Requirement
- SST
- System / SystemVersion / Application
- Page
- API
- Java Class / Method
- Repository / Mapper
- Database / Table
- TestCase
- CodeSourceSnapshot

### 5.2 业务查询接口

接口命名必须沿用 RC8 现有 API 风格，以下是能力合同而非强制 URL 命名：

```text
queryGraph(testRoundId, scopeRevisionId)
queryRequirementImpact(requirementId, testRoundId)
queryPageImpact(pageKey, testRoundId)
queryApiImpact(apiKey, testRoundId)
queryCodeImpact(symbol, codeSourceSnapshotId)
queryTableImpact(database, table, testRoundId)
queryTestCoverage(testCaseId, testRoundId)
queryEvidence(edgeId)
queryUnverifiedRelations(testRoundId)
queryTraceGaps(testRoundId)
compareGraphImpact(baseSnapshotId, targetSnapshotId)
```

每个查询结果必须返回：

```text
nodes
edges
verification_state
evidence_summary
gaps
source_snapshot
scope_revision
```

### 5.3 典型查询

#### 从需求查

```text
STBB19-320
 -> 额度调整页面
 -> 点击提交
 -> POST /credit/limit/adjust
 -> LimitAdjustController.submit
 -> LimitAdjustService.adjust
 -> CreditLimitMapper.update
 -> credit_limit
 -> credit_limit_change_log
 -> TC-xxx
```

#### 从表反查

```text
credit_limit
 -> CreditLimitMapper
 -> Service
 -> API
 -> Page
 -> Requirement
 -> TestCase
```

#### 从代码变更查增量回归

```text
Changed Method
 -> impacted API
 -> impacted Page
 -> impacted Requirement
 -> impacted TestCase
 -> next TestRound targeted regression
```

---

## 6. 页面展示合同

### 6.1 菜单

RC8 左侧业务菜单新增：`影响关系`。

保持中文优先、苹果式克制设计，不使用 Dashboard、大卡片或暴露 Agent/Stage/WorkItem/L1-L7 内部调度信息。

### 6.2 页面顶部筛选

```text
投产日期
测试轮次
需求/SST
系统
应用
代码快照
关系状态
```

默认进入页面时继承当前业务上下文，不要求用户重复录入。

### 6.3 主视图：链路视图

默认展示业务可理解的主链：

```text
需求 -> 页面 -> 接口 -> 代码 -> 数据库表 -> 测试用例
```

节点按类型分列，不做无限展开的大型自由图谱。

用户点击一个节点后，只展开其直接上下游，避免关系多时不可读。

### 6.4 右侧详情

点击任意节点或关系，右侧详情展示：

```text
名称
类型
当前验证状态
所在测试轮次
ScopeRevision
CodeSourceSnapshot
直接上游
直接下游
关联测试用例
Evidence 数量
Gap 数量
```

点击一条关系时额外展示：

```text
关系类型
来源
验证状态
证据来源
首次发现时间
最近验证时间
是否因新快照失效
```

### 6.5 Evidence 抽屉

点击“查看证据”后展示真实证据，不显示模型解释替代证据。

例如 PAGE_CALLS_API：

```text
页面 URL
页面操作
请求方法
真实请求路径
请求/响应摘要
捕获时间
Browser Attempt
Artifact
```

例如 CALLS / API_IMPLEMENTED_BY：

```text
CodeSourceSnapshot
Commit SHA
源码文件
类/方法
CodeGraph Query
CodeGraph Result
Artifact
```

例如 WRITES_TABLE：

```text
Mapper/Repository
SQL
数据库
表名
源码位置
CodeSourceSnapshot
Artifact
```

### 6.6 三种展示模式

同一批数据提供三种视图，默认第一种：

1. **链路视图**：需求 -> 页面 -> 接口 -> 代码 -> 表 -> 测试用例，业务用户默认使用。
2. **列表视图**：按关系逐行显示，适合筛选、导出、核查 Evidence。
3. **变更影响视图**：比较两个 CodeSourceSnapshot，只显示新增/变化/失效关系及受影响 TestCase，用于下一轮测试。

不把自由拖拽的复杂图数据库 UI 作为默认产品体验。

---

## 7. 用户操作合同

业务用户只需要：

```text
选择投产批次
 -> 选择需求/SST
 -> 开始测试轮次
 -> 查看需求分析
 -> 查看影响关系
 -> 必要时处理业务 Gap
 -> 查看测试设计
 -> 执行测试
 -> 查看报告
```

系统自动完成：

```text
冻结 ScopeRevision / CodeSourceSnapshot
需求分析
页面候选发现
fresh 4A 登录
Browser Network 捕获
API 真实识别
CodeGraph 查询
代码调用链解析
SQL / Table 解析
关系合并
Evidence 绑定
充分度检查
测试覆盖映射
跨轮次影响差异
增量回归范围计算
```

用户不得被要求维护 Controller、Service、Mapper 路径，也不得手工输入 WorkItem ID。

---

## 8. 持久化与运行时真相

PostgreSQL 持久化：

```text
TraceabilityGraph
TraceNode
TraceEdge
TraceEvidence
TraceGap
GraphSnapshot
```

Redis 仅用于 lease / claim / temporary coordination，不作为关系事实源。

R1 Event Stream 必须记录：

```text
TRACE_GRAPH_CREATED
TRACE_NODE_DISCOVERED
TRACE_EDGE_CANDIDATE_CREATED
TRACE_EVIDENCE_ATTACHED
TRACE_EDGE_VERIFIED
TRACE_EDGE_CONFLICTED
TRACE_GAP_OPENED
TRACE_GAP_RESOLVED
TRACE_EDGE_INVALIDATED
TRACE_GRAPH_SNAPSHOTTED
```

R1 Event Stream 继续作为 Runtime Truth。

---

## 9. 失效与跨轮次合同

以下变化必须触发选择性失效，而不是整体删除关系图：

```text
RequirementRevision
ScopeRevision
CodeSourceSnapshot
API Mapping
页面版本
SQL
```

下一轮 TestRound 创建新 CodeSourceSnapshot 后：

```text
Snapshot N -> Snapshot N+1
 -> ChangeSet
 -> affected TraceNode/TraceEdge
 -> invalidate impacted relations
 -> re-run required analysis
 -> calculate impacted TestCases
 -> targeted regression
```

`TEST_ROUND != PRODUCTION_BATCH != REQUIREMENT_ITERATION`，测试轮次增加不得新建 ProductionBatch。

---

## 10. CODE_SUFFICIENCY Gate

CODE_ANALYSIS 完成不等于 CODE_SUFFICIENCY 通过。

至少检查：

- 变更文件是否全部分析；
- 关键变更方法是否进入关系图；
- 相关 API 是否识别或有明确无 API 证据；
- 关键上下游调用链是否有 CodeGraph Evidence；
- 跨服务影响是否分析；
- DB/SQL/Table 是否分析；
- 未知影响是否为 0 或形成 Gap；
- 关键 Edge 是否存在 Evidence；
- Scope 是否隔离；
- CodeSourceSnapshot 是否一致。

不足时：

```text
INSUFFICIENT -> Gap -> 新 Attempt -> 增量 Evidence -> 重新评估
```

禁止覆盖旧 Attempt。

---

## 11. 测试设计与覆盖合同

测试设计必须消费 TraceabilityGraph，不得只基于需求文本生成案例。

每个 TestCase 至少可声明覆盖：

```text
Requirement
Page / PageAction
API
关键 Code Path
Database/Table
Risk
```

系统据此计算：

```text
Requirement Coverage
Page Coverage
API Coverage
Code Impact Coverage
Table Coverage
Risk Coverage
Runtime Evidence Coverage
```

测试充分度不得只以 Case 数量衡量。

---

## 12. 验收等级

必须分别声明：

```text
CODE_EXISTS
UNIT_VERIFIED
CI_VERIFIED
CLOUD_REALITY_CI_VERIFIED
BANK_REALITY_VERIFIED
TEST_SUFFICIENT
RELEASE_READY
```

页面完成、数据库表完成、接口可返回都不等于 BANK_REALITY_VERIFIED。

最小银行真实验收链必须包含：

```text
真实 Requirement
 -> 真实 Page
 -> 真实 Browser Network API
 -> 真实 Controller/Service/Mapper
 -> 真实 SQL/Table
 -> 真实 TestCase
```

关键 Edge 均可打开 Evidence，并可从任一关键节点进行反向追溯。

无真实 Evidence 时，Release 必须保持 HOLD。
