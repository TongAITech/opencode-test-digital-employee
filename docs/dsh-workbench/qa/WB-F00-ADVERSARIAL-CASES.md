# WB-F00 独立反例测试目录（候选验收集，尚未执行）

审查输入：`work/dsh-wb-w0@12a16a2a0e5726ffe275571ae59e6eacb4f4c4e8`。
状态：**SPEC_ONLY / NOT_RUN**。本文件不是测试执行日志，更不是产品 QA_PASS。任何 F01/F02/F03/F04 真验收必须补充运行命令、source_sha、实测输出、R1 事件/证据和截图。

## 1. 确定性测试底座

使用明确的稳定 ID，不用模糊名称连接：
- 项目 `P-A`，批次 `B-A-1112` 的用户可见日期为 `2026-11-12`；第二批次 `B-A-1119` 日期为 `2026-11-19`。
- 项目 `P-B` 也有 `2026-11-12`，稳定 ID 为 `B-B-1112`；`P-B` 用户不可读取 `P-A`。
- 系统 `SYS-A`、`SYS-B`、`SYS-C`；真实版本 `V-A-120` (SYS-A, label PF1.2.0)、`V-A-121` (SYS-A, PF1.2.1)、`V-B-120` (SYS-B, PF1.2.0)、`V-C-310` (SYS-C, PF3.1.0)。
- `B-A-1112`：`R1` 对应 `V-A-120` 的 SST `A-101,A-102`，`V-A-121` 的 `A-103`，`V-B-120` 的 `B-201,B-202`；`R2` 对应同一个 `V-A-120` 的 `A-104` 和 `V-C-310` 的 `C-301`；`R3` 对应 `V-B-120` 但尚未拆 SST。
- `B-A-1119`：`R1` 可再次出现，但有该批次自己的关联与 SST `A-1119-101`；不复用 `B-A-1112` 的 SST 关联。
- 数据种子保存后必须有 `canonical_scope_revision`、来源标识和创建事件，可在重启后复原；不得把不同 batch/system 的同名文本当作关联依据。

## 2. 正反向测试（原合同 T1–T10 + 增强反例）

| 用例 | 操作/可重现输入 | 预期可判定结果 | 执行状态 |
|---|---|---|---|
| T1 多版本多 SST | Scope `P-A/B-A-1112/R1`，查询 versions 与 SST | 返回三版本、五个独立 SST，`V-A-120` 有 2，`V-A-121` 有 1，`V-B-120` 有 2；计数可回溯关联表 | NOT_RUN |
| T2 共享版本不共享 SST | Scope `P-A/B-A-1112/R2/V-A-120` | 仅有 `A-104`，不得混入 R1 的 `A-101,A-102`；两需求指向同一个 `V-A-120` 对象 | NOT_RUN |
| T3 不同系统同标签 | 按 `PF1.2.0` label 查询 `V-A-120` 与 `V-B-120` | 两个不同 `system_version_id`，不能以 version_label 去重或跨系统计数 | NOT_RUN |
| T4 跨日期重名 | `B-A-1112/R1` 与 `B-A-1119/R1` 联合查询 | 每条显示自己的 batch 身份与 SST，默认不串数据；日期可跨项目复用 | NOT_RUN |
| T5 SST 未拆 | `P-A/B-A-1112/R3/V-B-120` | 关联可见且标记“待拆分”，不能静默消失或当作空成功 | NOT_RUN |
| T6 跨批次越界 | 在 `B-A-1112` 试图创建 `(R1,V-A-120,A-1119-101)`；或使用不存在的 `(R2,V-B-120,A-104)` | `422 ILLEGAL_ASSOCIATION`（授权主体合法前提下），R1 无增量，数据库无半写入 | NOT_RUN |
| T7 用例跨 SST 去重 | 一个 Case 映射 `A-101,A-102`，创建一次受控 Attempt | Case 可关联两义务，Attempt 只有一个稳定 ID；义务分别校验适用 Oracle/Evidence，不按两次执行计数 | NOT_RUN |
| T8 修改投产日期 | 将 `B-A-1112` 从 2026-11-12 修订到合法新日期 | 稳定 `batch_id` 不变，date history 完整；原始 Attempt 的发生时上下文可审计；同项目日期冲突拒绝 | NOT_RUN |
| T9 断线恢复 | 保存 Scope 与原生 DSH session 绑定，重启宿主并从项目入口恢复 | 复原合法筛选；若权限或关联变化，显式警告并清理失效筛选；不得创建重复 Mission/Attempt | NOT_RUN |
| T10 跨项目授权 | 以只拥有 `P-B` 权限的主体请求 `P-A/B-A-1112`，分别查询 Scope/质量/证据/事件流 | `403 FORBIDDEN`，不得泄露项目是否存在、字段或 SSE 事件，R1 不新增写事件 | NOT_RUN |
| T11 N10 及人工门禁 | 看板直接拖到“已发布”，但 N10=BLOCKED 或 HUMAN_GATE | 显示阻断及原因，不改写 NodeGate、不置 PASS；审批不足继续拒绝 | NOT_RUN |
| T12 追踪双向 | 从 `A-101` 出发贯穿 CodeSlice→TestObligation→Case→WorkItem→Attempt→Evidence→Defect/Report 并返回 | 每一跳含稳定 ID、source_ref、truth_revision、batch_id、来源时间；反向回溯同一图，不以字符串相似度连接 | NOT_RUN |
| T13 幂等事件 | 以相同 `command_id/idempotency_key` 重发控制命令，SSE 按 event_id/revision 重放、断线重订 | 原命令仅执行一次；冲突返回 `409`，历史事实保留；UI 不重复累加计数 | NOT_RUN |
| T14 状态/环境反例 | 模型说 PASS 但 R1 仅有 DISPATCHED、BLOCKED 或无 assertion/evidence；或浏览器 4A 登录态过期 | UI 仍不得标 PASS；SUT 4A 状态与 Agent 会话独立，需重新受控登录或 BLOCKED/HUMAN_GATE | NOT_RUN |

