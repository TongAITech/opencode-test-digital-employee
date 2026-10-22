# RC8 TestRound 自主任务拆分与 Mission Bootstrap 契约

状态：**FROZEN FOR RC8 CONSTRUCTION**

本文补充 `docs/rc8-production-date-test-round-model.md`，定义用户点击“开始本轮自主测试”之后，Center 必须如何把一个 TestRound 自动组织为可执行任务。该契约的目标是让用户提交业务测试目标，而不是手工选择 Agent、L1-L7 或下一步动作。

## 1. 用户入口

用户只负责：

1. 选择投产日期；
2. 确认本次投产需求；
3. 确认每个 RequirementDelivery 的 System / SystemVersion / Application / SST Scope；
4. 新建测试轮次；
5. 点击“开始本轮自主测试”。

用户不输入 `test_round_id`、`test_run_id`、Stage、Worker、Agent 名称，也不手工选择 L1-L7。

## 2. 启动后的正式结构

```text
ProductionBatch
  -> TestRound
     -> TestRun
        -> Scope A pipeline
        -> Scope B pipeline
        -> ...
        -> Mission Sufficiency
        -> Report / Release Decision
```

每个 RequirementDeliveryScope 独立生成一条初始 Stage 链：

```text
SCOPE_INTAKE
  -> REQUIREMENT_ANALYSIS
  -> REQUIREMENT_SUFFICIENCY
  -> CODE_ANALYSIS
  -> CODE_SUFFICIENCY
  -> RISK_TEST_MODEL
  -> TEST_DESIGN
  -> DESIGN_SUFFICIENCY
  -> EXECUTABLE_SPEC
  -> PRECONDITION_DATA_PREP
  -> APPLICABLE_LAYER_EXECUTION
  -> FAILURE_COVERAGE_EVALUATION
```

多个 Scope 的 `FAILURE_COVERAGE_EVALUATION` 最终共同汇聚到：

```text
MISSION_SUFFICIENCY
  -> REPORT_RELEASE
```

因此一个 SST/Application Scope 的成功不能掩盖另一个 Scope 的缺口。

## 3. 动态修复阶段不得预造

以下阶段不在初始 Mission Graph 中预创建：

- `DELTA_REPAIR`
- `TARGETED_REEXECUTION`

它们只能由真实 Gap 驱动生成，例如：

```text
FAILURE_COVERAGE_EVALUATION
  -> Coverage Gap
  -> DELTA_REPAIR
  -> TARGETED_REEXECUTION
  -> FAILURE_COVERAGE_EVALUATION
```

没有 Gap 时预造修复任务属于假执行，禁止。

## 4. 初始可调度规则

Mission Bootstrap 完成后：

- 每个 Scope 只有自己的 `SCOPE_INTAKE` Stage 为 `READY`；
- 其余 Stage 必须保持 `PENDING`；
- 每个 READY `SCOPE_INTAKE` 创建一个首批 WorkItem；
- 下游 WorkItem 只能在前置 Stage 真实完成并通过对应 Gate 后生成；
- 不允许一次性把整条链全部标记 READY。

两个 Scope 必须得到两个独立 READY 入口，而不是合并成一个“大任务”。

## 5. Stage 与 WorkItem 身份关系

`WorkItemIdentity.stage` 表示阶段类型，用于人类理解和调度路由；它不能替代具体 Stage Instance 身份。

RC8 使用正式表：

`rc8_stage_work_item_link`

保存：

- `work_item_id`
- `stage_instance_id`
- `test_run_id`
- `created_at`

约束语义：

- 一个 WorkItem 只属于一个 Stage Instance；
- 一个 Stage Instance 后续允许拆成多个 WorkItem；
- 重试、并行 Scope、Delta Test 不得靠 Stage 名称猜归属。

## 6. 启动事务不变式

以下事实必须在**同一个 PostgreSQL 事务**中成功或失败：

1. TestRound Scope 完整性校验；
2. TestRun 创建；
3. 初始 Mission Graph Stage 落库；
4. 首批 READY WorkItem 落库；
5. Stage <-> WorkItem 显式映射落库；
6. TestRound `PLANNED -> ACTIVE`。

任何一步失败时，不得留下：

- 空 TestRun；
- 只有部分 Stage 的 TestRun；
- 无 Stage 归属的 WorkItem；
- 已 ACTIVE 但没有任务图的 TestRound。

## 7. TestRound Scope 冻结

TestRound 启动后，其 RequirementDelivery 集合冻结。

如果运行中允许向同一轮追加需求，会产生：

```text
TestRound 页面范围 != TestRun 启动快照 != Stage/Attempt 实际测试范围
```

这是 Runtime Truth 分叉，必须 fail-closed：

`TEST_ROUND_SCOPE_FROZEN_AFTER_START`

范围变化应进入新的 TestRound，或通过明确的 Gap/Delta 机制在当前冻结快照上生成补充 WorkItem，不能静默改原始范围。

## 8. 并发新建下一轮

同一个 ProductionBatch 下，“新建下一轮”的 `round_no` 分配必须串行化。

Center 使用 ProductionBatch 行锁，在同一事务中完成：

```text
lock ProductionBatch
  -> read max(round_no)
  -> allocate N+1
  -> validate deliveries
  -> create TestRound
  -> create TestRoundDelivery links
  -> commit
```

数据库唯一约束 `(production_batch_id, round_no)` 是最后一层 fail-closed 保护，不能依赖“先查询再另一个事务插入”。

## 9. 真相边界

- Mission Graph 已创建 != Stage 已执行
- WorkItem READY != WorkItem EXECUTED
- WorkItem COMPLETED != Stage Sufficiency PASS
- Stage 完成 != TestRound Sufficiency PASS
- TestRound COMPLETED != RequirementDelivery COMPLETED
- Mission Sufficiency PASS != Release PASS
- Cloud CI PASS != BANK_REALITY_VERIFIED

RC8 Release 在真实 Bank Reality 和既有 Gate 未完成前继续保持 `HOLD`。
