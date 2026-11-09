# 工作台 API / 事件契约草案
状态：W0 设计草案；以下接口为待实现，非现有可用 API

## 查询 API
GET /api/workbench/v1/projects/{project_id}/release-dates
GET /api/workbench/v1/projects/{project_id}/release-dates/{yyyy-mm-dd}/scope
GET /api/workbench/v1/projects/{project_id}/release-dates/{yyyy-mm-dd}/quality
GET /api/workbench/v1/missions/{mission_id}/graph
GET /api/workbench/v1/missions/{mission_id}/workitems
GET /api/workbench/v1/attempts/{attempt_id}/evidence
GET /api/workbench/v1/capabilities
GET /api/workbench/v1/events（SSE）

## 受控命令
POST /api/workbench/v1/missions/{mission_id}/commands
命令需要 command_id/idempotency_key、expected_state_revision、principal/authorization、scope_ref、action、reason；服务端校验合法状态转移、权限、资源及人工门禁，并给出 accepted/rejected/revision_conflict 和正式 command_ref。
禁止绕过 RC7.2 控制面直接变更 R1 事件或 NodeGate。

## Scope 查询契约
每个业务查询必须包含 project_id 和 batch_id 或经 project_id+release_date 解析得到稳定 batch_id；需求/版本/SST 筛选传 ID 数组、按关联表校验，不能做简单字符串联想查询。
结果返回 scope、source_refs、truth_revision、as_of、records、pagination、warnings、gap_indicators；R1 真相缺失时返回缺口/未就绪，不返回空成功。

## 事件
mission.updated、workitem.updated、attempt.created、evidence.verified、nodegate.updated、batch.scope_changed、human_gate.requested、data.source_unavailable。
事件必须带 event_id、revision、project_id、batch_id、mission_id?、timestamp；前端按 revision 去重和恢复，断线后先拉最新快照再订阅。

## 典型错误
400 INVALID_SCOPE / VALIDATION_ERROR；403 FORBIDDEN；404 RESOURCE_NOT_FOUND；409 STATE_REVISION_CONFLICT / GATE_BLOCKED；422 ILLEGAL_ASSOCIATION；503 TRUTH_SOURCE_UNAVAILABLE。中文面向用户提示，保留可检索的英文错误码。

## WB-A03 v0.2 补充 — 未签收的安全与真相边界
**现状盘点：** 本仓库 rc7_admin/server.py 现有 /api/health、/api/meta、/api/missions/{id}/overview 或 detail、通用资源列表、用例写入及修订；product_server.py 增 /api/requirement-hierarchy。并不存在拟议 /api/workbench/v1 完整入口。新接口不得与旧查询路径混为已实现。

1. **Scope 与 ACL：** 服务端依据已认证宿主主体验证项目权限；投产日期必须按银行业务日 yyyy-MM-dd 解析稳定 batch_id，不通过 UTC 时间戳制造一天偏移。需求/系统版本/SST 必须来自真实复合关系表，不能根据名称或两个合法 ID 集合做笛卡尔组合。未拆分 SST 返回待拆分。跨项目 403、关联非法 422、无资源 404、R1 不可用 503，不得返回空成功假象。分页游标绑定主体、Scope、关联版本、truth_revision；增加 access_scope_revision。
2. **命令权威：** 客户端只能提交 command_id、idempotency_key、expected_state_revision、scope_ref、action、reason。原草案写的 principal/authorization 是服务端验证所得上下文，**不得从请求体信任这两个字段**。暂定候选动作 pause、resume、retry_failed、request_human_gate，UI 不提供 publish/任意 NodeGate PASS/直接修改 R1。按 (principal, project, idempotency_key) 原子落库，重复同负载返回原 command_ref、同键不同负载 409；授权、状态机合法边、Worker/Browser 资源租约及 Human Gate 必须真实受控。
3. **事件与续传：** 每事件包含 event_id、type、revision、project_id、batch_id、timestamp(时区明确)、source_ref、truth_revision，按需 mission_id。事件流 revision 与 R1 全局 truth_revision 独立。相同 event_id 原内容重播去重，变内容冲突；revision 缺号不得继续显示假实时。冷恢复要获取带水位的快照，再从水位可靠补放/订阅，保证快照与订阅间不丢事件；切换项目/批次必须丢弃旧订阅并重新授权。
4. **关系和迁移：** 新增 BatchRequirement、BatchSystemVersion、BatchRequirementVersion、BatchRequirementVersionSST 的复合键/复合外键/来源修订，避免不同系统同 version_label 和跨批次同 SST 污染；变更投产日期要保留稳定 batch_id 及历史。迁移可逆并核对历史分母；不更改 RC7.2 原始 R1 Event/Case/Attempt/Evidence。破坏性字段改动须另升 API 版本。
5. **Evidence 与结果：** 命令 accepted、Agent 派发、截图、服务端 API 返回 200 不等于 PASS；以独立有效 Attempt、Oracle、Evidence、NodeGate 为准。重试保留旧失败和新签名 Attempt，无法判断副作用的执行必须 HOLD。

