# RC8 投产批次优先的测试任务模型

## 1. 冻结业务规则

RC8 的用户入口不是“选择系统版本开始测试”，而是先确定计划投产日/投产批次，再确定本批次包含的业务需求。

一个业务需求是长期主实体，但不强制存在“需求迭代/RequirementRevision”层。需求可以在一个投产批次内一次完成，也可以在多个投产批次中持续交付。是否存在下一次交付，只由真实投产关系决定，系统不得预先虚构迭代。

系统版本、应用和 SST 是某个需求在某次投产批次中的实现载体，不是 Test Mission 的顶层。

## 2. 正式关系

```text
ProductionBatch（投产批次）
  └─ RequirementDelivery（某需求参与本批次的一次交付）
       ├─ Requirement（长期需求主实体）
       └─ RequirementDeliveryScope（本次交付实际实现范围）
            ├─ System
            ├─ SystemVersion
            ├─ Application（可选）
            └─ SST
```

基数约束：

- 一个 ProductionBatch 可以包含多个 RequirementDelivery。
- 一个 Requirement 在同一 ProductionBatch 中只有一个 RequirementDelivery，避免同批次重复建任务。
- 一个 Requirement 可以在不同 ProductionBatch 中拥有多个 RequirementDelivery，因此天然支持跨批次持续交付。
- 一个 RequirementDelivery 可以拥有一个或多个 RequirementDeliveryScope。
- 一个 Scope 精确表示 `delivery + system + systemVersion + application + SST`；同一 Scope 不得因换一个 scope_id 被重复创建。
- 历史 Delivery 和 Scope 不覆盖。新增后续批次只追加新 Delivery；已完成 Delivery 不允许重新打开。

## 3. 单批次完成与跨批次交付使用同一模型

### 3.1 一个批次完成

```text
PB-20261115
  └─ REQ-001 / DEL-001 / COMPLETED
       └─ SYS-A / A-1.8.0 / SST-A101
```

此时 Requirement 的交付历史只有一条，`completed_in_single_batch=true`。系统不会创建多余的 RequirementRevision。

### 3.2 多个批次持续交付

```text
REQ-002
  ├─ PB-20261115 / DEL-101 / PARTIAL
  │    └─ SYS-A / A-1.0 / SST-A101
  └─ PB-20261220 / DEL-102 / COMPLETED
       └─ SYS-B / B-2.0 / SST-B201
```

第二条 Delivery 可以通过 `continuation_of_delivery_id` 显式关联上一条，但 Requirement 主实体保持不变。前一批的状态和 Scope 继续保留，不能被第二批覆盖。

即使上一条 Delivery 已经 COMPLETED，未来业务又对同一需求主实体追加新的真实交付，也可以在新的 ProductionBatch 中创建新的 Delivery；“完成”描述的是该批次交付，不代表禁止未来业务继续演进。

## 4. 一个需求对应多个系统版本和 SST

RequirementDeliveryScope 不限制一个需求只属于一个系统版本。例如：

```text
PB-20261115 / REQ-003 / DEL-201
  ├─ SYS-A / A-1.8.0 / cfg-center / SST-A105
  ├─ SYS-A / A-1.8.0 / cfg-data   / SST-A106
  └─ SYS-B / B-3.2.0 / cfg-admin  / SST-B301
```

因此测试规划必须从 RequirementDelivery 的全部 Scope 汇总影响面，再分别生成 Scope 内测试和跨 Scope 的需求级业务链路测试。

## 5. 用户实际使用流程

```text
确定投产日/投产批次
  → 选择/同步本批次需求
  → 系统还原每个需求对应的系统版本、应用、SST
  → 用户确认投产范围
  → 创建 TestRun（绑定 production_batch_id）
  → 按 RequirementDelivery/Scope 自动拆分析、设计、数据、L1-L7 执行 WorkItem
  → Actual/Evidence
  → Gap/Defect
  → Delta WorkItem / Targeted Rerun
  → Sufficiency
  → 投产报告
```

用户负责确认投产事实与必要 Human Gate，不负责手工编排 Agent。

## 6. 状态语义

RequirementDelivery 状态：

- `PLANNED`：已纳入本批次，尚未开始。
- `IN_PROGRESS`：本批次需求交付/测试正在进行。
- `PARTIAL`：本批次只完成部分范围，允许后续批次继续交付。
- `COMPLETED`：本批次对该需求声明的交付范围已经完成。
- `CANCELLED`：本批次取消该需求交付。

`COMPLETED` 和 `CANCELLED` 是该 Delivery 的历史终态，禁止原地回退。后续真实变化通过新的 ProductionBatch + RequirementDelivery 表达，从而保留历史。

## 7. 与 RC8 运行事实的边界

本模型负责“要测什么、为什么属于这次投产、范围是什么”。WorkItem/Attempt/R1/Artifact/Governance 继续负责“实际执行了什么、结果和证据是什么”。

因此：

```text
ProductionBatch / RequirementDelivery / Scope
        ↓ 规划来源
TestRun / Stage / WorkItem / Case / Attempt
        ↓ 运行事实
R1 / Artifact / Coverage / Gap / Defect / Sufficiency
```

建立任务模型不等于测试充分，不得因此把 `TEST_SUFFICIENT`、`BANK_REALITY_VERIFIED` 或 Release Gate 改成 PASS。
