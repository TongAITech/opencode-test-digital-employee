# WB-A03 W0 业务/API/事件跨组签收候选
状态：A_CONTRACT_DRAFT / B_PENDING / D_PENDING / E_PENDING / F_RECHECK_REQUIRED。仅讨论 W0 DESIGN_SIGNOFF；未获得任何组签署，也未取得任何真实功能 QA_PASS。
参照 F 组 PR #85 的 FG02–05、FG10、FG13；W0 Python 合同测试只验证内存 oracle。

| 组 | 签署范围 | 必须带回的可复核证据 | 结论 |
|---|---|---|---|
| B | Batch 日期唯一/改期、复合 FK、SST 来源、事务与迁移方案、Scope 真 join | W0：字段/约束/事务/回滚设计评审，T1–T8 反例预期与接口可实现性签署；W1：真实存储、422 rollback、重启保持另验 | DESIGN_SIGNOFF_PENDING / IMPLEMENTATION_QA_NOT_RUN |
| D | DSH1.18.26 认证主体/原生会话、命令技能附件、权限和断线恢复 | W0：宿主身份/权限/Session 复用/恢复接口边界、不可复用密钥与反例签署；W1+：现场宿主日志、项目隔离和重启恢复另验 | DESIGN_SIGNOFF_PENDING / FIELD_QA_NOT_RUN |
| E | R1 只读真相/NodeGate、命令幂等/人审、batch SSE/恢复 | W0：R1 数据字段/状态机/SSE 协议/ACL 与 T9–T14 反例设计签署；W1+：真实 API/R1 Evidence/签名 Attempt/SSE 恢复日志另验 | DESIGN_SIGNOFF_PENDING / IMPLEMENTATION_QA_NOT_RUN |
| F | 独立检查合同遗漏、版权安全与设计退出门槛 | W0：审查设计合同、反例、来源锚点与分层 Gate；W1+：仅按真实证据签 IMPLEMENTATION/INTEGRATION/FIELD_QA_PASS | DESIGN_RECHECK_REQUIRED |
| A | 依赖、合同分歧、CI/GAP/PR/主线集成 | W0：持有同 SHA 契约 CI、角色书面 DESIGN_SIGNOFF 和 F 设计审查；W1+：各组真代码 + F QA 另行门禁 | IN_PROGRESS |

## 关联约束与迁移提议
稳定 ID 必须包括来源身份：project_id,batch_id,requirement_id,system_version_id,sst_id；版本显示标签不能做关联键。batch_id 固定，release_date YYYY-MM-DD 为业务可见日期，BUSINESS_TZ 待银行业务责任人批准；不能默认 UTC 或 Asia/Shanghai。旧 ReleaseBatch 先 dry-run 源 ID 映射、日期空值/同日冲突隔离、关联/分母计数、R1 历史引用；迁移事务应可逆、幂等、不重写原始 Attempt/Evidence。
关系键：BR(batch_id, requirement_id)、BV(batch_id,system_version_id)、BRV(batch_id,requirement_id,system_version_id) 指向 BR 和 BV 复合外键、BRVS(batch_id,requirement_id,system_version_id,sst_id) 指向 BRV，另外核对 SST 来源系统及版本身份。未拆 SST 为 BRV 的 UNSPLIT 状态。B1/R1/V-A/S1,S2 与 B1/R2/V-A/S4 是合法的独立连边；B1/R2/V-A/S1、从 B2 冒用 B1 SST 必须 422 且不产生部分写入。

## 拟议端点的身份授权矩阵（全是未实现 API）
| Endpoint | 权威数据 | 授权边界和失败 |
|---|---|---|
| GET projects/{p}/release-dates | B ReleaseBatch | p.read; 先鉴权，未授权 403 不泄漏存在性 |
| GET projects/{p}/release-dates/{date}/scope | B 合法四元组快照 | p/batch/关联版本一致；无关联不得笛卡尔积 |
| GET .../{date}/quality | E R1 同源快照 | R1 503 时 UNKNOWN，不返回 0/PASS |
| GET missions/{id}/graph/workitems | E R1 与控制面 | mission→batch→project 反查授权 |
| GET attempts/{id}/evidence | E Evidence | Attempt→Mission→batch→project 全链 ACL 和 hash |
| GET events（SSE） | E batch 事件流 | 订阅/重放限制 project+batch+权限版本，切批必重订 |
| POST missions/{id}/commands | E 正式控制面 | principal 服务端派生、Scope/修订/幂等/人审/租约 |

