# RC8 自主阶段推进契约

状态：FROZEN CONSTRUCTION CONTRACT

## 1. 业务入口

生产任务必须保持以下层级：

```text
投产日期（ProductionBatch）
  -> RequirementDelivery / RequirementDeliveryScope
  -> TestRound（同一投产日期内可有多轮）
  -> TestRun
  -> Mission Stage
  -> WorkItem
  -> Attempt
  -> Evidence / Coverage / Gap / Defect
```

TestRound 不是投产批次，也不是需求迭代。一个需求可以在同一投产日期内经过多轮测试后完成。

## 2. 自主推进的唯一合法条件

`WorkItem COMPLETED` 不能直接推导 `Stage COMPLETED`。

普通活动 Stage 只有同时满足以下条件才能完成：

1. WorkItem 与 StageInstance 有正式持久化血缘；
2. 存在同一 WorkItem + StageInstance 的 `ATTEMPT_COMPLETED`；
3. Attempt 已由 R1 投影到治理仓储，而不是本地日志或 UI 推断；
4. Attempt 至少有一个 Evidence 引用；
5. 每个 Evidence Artifact 均真实存在且状态为 `AVAILABLE`；
6. Artifact 的 TestRun / WorkItem 身份与当前执行一致。

随后才允许：

```text
EXECUTING
 -> EVIDENCE_PENDING
 -> COMPLETED
```

## 3. 充分度阶段不能由执行绿色代替

以下阶段属于 Sufficiency Stage：

- REQUIREMENT_SUFFICIENCY
- CODE_SUFFICIENCY
- DESIGN_SUFFICIENCY
- MISSION_SUFFICIENCY

除了 Attempt + AVAILABLE Evidence 外，还必须存在 R1 投影的 `SUFFICIENCY_EVALUATED`。

合法状态流：

```text
EXECUTING
 -> EVIDENCE_PENDING
 -> EVALUATING
 -> SUFFICIENT | INSUFFICIENT
 -> COMPLETED
```

因此：

```text
Tool PASS != WorkItem COMPLETED != Stage SUFFICIENT != Mission SUFFICIENT != Release PASS
```

## 4. 下游自动解锁

Stage 完成后，Center 必须重新按 Mission Graph 判断依赖。

只有全部 predecessor 为 `COMPLETED` 的 PENDING Stage 才能转为 READY。

READY Stage 自动生成确定性 WorkItem，并建立：

```text
StageInstance <-> WorkItem
```

血缘。用户、Director、Node 都不需要知道或手工生成下游 WorkItem ID。

Node 只调用 claim-next，Center 按 READY 状态、VERIFIED capability 和 Redis lease CAS 分配工作。

## 5. 能力约束

不得为了让任务可领取而虚构 capability ID。

已冻结能力约束必须强制，例如 Java 代码分析：

```text
CODE_ANALYSIS -> codegraph
```

后续 L1-L7 / Browser / 4A / DB / API 等 capability 必须在其真实适配器和能力探测闭环落地后再进入调度策略。

## 6. 崩溃恢复

可能存在合法 crash window：

```text
Attempt/Evidence 已持久化
WorkItem 已 COMPLETED
Stage 或下游 WorkItem 尚未推进
```

此时禁止重新执行原副作用来“补状态”。

Center 必须通过幂等 reconcile：

1. 读取 PostgreSQL WorkItem COMPLETED；
2. 读取 R1 投影 Attempt；
3. 重新验证 Artifact AVAILABLE；
4. 补齐 Stage 状态；
5. 按图解锁下游；
6. 确定性物化缺失 WorkItem。

## 7. Fail-Closed

以下任一情况必须阻止 Mission WorkItem 完成或 Stage 推进：

- 没有 ATTEMPT_COMPLETED；
- Evidence 引用为空；
- Artifact 不存在；
- Artifact 非 AVAILABLE；
- Artifact 属于其他 TestRun / WorkItem；
- Sufficiency Stage 没有 SUFFICIENCY_EVALUATED；
- Stage 状态不允许当前推进；
- Stage↔WorkItem 血缘不一致。

禁止用“worker 返回成功”“脚本 exit 0”“UI 显示绿色”绕过这些门禁。

## 8. 验收标准

至少同时通过：

1. 领域/单元：无 Attempt、无 AVAILABLE Evidence 均 fail-closed；
2. PostgreSQL：Stage/WorkItem/血缘均耐久；
3. HTTP Reality-CI：
   - TestRound 启动；
   - Node 不知道 WorkItem ID，claim SCOPE_INTAKE；
   - 真实 R1 Attempt；
   - 真实 Artifact 字节上传、size/SHA256 校验后 AVAILABLE；
   - WorkItem 完成；
   - SCOPE_INTAKE Stage 自动 COMPLETED；
   - REQUIREMENT_ANALYSIS 自动 READY + WorkItem 物化；
   - Node 再次在不知道下游 WorkItem ID 的情况下 claim 到 REQUIREMENT_ANALYSIS。

CI 通过只代表 cloud Reality-CI，不代表银行环境 Reality。

`BANK_REALITY_VERIFIED=NO`、`TEST_SUFFICIENT=NO`、`Release=HOLD` 在银行真实闭环和充分度门禁满足前保持不变。
