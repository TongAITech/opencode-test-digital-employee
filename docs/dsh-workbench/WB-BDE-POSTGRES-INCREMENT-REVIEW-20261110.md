# PostgreSQL 增量合同 B/D/E 技术评审

状态：REVIEW_IN_PROGRESS / 新增量待固定源 SHA；不是历史团队代签，不是 F 验收。
评审日期：2026-11-10；执行者：本轮独立合同技术审查 Agent。

## 当前远端与历史签署范围

本轮读取 A PR #84 源 `5c1a5f4e10ed9f79bb523516d340ff21f58c72f0`；RC7.2 远端 `87f956f1388f58beabf7116c937fd6fda5fae2ca`。
B #108 `b801c25bbec361e6a791c561d5a7dd0ec9440aaf`、E #107 `a04933fbe7b651c10b589b90cade5da65bdd8b81`、D #90 `a332e6c575cac9d2b6ef0b2038615b276dcfa602` 均已 MERGED，各自 check success 只属于这些完整源 SHA 的设计/组件检查。
B 既有签署已将 PostgreSQL 列为 W1 实施目标，SQLite 只是约束设计见证。D/E 既有签署保留宿主身份和 R1 权威边界，不能自动当作新 PostgreSQL 增量签署。

## B 领域审查要求

正式数据库应持有项目、批次业务 DATE、稳定身份及带 project 的 BR/BV/BRV/BRVS 复合外键、来源白名单、版本限定 SST 原始身份。必须保持经验证来源不可静默修改和 SPLIT 状态由实际合法连边推导。事务须覆盖关系、CAS、审计与领域 outbox；真实 PostgreSQL 正反向/并发/崩溃及回滚必须另验。

## D 宿主审查要求

数据库仅保留宿主 opaque ref、业务绑定、权限修订和审计，不拥有第二套模型密钥、会话历史或 Skills/Commands 注册表。服务端 principal 来自已认证 Host；连接池身份上下文不得跨请求泄漏；权限撤销后游标、SSE、恢复上下文失效，未知宿主能力 fail closed。

## E R1 审查要求

Mission/Attempt/Evidence/NodeGate 和执行租约继续由 RC7.2 R1/正式控制面负责；PostgreSQL 不成为第二个 runtime truth。数据库命令日志/outbox 的提交不等于 R1 已执行，跨存储崩溃必须对账原命令身份，未知副作用 HOLD。Evidence 大字节在受控存储，元数据/hash/ref 不能代替回读校验和正式 provenance。

## 发现与建议

P1 设计文字歧义：06 最后 B06 段和 A03 历史段写“R1 读取后验证 Mission”，容易复现已发现的先读 details 再校验。新合同必须明确只允许先读最小唯一 Mission 身份，核对 project+batch 后才读 Tasks/Executions/Evidence，拒绝前相关明细查询数为零，无 unscoped fallback。已通知合同作者。

## 门禁

新增量完成后固定完整 SHA，再逐条落结论。当前不能记 B/D/E 新增量签齐或 W0_DESIGN_FROZEN；W1 真数据库、Host、API、Windows 和现场仍 NOT_RUN。未修改 A 的 08/09/10，也未改 RC7.2 主线。
