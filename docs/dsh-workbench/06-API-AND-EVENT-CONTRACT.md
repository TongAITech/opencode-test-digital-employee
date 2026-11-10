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


## WB-FG18 跨系统版本 SST 原始来源 ID 复用语义

同一 raw source_object_id 在不同 system_version_id 下可对应独立内部 sst_id，接口返回稳定内部身份以及版本限定的原始 source_ref、source_revision。Scope 及关系写入必须校验 project、batch、requirement、system_version、sst_id、source_verified_link 完整链路；误把 raw ID 相同当作关联即 422，且本事务不能有部分副作用。来源唯一约束不再是全项目的 raw ID 唯一。正式 API/真实来源审计仍属 W1+。


## B06 专属 Scope 响应契约（覆盖本文件通用 pagination 描述）

本节仅约束 B 组 GET /api/workbench/v1/projects/{project_id}/release-dates/{yyyy-mm-dd}/scope；该接口的响应不采用上文泛化的外层 pagination envelope，也不返回 R1 truth 字段。

**请求：** DSH Host middleware 从已认证宿主会话派生 principal 并绑定到服务端 request context；principal 不是 query/body 字段，也不是 E adapter 可自报/传入的参数。业务查询参数为 project_id；batch_id 或 project_id+release_date；可选 requirement_ids[]、system_version_ids[]、sst_ids[]；page_size、page_cursor。B06 不接受 mission_id，也不维护 authorized_mission_ids。

**响应固定字段：**
- project_id、batch_id、release_date、relation_revision、access_scope_revision；
- source_refs：去重后的非空字符串数组，必须覆盖本页每条 BRV 的 source_verified_requirement_version.source_link_ref，以及每条 SPLIT SST 的 source_verified_link.source_link_ref；
- records：真实 BRV LEFT JOIN BRVS 记录；每行包含 requirement_id、system_version_id、split_state、sst_id，以及 source_verified_requirement_version 来源对象；SPLIT 行另含 source_verified_link 来源对象；UNSPLIT 行 sst_id=null 且 source_verified_link=null；
- warnings、gap_indicators：始终为数组，无内容时为空数组；
- next_page_cursor：**固定顶层字段且必须存在**；null 表示最后一页，非 null 表示仍有后续页。

B06 不返回外层 pagination object，不同时返回 cursor/page_cursor 两种响应字段。请求游标名为 page_cursor，响应游标名为 next_page_cursor。游标必须绑定服务端 principal、project、batch、过滤集合、relation_revision、access_scope_revision 和稳定排序位置；若真实查询依赖 R1，则另绑定对应 truth_revision。关联/权限修订后返回 409 STALE_CURSOR，要求从新快照重新查询。只有消费完所有页直到 next_page_cursor=null 才能宣称 Scope 完整。

B06 的 source_refs 只表示 B 领域的权威关系来源。B06 不生成 truth_revision 或 as_of；E 在读取 R1 后负责补充 R1 的 truth_revision/as_of 和 R1 source ref。B06 只授权 project+batch+relation query，不负责 Mission allow-list；E 必须在 R1 读取后验证 Mission 显式 project_id、batch_id 与 B06 Scope 完全一致，缺失/不匹配均 HOLD，不得从 release_id、名称或版本标签推断 batch_id。

上述是 W0 API 设计契约，当前 /api/workbench/v1 尚不存在；真实 PostgreSQL、HTTP ACL、游标持久性、跨页快照一致性、403/404/409/422/503 仍须 W1+ 实施验证。



## PostgreSQL 正式业务库增量决策（待 B/E/D 与 F 精确源审查）
正式工作台业务数据库采用 PostgreSQL；SQLite 设计见证不能替代真实 PostgreSQL 验收。Redis 仅用于缓存、临时状态和协调，丢失后必须从权威存储恢复。

项目、投产日期、需求、系统、系统版本、SST、BR/BV/BRV/BRVS、测试用例、缺陷、里程碑、报告、知识、会议纪要及审计记录持久化至工作台独立 schema。所有项目内实体及关联以 project_id 参与复合主外键，BRV/BRVS 必须引用权威来源连边；禁止按显示名称连接。投产日期以 DATE 保存，稳定 batch_id 改期不变并记录历史。已有来源见证不可静默覆盖或删除。

业务写入在一个 PostgreSQL 事务内完成授权、expected_relation_revision 比较、关联校验、业务变更、幂等记录、审计和事务 outbox；冲突或非法关系完整回滚。运行角色不得拥有 schema/迁移权限；宿主可信主体通过服务端上下文授权，连接池每事务设置并清理身份，RLS 及 API 授权共同隔离项目，撤权后旧游标失效。审计保留主体、动作、请求ID、对象、前后修订、时间与来源，业务角色不可改写。

