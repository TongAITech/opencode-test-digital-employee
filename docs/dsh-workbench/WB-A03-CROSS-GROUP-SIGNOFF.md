# WB-A03 W0 业务/API/事件跨组签收候选
状态：A_RECONCILED_CANDIDATE / B_DESIGN_SIGNOFF_RECONFIRMED / D_DESIGN_SIGNOFF_ISSUED / E_DESIGN_SIGNOFF_WITH_IMPLEMENTATION_HOLDS / F_RECHECK_REQUIRED。各组仅签 W0 设计合同；B FG18 来源约束已获 F 设计反例复核，B #95 已对新集成领域语义差量复签；后续联合 SHA 仍待 F 审查；真实产品 QA 尚未执行。
参照 F 组 PR #85 的 FG02–05、FG10、FG13；W0 Python 合同测试只验证内存 oracle。

| 组 | 签署范围 | 必须带回的可复核证据 | 结论 |
|---|---|---|---|
| B | Batch 日期唯一/改期、复合 FK、SST 来源、事务与迁移方案、Scope 真 join | W0：审查 [B DESIGN_SIGNOFF](WB-B-A03-DESIGN-SIGNOFF.md)、跨版本原始 SST ID 的版本限定 UNIQUE 及 T1–T8 反例；W1：真实 PostgreSQL/422 回滚/重启验收 | B_DESIGN_SIGNOFF_RECONFIRMED / FG18_DESIGN_RECHECK_PASS / W1_IMPLEMENTATION_QA_NOT_RUN |
| D | DSH1.18.26 认证主体/原生会话、命令技能附件、权限和断线恢复 | W0：[D DESIGN_SIGNOFF](WB-D00-DESIGN-SIGNOFF-AND-D01-HOST-DELTA.md)，可信主体、PROJECT/BATCH_COMMAND/WORKER 三会话、host 失败语义；W1+：行内真实会话/并发/恢复另验 | D_SIGNOFF_ISSUED / FIELD_QA_NOT_RUN |
| E | R1 只读真相/NodeGate、命令幂等/人审、batch SSE/恢复 | W0：[E DESIGN_SIGNOFF](WB-E-A03-DESIGN-SIGNOFF.md)，明确旧 /api/workbench/v1 不存在与六项实现 HOLD；W1+：真实 API/Evidence/持久幂等/SSE 另验 | E_SIGNOFF_ACCEPTED_WITH_IMPLEMENTATION_HOLDS / IMPLEMENTATION_QA_NOT_RUN |
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

## A 组真实跨组签收集成基线（2026-11-09）
- 精确来源 B PR #89 HEAD `704c86aaf9b2c5a9b9b4088648ccd0c50204f2f8`、C PR #92 HEAD `e9094bf5267ebc840ffae6bf3e8a707380ecaf7f`、D PR #90 HEAD `f0b7faeb22f9bf03d2487061a8f81a2776a5213d`、E PR #91 HEAD `bee612b2dd94a6040404db4b9a4a5fd816e136dd`；F 独立审查见 PR #85。
- B 原签署的 sst 源键 UNIQUE 用了全项目作用域，F FG18 已证明与同原始 source_key 在多系统版本合法复用冲突。A 本次仅修复 **设计见证 SQL** 为 UNIQUE(project_id,version_id,source_system,source_key) 并保留版本限定来源身份；必须由 B 对新合同重新确认且 F 独立负向复验。
- B/D/E 旧分支签署覆盖本行声明的既有语义，但最新联合集成 SOURCE SHA 与 A03 变更，仍需各组验证不丢信息。F W0 设计 ACCEPTED 与商业法务签署均未获得；W0 NOT_FROZEN、A02 BLOCKED_LICENSE。

## FG18 正式 B 组修订来源（待 F 核销）
B 组最新 PR #89 HEAD `98bac426a35063a306f4eaa4b43c80cf0a0a1745` 已新增 sst stable internal ID、version-scoped source uniqueness 和 source_trace(源 namespace/revision/ref)。此段只接受 B 更新后的 W0 设计合同进入 A 集成，不能用 SQLite 内存 SQL 代替 W1 PostgreSQL/真实合法来源导入。E/D 的签署须以联合源 SHA 复核含义是否保持。


