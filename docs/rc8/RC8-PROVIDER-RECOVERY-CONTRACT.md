# RC8 模型服务限流与自动恢复合同

## 目标

模型频率限制、502/503/504、SSE 未正常结束、连接/读取超时属于 Provider/Transport 故障，不得直接等价为测试任务失败，更不得依赖人工输入“继续”才能恢复 Mission。

恢复决策必须由非 LLM Supervisor 完成；模型服务失效时恢复控制面仍需可运行。

## 统一请求预算

Director 与所有 Worker 对同一 Provider/账号共享 `RequestGovernor`。`max_requests/window_seconds/safety_ratio` 均为环境配置，不把某个行内额度硬编码成产品常量。

达到安全预算后先进入 `WAITING_PROVIDER_CAPACITY`，排队和背压，不继续制造 429 重试风暴。

## 故障分类

- 429 -> RATE_LIMIT
- 502/503/504 -> TRANSIENT_SERVER
- SSE ended/closed without正常 DONE -> SSE_INCOMPLETE
- connect/read timeout -> CONNECT_TIMEOUT / READ_TIMEOUT
- 401/403 -> AUTH_CONFIGURATION
- 其他确定性 4xx -> INVALID_REQUEST
- 无法分类 -> UNKNOWN，fail-closed

Provider 状态独立于测试任务状态：HEALTHY / DEGRADED / UNAVAILABLE。

## Durable Recovery

模型请求前必须存在持久化 RecoveryCheckpoint，至少包含：Mission、TestRun、Stage、WorkItem、Attempt、InputSnapshot、Cursor、已完成副作用。

Transient fault 恢复必须复用原 Mission/WorkItem/Attempt 的 durable identity，从最后安全 Cursor 继续，禁止创建一个新 Mission 冒充恢复。

RecoveryCheckpoint 的持久事实存放在 PostgreSQL；Redis 只允许用于请求预算、lease、队列等协调，不允许成为恢复真相。

Center 启动时必须执行 startup reconciliation：读取仍开放的 checkpoint，形成确定性的 resume plan。允许 Provider/模型从 BankGPT 切换到 DSV4 或其他已探测可用模型，但 Mission、Stage、WorkItem、Attempt、InputSnapshot 与 Cursor 不得因模型切换改变。

模型切换本身不能成为“重新规划任务”的理由；完成过的副作用与 Evidence 不能重复生成。

R1 运行事实至少包括：
- PROVIDER_CAPACITY_WAITING
- PROVIDER_RETRY_SCHEDULED
- PROVIDER_RECOVERY_WAITING
- PROVIDER_CHECKPOINT_RESUME_READY
- PROVIDER_SIDE_EFFECT_RECONCILIATION_REQUIRED
- PROVIDER_CONFIGURATION_BLOCKED

## 副作用安全

若外部副作用“可能已成功但响应丢失”，Checkpoint 必须标记 `UNKNOWN`，Supervisor 只能进入 `RECONCILE_SIDE_EFFECT`。在对账完成前禁止盲目 replay，避免重复缺陷、重复数据库写入、重复执行或重复 Evidence。

## 故障注入验收

1. 达到共享预算安全线：后续请求排队，不丢 Mission；容量恢复后可继续原 WorkItem。
2. 429：WAITING_PROVIDER_CAPACITY，不把测试任务判 FAILED。
3. 502/503/504：指数退避；连续故障进入 WAITING_PROVIDER_RECOVERY。
4. SSE 中断/read timeout：Attempt 可追踪，无假 PASS，并调度恢复。
5. Provider 恢复探针成功：Health 复位 HEALTHY。
6. 未知副作用：必须 reconciliation 后才能 replay。
7. 恢复 identity 稳定，不能创建重复 Mission/WorkItem。
8. PostgreSQL 写入 checkpoint 后销毁并重建 Center 数据访问对象，必须仍能恢复同一 Mission/Stage/WorkItem/Attempt/Cursor。
9. BankGPT -> DSV4 模型切换不得创建新 Mission，也不得要求用户输入“继续”。
10. 新 checkpoint 必须替代同一 WorkItem 的旧开放 checkpoint，避免从过期 Cursor 恢复。

## 当前验证边界

云端 PostgreSQL 重启/模型切换回归只能证明 Center 持久化与确定性恢复语义，不等价于行内模型服务 Reality。必须在行内真实 DSH/模型服务环境中注入 429、502、SSE 中断、模型切换与进程重启，并核对 R1 Event Stream、PostgreSQL checkpoint、实际 Worker 续跑与副作用幂等后，才能提升 Bank Reality 状态。

`BANK_REALITY_VERIFIED` 在上述现场验证完成前必须保持 `NO`。
