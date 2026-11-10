# B对E03 PG008/Scope/跨R1对账提案的独立职责审查

精确被审源：0e8259cd96b54e5009eecc2bac01a532eb896b3f，文件WB-E03-CONTROL-DEPENDENCY-AUDIT.md。本次仅B职责设计审查，不实现PG008、拒绝journal或正式gateway，不代D/E/F签署，不修改R1或08/09/10。

结论：**B_DESIGN_REVIEWED_WITH_REQUIRED_DETAILS**。下列原则可接受，但当前提案还不能直接成为可实施的PG008数据库/API合同。E03保持BLOCKED_FORMAL_CONTROL_API / DESIGN_REVIEW_PENDING；不能凭本报告生成accepted、解除动作阻断或变更冻结Mission状态机。

## 可接受范围

- 工作台仅保存业务命令意图、outbox和正式回执引用；R1正式控制事实仍由RC72 CommandGateway及专项controller拥有。PG journal状态不等于Mission/Attempt/NodeGate状态。
- 可信Host mutation/CSRF、project+batch合法Scope、显式Mission归属、动作专属payload、expected revision和正式租约/人审都必须验证；不直接调scheduler/append R1。
- 正式gateway先提供submit/query、持久幂等与稳定command_ref。PG/R1没有跨存储原子假设；未知副作用HOLD并对账，不用超时冒充拒绝/失败，也不盲目产生新Attempt。
- PG008必须在正式协议审查和控制面能力落地后才接入发送路径。现有pause/resume未支持、retry需正式恢复计划、Human Gate需正式request/签名的依赖判断保持，不可由journal“补齐”。

## 进入PG008实施前需补充的B合同

| 项目 | 必需明确的约束/退出条件 |
|---|---|
| 关系与身份 | intent_id稳定主键；project/batch复合FK到既有业务批次；Mission只保存正式gateway核对后的显式归属与来源修订，不造另一张权威Mission表。Scope保存完整合法关系身份/关系修订，不按release label或raw SST猜边。 |
| 幂等域与payload | 与A03一致明确(principal_id,project_id,mission_id,idempotency_key)唯一域及不可变batch/Scope绑定；action、动作专属payload、scope_ref、expected_state_revision、reason的规范digest版本要固定。相同键异负载409；重放先按当前权限鉴权，再返回原正式回执，不能把最新状态覆盖成“原响应”。 |
| 原子事务 | 接受意图时同一PG事务完成可信主体/ACL、batch关系修订校验、journal、audit、outbox。业务runtime无迁移/ACL/正式回执伪造权限；payload/actor/Scope/digest和审计追加不可改，投递元数据CAS单列/单表。 |
| 分工和正式修订 | PG可以校验业务relation/access revision；正式expected_state_revision必须由gateway在R1原子比较，不能拿PG revision代替。正式controller仍负责资源租约、人审、恢复plan和状态合法边，不能以PG提交成功抵扣。 |
| 并发投递 | outbox记录与intent复合FK及唯一事件；投递claim的租约、generation/fencing、CAS状态迁移、过期owner处理需有明确字段。即使重复投递，正式gateway仍按相同权威幂等域只执行一次。 |
| 回执来源 | 明确正式receipt的发行者、principal/project/batch/Mission、payload digest、command_ref、正式来源revision/事件ref、时间/校验哈希；只经可信gateway适配器写入引用，浏览器不得自报verified或accepted。跨Mission/跨主体/同ref异digest必须HOLD且保留异常证据。 |
| Scope变化/撤权 | 初次提交与每次发送/查询均应有当前授权和合法Scope策略；撤权/资源失效可停止本地投递但不能伪造“正式已拒绝”。原已提交命令的历史Scope保持不可变，重对账不静默换到新批次/新principal。 |
| 迁移与审计 | 008须命名PK/FK/唯一键/NOT NULL、角色/RLS、事务审计、schema checksum、空表回退与非空备份对账HOLD；不得改007或旧迁移checksum，也不得清理原R1失败/lease/Attempt分母。 |

## 必须解决的丢回执窗口

提案要求正式query与command_ref，但如果gateway已提交R1、PG尚未收到command_ref就崩溃，工作台不知道ref，单纯query(command_ref)不足以恢复。正式协议必须支持按**原principal/project/Mission/idempotency_key及payload digest查原回执**，或证明重复submit同一权威键只查询/返回原结果而绝不重执行。此能力须由正式控制面实现，不能由PG自行“猜accepted”。不可查询且无法排除副作用时继续UNKNOWN/HOLD，不分配新UUID绕过。

恢复测试至少包括：PG意图提交前失败、提交后发送前崩溃、R1提交后丢ref、PG落正式ref前/后崩溃、双消费者并发、旧lease owner恢复、授权撤销、Scope修订、异payload重放、伪造/跨Mission回执、正式query不可用。每步以真实持久R1/PG数据Oracle证明副作用次数及历史保留；fixture executor/签名不能授予生产动作支持。

## 新发现的主体域恢复约束

本轮资产恢复已真实发现Alice未知提交→Bob同项目写权重放会落到新幂等域。E03也必须防同类原意图跨主体重绑：客户端pending捕获原opaque expected write-context，重试不得补当前主体token；服务端在journal/幂等回执读取前比对当前可信主体域。新D/C合同6661e80规定该token非授权、非SSO、非签名authority；CSRF/ACL/Captain/资源租约仍独立。后台outbox必须使用审查后的正式委托/authority保留原actor，不能借当前Bob会话或复制Captain凭据替换原主体。具体协议由D/E增量确认，不在本报告擅自实现。

## 审查边界

本报告是B的源码/合同设计审查，未运行不存在的PG008/正式gateway产品测试。可先补精确字段、失败/恢复状态和上述协议，再由B/D/E/F评审独立增量、A决定冻结合同变更；本报告不代替该门禁。行外现场统一FIELD_NEEDS_BANK_TRANSFER，不虚构Host、银行签名或Windows证据。