## 2026-11-10 A03 B/C/E 差量签收与 F 最新审核
- B 组 PR #95 @ `67c4fc592f290710d6242aef2d4144000e7d82fd` 已正式复签 **B_DESIGN_SIGNOFF_RECONFIRMED=ACCEPTED**，仅涵盖 B 领域关系、B01/B02 日期审计/系统身份 W0 witness、B06 分页/来源 payload 与拒绝语义；见 [B 差量签署](WB-B-A03-INTEGRATED-DELTA-REVIEW-75FD2C6.md)。这不是 A 替 B 签字，也不是 PostgreSQL 迁移完成。
- B06 专属 API shape 见 [06 合同](06-API-AND-EVENT-CONTRACT.md)：服务端 DSH Host 派生 principal，B06 不接受调用者自报主体/Mission allow-list；source_refs 为每页去重的 BRV/SPLIT 来源引用，records 返回真实关联及 UNSPLIT，响应顶层 next_page_cursor=null 才是最后页。E #96 仅消费 B06 合同并在 R1 读取后验证 Mission 显式 project_id/batch_id，不通过源名称猜测映射。
- C PR #97 原创 W0 原型新增多选 Scope/十区表单负向交互；只有 W0 原型级真实 Chromium 与 Node 20/20 证据，非 C01/C02/F02 实现资格。
- F PR #101 @ A `b385e042` 接受 FG18 设计与 FG17/R4 targeted，发现 **FG22 W0 CI 失败**；A 修复提交 `5bba94c` 后仍需用新同 SHA CI 和 F 独立重检。
- D DESIGN_SIGNOFF 既有附件不替代 DSH1.18.26 实际宿主 qualification；E DESIGN_SIGNOFF_WITH_IMPLEMENTATION_HOLDS 不等于 E01/R1/HTTP 已实现。FG21 Git source merge 已解，PR #84 CI=unstable 时禁止主线合并。
- **退出门槛不变：F 独立 W0 DESIGN_ACCEPTED 尚缺、W0_NOT_FROZEN、A02 BLOCKED_LICENSE、W1–W4 FIELD/IMPLEMENTATION_QA_NOT_RUN。**


## 2026-11-10 A 最终 B/C/E W0 差量集成签署附件（不可代签 F）
- B 组最新设计签署源 #95 `50bd16d9e2c321eb5eaa21e96f663e89ae377b34`；原 B_DESIGN_SIGNOFF_RECONFIRMED 仅对领域 W0 合同成立。新增 `authoritative_link(project,version,sst)` 经 sst_source_trace 复合来源 FK、反跨版本 raw SST ID 错配/空白来源，SQLite 设计见证，PostgreSQL B01/B02/B06 正式实现未开始。
- E 组新 #102 `26b2deaf5485193133e418da81982291c8056d64` B06 全分页请求 page_cursor、顶层 next_page_cursor；所有页授权和 project+batch/revisions/source_refs 恒等才允许读取 R1，E 不接收自报 principal。E 的 W0 协议反例可进入联合 CI，E01 真实 R1/HTTP/持久化未通过。
- C 组 #97 `b2a64df65661880808510d0486f6aefc70ca23df` 新原创 SourceReadFence/30 Node 反例只展示只读模拟 Scope，不得自动让 NodeGate/人审 PASS。F #104 FG23 旧联合树失败、新 C 已删除 Chromium CI 08/09/10 PR 路径，待本次 A 同 SHA 合同/F 独立复验。
- 最新 F 已审查但尚未签署当前 A 集成树，`W0_DESIGN_ACCEPTED=NO`；F02/F03/F04、A02 商业权限与独立产品现场认证另为严格门禁；`W0_NOT_FROZEN / BLOCKED_LICENSE / W1–W4_NOT_RUN`。

## 2026-11-10 B108/E107 来源合同新复签事项（不能代替 F 的 E P1 审核）
- B [#108](https://github.com/TongAITech/opencode-test-digital-employee/pull/108) 源 `b801c25bbec361e6a791c561d5a7dd0ec9440aaf`：F #111 接受 `B108_W0_DESIGN_WITNESS_PASS`，规定 B06 的 SPLIT/UNSPLIT 必须根据 verified BRV↔BRVS 关系和一致性快照计算，而不是引用可变标签；来源修订不可被静默 UPDATE/DELETE，合法纠正/退役需来源 supersession+审计。SQLite W0 是见证不是 PostgreSQL。
- E [#107](https://github.com/TongAITech/opencode-test-digital-employee/pull/107) 旧源 `917f597`：F #111 指出 Mission Scope 检查之前已读取关联任务与 Evidence 的 P1；新源 `a04933fbe7b651c10b589b90cade5da65bdd8b81` 改为强制 `AdminProjection.mission_overview_scoped(project_id,batch_id,mission_id)`。先唯一 Mission 身份查询及显式 project/batch 校验，匹配后才读 details；缺绑定、跨项目/批次时关联明细零查询，老 mission_id-only API 绝不可 fallback。**E 新修复仅具备提交与同 E HEAD CI，F 最新安全签署仍待**。
- A03 新增“先权限、后数据”的读取时序边界；正式 Host-derived principal/真实 Postgres/R1 ACL/重启与权限撤销 QA 在 W1+ 执行。F 原 P1 提醒不是实际线上接口已暴露证据；但不能放行预适配器生产使用。
- A02 `BLOCKED_LICENSE` 不变，W0 `NOT_FROZEN`；B01/B02/E01 真产品 `QA_NOT_RUN`；A 不代签 F。