## 3. 后续可执行 API 回放协议（当前接口尚未实现）

工作台设计草案 `06-API-AND-EVENT-CONTRACT.md` 定义了以下候选请求：

```text
GET /api/workbench/v1/projects/P-A/release-dates
GET /api/workbench/v1/projects/P-A/release-dates/2026-11-12/scope
GET /api/workbench/v1/projects/P-A/release-dates/2026-11-12/quality
GET /api/workbench/v1/missions/<mission-id>/graph
GET /api/workbench/v1/missions/<mission-id>/workitems
GET /api/workbench/v1/attempts/<attempt-id>/evidence
GET /api/workbench/v1/events
POST /api/workbench/v1/missions/<mission-id>/commands
```

以上是 **未来测试目标，不应在当前 HEAD 伪造成功调用**。在 A03 冻结字段前，F 只记录测试数据、行为预期和阻断点；接口响应和状态码约束必须由 B/E 提供实际实现与运行日志。

## 4. 额外平台级验收记录要求

- 原六个页面与十区：为每个原版按钮和列表状态生成 `feature_id, action, expected, actual, screenshot_ref, network_trace, source_sha`，标明新增子视图不替代原版功能。
- N1–N10：每个节点都核对 Delivery、Sufficiency、NodeGate 及 BackEdge；评审/执行不能靠前端更改状态伪造。
- R1：同一 Snapshot 可重算需求/代码/用例/Attempt/Evidence/缺陷/报告数值；R1 缺失要明确 TRUTH_SOURCE_UNAVAILABLE。
- Windows Git Bash：clean-unpack、非管理员/断网、路径含空格和中文、离线 Node/Python/Chromium/BSK 清单及 hash、宿主 1.18.26 会话恢复、卸载后重装及数据不丢；完成前 QA-10 NOT_RUN。
- 许可证：建立 SBOM 与源码来源扫描；缺商业授权时 `naodeng/dsh-qa` 源码复制路径必须零命中，不能通过删除 PolyForm 声明“消除”限制。

## 5. A 组整改后回归入口

1. A01 完整功能矩阵；A03 领域+API+事件联合合同，附每个反例的明确 Schema/预期。
2. B 提供领域存储/跨批次拒绝和数据迁移可运行测试；E 提供 R1 只读/受控命令的正式执行路径；C/D 给原版交互和 DSH 宿主证据。
3. F 用新的代码 SHA 在真实 SUT 上逐个执行，不采信文档中写的 `PASS` 或模拟响应。
4. 有新 HEAD 后重新确认 CI 及每一条证据的 SHA；不能复用旧 HEAD 的绿色检查。