工程负向 oracle：tools/dsh_workbench/w0_contract_gate.py + tests/test_dsh_workbench_w0.py 覆盖 T1–T10、未授权/伪主体、版本冲突、禁用发布、事件水位缺口、非商业许可证拦截。**它不是 HTTP 实现、数据库迁移、真实 SSE 或幂等落库验收。** B/D/E/F 尚未签署此合同，A03 只能保持 IN_PROGRESS。

## WB-A03 v0.3：待签收的授权、命令、SSE 与 R1 真相
- 真实端点授权矩阵和角色签署表见 [WB-A03-CROSS-GROUP-SIGNOFF.md](WB-A03-CROSS-GROUP-SIGNOFF.md)；拟议 /api/workbench/v1 仍不存在。
- 授权先行：项目不可读 403 且不泄露对象存在性；授权后无资源 404、非法真实关联 422、命令/修订冲突 409、R1 truth 不可用 503。错误不可修改关系、Attempt、R1。
- 命令主体来源由 DSH 宿主/服务端提供，拒绝客户端自报。服务端把 principal、project_id、mission_id、scope_ref、expected_state_revision、idempotency_key 联合授权及原子持久化；相同键同 payload 返回原 command_ref，不同 payload 409；未批准的 publish/NodeGate override 禁止。
- SSE 的订阅身份和水位至少绑定 project_id、batch_id、access_scope_revision；事件要有 source_ref、truth_revision（区别于流 revision）和带时区时间。切换同项目批次也须取消旧流、重授权及丢弃旧 cursor；快照-补放-订阅必须无缝，event gap 不得伪实时。
- UI 发布不是拖卡片结果：NodeGate PASS 且 N10 完成、Evidence 合格、所需人审通过方可放行；NEEDS_REVISION/BLOCKED/HUMAN_GATE、未结束、过期或无真相一律不可 PASS；原 QA 的 WARN 不等于 NodeGate PASS。
- Python 契约 oracle 的事件与命令校验仅用于设计期测试，不证明真实 HTTP、R1、持久事务或 SSE 已实现。

## WB-B-A03 Scope 服务边界附录（W0，仅设计）
详见 [WB-B-A03-DESIGN-SIGNOFF.md](WB-B-A03-DESIGN-SIGNOFF.md)。B06 仅返回授权 project+batch 的真实 BRV LEFT JOIN BRVS 关联，含 UNSPLIT、来源、relation_revision、access_scope_revision、稳定游标；多选只筛真实连边，不生成笛卡尔积。服务端可信 principal 权限先判 403；授权后资源不存在 404，非法来源或跨批次关联 422，修订/日期冲突/过期游标 409，真相源不可用 503。游标绑定 principal+project+batch+filter+revision；切批次、权限或关系版本必须重查。E 的命令/SSE/R1 及 D 的宿主身份仍需各自设计签署，B 不代签。

### WB-B A03 双重来源校验
Scope 的 BRV 不只是 BR 与 BV 均在批次内，**还必须有 authoritative requirement-version link**；SST 另外校验该 requirement-version 的 source_verified_link。没有来源可信连边则拒绝 422，不得把两个合法 filter ID 的笛卡尔组合视作已授权实体。该校验对写入和查询都不可绕过。

<!-- A integration: B source 704c86a; FG18 witness corrected in tests; B reconfirmation pending. -->