R1 继续是 Mission、Attempt、Evidence、NodeGate 正式运行事实来源。工作台数据库只保存业务关系与 R1 引用/投影，不直接更新这些正式事实。读取时先取最小 Mission 身份，校验 project+batch，再读关联明细；禁止 unscoped fallback。跨 PostgreSQL/R1 不假设分布式原子事务：命令以持久幂等状态、正式 command_ref 和对账恢复处理，未知副作用进入 HOLD；outbox 投递不等于 R1 已执行或 PASS。缓存与投影必须带来源修订及新鲜度，R1 不可用返回明确缺口。

证据大文件放受控文件或对象存储，数据库只保存元数据、哈希、访问控制与引用；上传暂存、哈希验证、元数据提交和孤儿清理须可恢复，不将缺文件或哈希失败视为有效证据。

迁移使用有序版本与校验和、专用迁移角色、备份及 dry-run；先核对来源映射、冲突隔离、行数和历史分母，再切换。回滚必须实测恢复旧应用与数据库兼容状态，不删除正式 R1 或已有证据；不可逆步骤须先备份并明确恢复方案，失败停止切换。

W1 验收必须在真实 PostgreSQL 执行：迁移与回滚、同需求多版本多SST、共享版本不共享SST、跨项目/批次复合FK拒绝、并发修订冲突、幂等重放/异负载、事务中断零部分写、连接池身份串用、撤权、重启、outbox重复/故障恢复、R1不可用和证据缺失。记录服务器版本、源SHA、命令、日志与数据Oracle；当前均 NOT_RUN。

本增量状态 PG_INCREMENT_REVIEW_PENDING；历史 B/D/E 设计签署不覆盖本增量，须分别绑定完整提交 SHA 提供意见；F 接受最新设计 HEAD 前禁止 W0_DESIGN_FROZEN。

## B07 草稿资产CRUD增量候选
新增`projects/{project_id}/batches/{batch_id}/assets`及版本CAS、幂等、退役/恢复、日历同源里程碑查询合同，详见[WB-B07-DRAFT-ASSET-API-CONTRACT.md](WB-B07-DRAFT-ASSET-API-CONTRACT.md)。当前DESIGN_REVIEW_PENDING，尚无这些资产HTTP端点。写入需服务器Host mutation授权与CSRF边界、项目ACL；不接受客户端principal或正式R1事实字段。历史冻结设计签署不覆盖本新增接口。

## B01/B06只读目录精确增量
GET `/api/workbench/v1/projects`只列可信Host当前principal经RLS可读项目，records字段为project_id/name/access_scope_revision，不猜业务phase或质量统计。
GET `/api/workbench/v1/projects/{project_id}/release-dates`先项目授权；records字段为project_id/batch_id/release_date（DATE原值）/date_revision/relation_revision/access_scope_revision。稳定batch_id改期不变。授权空列表可records=[]；无权项目403、缺Host/DB503。均不新增项目或ACL写接口。
两端点仅接受page_size(1–100)/page_cursor，拒绝客户端principal及重复标量参数。响应schema=`dsh-workbench/business-directory/v1`，含directory_revision（当前完整可见快照SHA256）、records、顶层next_page_cursor（末页null）、warnings/gap_indicators；日期目录另含project_id/access_scope_revision。
签名cursor绑定主体、目录类型/project、page_size、完整可见项目/ACL或日期/修订指纹与位置；增授、撤权、改期、目录可见数据变化旧cursor409。每页真实PG REPEATABLE READ/RLS，无R1 fallback、无虚构统计；不改变R1权威。实现及现场资格分别独立验收，FIELD_NEEDS_BANK_TRANSFER。

## M1 项目改名协议增量（2026-11-11，尚未接入HTTP）

被审协议见[B230](WB-B-PROJECT-METADATA-M1-NAMESPACE-CANDIDATE-20261111.md)及[A决策](WB-A-PROJECT-METADATA-M1-DECISION-20261111.md)。拟议metadata GET/PATCH为已有project改名，不接纳principal/namespace/role/parent等权威字段。新metadata revision和expected revision使用规范正十进制字符串，不转JS Number；当前Host mutation、CSRF/Origin、原主体write-context、项目can_write及服务端治理状态共同约束。已提交原K同digest经当前重授权后返回原历史回执，优先于当前CAS；UI另读当前状态，不能把旧receipt回滚新name。NO_CHANGE须权威数据库判定并持久回执，纯codec不能断言。

PROJECT级outbox不得填假batch冒充BATCH事件或SSE；名称变更不触碰R1。Directory摘要须包含metadata_revision防ABA，具体项目wire兼容另审，不顺带改批次/Scope协议或清合法Scope。受审现有协议仍可只读；本增量尚无产品功能PASS。

SQL冻结前须选择兼容现request_log FK/claim的锁级或统一顺序，真实PG两连接覆盖同K metadata与既有asset/batch跨动作、ACL/治理竞态、死锁及完整回滚。当前project FOR UPDATE先于claim的反向等待是源码审查假设，未实证为现存缺陷。D/E/F设计接受不替代具体SQL/runner/profile及客户端实现精确验收。