默认拒绝：未经授权 403 优先且不能泄露资源存在性；合法主体的不存在对象 404、非法批次连边 422、版本或幂等冲突 409、无 R1 503。查询应提供 project_id,batch_id,release_date,relation_revision,access_scope_revision,truth_revision,as_of,source_refs,page_cursor；游标绑定主体、权限/关联版本、Scope，变更后必须重新查询。
命令 body 仅 command_id,idempotency_key,scope_ref,expected_state_revision,action,reason；禁止客户端提交 principal/authorization 或 publish/NodeGate 强制 PASS。幂等持久键为 (principal_id,project_id,mission_id,idempotency_key)：同键同 payload 返回原 command_ref，不同 payload=409；事务中校验状态、人审及资源条件，不能靠内存重复去重。
SSE 每事件包含 event_id,project_id,batch_id,type,revision（该 batch 流有序）,truth_revision（R1 独立）,source_ref,timestamp（带时区）。快照带水位后必须无缝补放并订阅；gap、权限变化、批次变化强制清除旧 cursor，不能把 B1 的事件累加到 B2。

## N10 与原版 QA Gate 不能混用
| R1 当前事实 | UI 展示/发布 |
|---|---|
| NodeGate PASS + N10 完结 + Evidence 合格 + 所需人审通过 | 可发起正式发布请求，仍需控制面确认 |
| PASS 但 Evidence 缺失/人审未通过 | HOLD，不发布 |
| NEEDS_REVISION 或 BLOCKED | 原状显示，不允许 PASS |
| HUMAN_GATE | 等待人工，不能自动发布 |
| DISPATCHED/RUNNING/INCONCLUSIVE | 进行中或不确定，不算 PASS |
| STALE/TRUTH_SOURCE_UNAVAILABLE | UNKNOWN/STALE，不可空成功 |
原版 QA 的 WARN 不等于 RC7.2 NodeGate PASS，历史失败 Attempt 不可被重试覆盖。

各组须在 PR #84 用源 SHA、设计字段/拒绝语义/反例表/可实现性审查、剩余异议明确签署 W0 DESIGN_SIGNOFF；**W0 禁止要求真实 DB/HTTP/Host/R1 已运行**，这些是 W1–W4 IMPLEMENTATION_QA/INTEGRATION_QA/FIELD_QA 的严格必验条件。A 不能代签 B/D/E/F；F 对整改 HEAD 设计复验前 W0_NOT_FROZEN。

## WB-FG15 设计门禁与实际实现门禁拆分（F 独立审查要求）
F 组在 PR #85 的 WB-F00-HEAD-DELTA-6EDB9FB.md 指出：旧 A03 要求 W1 实库/HTTP/现场日志才能 W0 签署，但 WB-B01 反过来依赖 W0 A03，产生施工死循环。本次从依赖图和合同中消除**W0 签署要求 W1 实现证据**，不能借此放宽真实 QA。
- `A03_CONTRACT_SIGNED` = B/D/E 分别审核并书面签署稳定身份、关系 FK/约束、业务时区待确认项、API 权限优先级、命令幂等、SSE 水位/R1 状态、负向验收预期、跨组责任；签署需指向版本 SHA，任何分歧登记为 HOLD。
- `W0_DESIGN_FROZEN` = A01 原版功能设计范围与 A03 合同由 F 独立复核接受；**不意味着工作台实际已实现、许可证获授权或银行可交付**。
- `IMPLEMENTATION_QA_PASS` = B/C/D/E 在 W1+ 提交真实数据库/API/UI/Host 运行源码、持久化失败回滚、重启恢复及正反例实测；不能用 W0 Python oracle 抵扣。
- `INTEGRATION_QA_PASS` = F 验证真实项目→批次日期→需求→系统版本→SST→Case/RC7.2 R1 Evidence 贯通且权限无串扰。
- `FIELD_QA_PASS` 与 `LICENSE_RELEASE_APPROVED` 在最终离线发布前独立核销；法务权利与 SBOM 保持 BLOCKED_LICENSE，未经许可不得复制 PolyForm 受限源码。
- 机器可检 DAG 位于 W0-W1-GATE-MANIFEST.json，由 tools/dsh_workbench/w0_dependency_gate.py 验证，拒绝 W0→W1 反向依赖、依赖环、缺失许可或现场发布门禁。该工具只静态校验依赖图，不会自动签署或解锁未获 F 批准的任务。
