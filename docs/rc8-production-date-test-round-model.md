# RC8 投产日期与多轮测试任务模型

> 本文档是 RC8 测试任务组织的正式设计约束。代码、数据库迁移、API 和回归测试必须遵守本文，不得再把“投产日期”“需求交付”“测试轮次”混为一谈。

## 1. 业务入口

用户发起测试时，顺序固定为：

1. 先选择 **投产日期**；
2. 再确定这个投产日期包含的 **需求**；
3. 对每个需求确定实际交付范围：**系统 / 系统版本 / 应用 / SST**；
4. 在这个投产日期的测试周期内进行 **第 1 轮、第 2 轮……第 N 轮测试**；
5. 每轮保留自己的分析快照、测试设计、用例、执行 Attempt、证据、覆盖率、Gap、缺陷和充分度结果。

## 2. 正式领域关系

```text
ProductionBatch（投产批次，本质就是投产日期）
  ├─ RequirementDelivery（需求在该投产日期的一次交付参与）
  │    └─ RequirementDeliveryScope
  │         ├─ System
  │         ├─ SystemVersion
  │         ├─ Application（可选）
  │         └─ SST
  │
  └─ TestRound 1..N（同一个投产日期内的多轮测试）
       └─ TestRoundDelivery（本轮纳入哪些 RequirementDelivery）
            └─ 后续 Stage / WorkItem / Case / Attempt / Evidence
```

## 3. 不可破坏的不变式

### I-01 投产批次就是投产日期

`ProductionBatch` 表示一次实际投产日期/窗口。创建多个 TestRound **不得**创建新的 ProductionBatch。

### I-02 多轮测试不是需求迭代

`TEST_ROUND != PRODUCTION_BATCH != REQUIREMENT_DELIVERY_HISTORY`

同一个需求在同一个投产日期内经历 4 轮、10 轮测试，都仍然是同一个 `RequirementDelivery`。

### I-03 一个需求可以一个投产日期就完成

例如需求 R001 在 2026-11-15 投产：

```text
R001 / 2026-11-15
  Round 1
  Round 2
  Round 3
  Round 4
  RequirementDelivery -> COMPLETED
```

这仍然是“单投产日期完成”，不能因为有 4 个 TestRound 被判定为跨批次持续交付。

### I-04 一个需求也可以跨多个投产日期持续交付

只有当同一个 Requirement 真实进入另一个 ProductionBatch 时，才建立新的 `RequirementDelivery`，并通过 `continuation_of_delivery_id` 保留交付历史。

```text
R001
  2026-11-15 -> Delivery A -> Round 1..N -> PARTIAL
  2026-12-10 -> Delivery B -> Round 1..M -> COMPLETED
```

“是否跨批次”只由需求参与了多少个 **不同投产日期** 决定，绝不能由 TestRound 数量决定。

### I-05 一个需求可以关联一个或多个系统版本和 SST

一个 `RequirementDelivery` 可以有多个 Scope。每个 Scope 明确系统、系统版本、应用和 SST；同一需求可以：

- 只关联一个系统版本的一个 SST；
- 一个系统版本关联多个 SST；
- 同时关联多个系统版本，每个系统版本再关联一个或多个 SST。

系统版本/SST 是需求交付范围，不是 Test Mission 的顶层入口。

### I-06 同一个 RequirementDelivery 可以进入同一投产日期的多轮测试

例如 Delivery A 可以同时出现在 Round 1、Round 2、Round 3。每轮是新的测试事实，不能覆盖前一轮。

### I-07 禁止跨投产日期挂错需求交付

`TestRound.production_batch_id` 必须与被加入该轮的 `RequirementDelivery.production_batch_id` 完全一致，否则必须 fail-closed：

`TEST_ROUND_DELIVERY_PRODUCTION_DATE_MISMATCH`

### I-08 完成一轮测试不等于需求完成

`TestRound -> COMPLETED` 只代表这一轮测试结束，不允许隐式修改 `RequirementDelivery.state`。

需求是否 `PARTIAL / COMPLETED` 是独立业务判断，必须由真实交付事实决定。

### I-09 历史不可覆盖

Round 2、Round 3 不得覆盖 Round 1 的测试事实。每一轮必须保留独立 ID、轮次号、状态和后续证据链。

### I-10 轮次号在同一投产日期内唯一且单调增加

同一个 `ProductionBatch` 下 `(production_batch_id, round_no)` 唯一。另一个投产日期可以重新从 Round 1 开始。

## 4. 用户最终看到的组织方式

```text
投产日期：2026-11-15
├─ 需求 R001
│  ├─ 系统A / A-1.8.0 / SST-A101
│  ├─ 系统A / A-1.8.0 / SST-A102
│  └─ 系统B / B-3.2.0 / SST-B208
├─ 需求 R002
│  └─ 系统C / C-2.6.1 / SST-C330
│
├─ 第1轮测试
│  ├─ R001
│  └─ R002
├─ 第2轮测试
│  ├─ R001（修复后回归 + 增量测试）
│  └─ R002（受影响范围回归）
└─ 第3轮测试
   └─ R001（Coverage Gap 补测）
```

用户不需要手工编排 Agent。数字员工根据每轮 Actual / Gap / Defect / Change 自动生成下一轮或本轮的增量 WorkItem。

## 5. 与测试闭环的关系

TestRound 是业务测试周期容器，不替代 RC8 已有的 Stage/WorkItem/Attempt/R1/Evidence 模型：

```text
ProductionDate
  -> TestRound
     -> Stage
        -> WorkItem
           -> TestCase / ExecutableSpec
              -> Attempt
                 -> Evidence / Coverage / Gap / Defect
```

失败或覆盖不足可在当前轮内产生补充 WorkItem，也可在代码/需求发生新的可识别变化后进入下一轮。无论哪种情况，都必须保留真实历史。

## 6. 真相边界

- TestRound COMPLETED != RequirementDelivery COMPLETED
- RequirementDelivery COMPLETED != Mission Sufficiency PASS
- Mission Sufficiency PASS != Release PASS
- Cloud/CI 验证 != BANK_REALITY_VERIFIED

RC8 当前 Release 仍保持 HOLD，除非真实证据满足既有 Release Gate。
