# B 正式 Scope 008 物理合同候选

状态 `PHYSICAL_CONTRACT_REVIEW_REQUIRED`。基线 `800dfa37`。输入为 [V3 04ca9716](https://github.com/TongAITech/opencode-test-digital-employee/pull/188)、[E245 5be49d08](https://github.com/TongAITech/opencode-test-digital-employee/pull/245)、紧凑绑定 V1 15/4/7 及已集成的 [009 3b74d5e0](https://github.com/TongAITech/opencode-test-digital-employee/pull/244)、[009 内部 profile 7d7c3fcd](https://github.com/TongAITech/opencode-test-digital-employee/pull/255)。B 提交可逐项评审的 SQL 输入。当前仓库没有 008 表或最终锁函数。正式批次映射、请求 digest wire、权威分配器、封闭 writer、typed copy 修复和真实 Host 围栏分别待精确签署。当前 HOLD 边界继续适用。

## 1. 来源与实库基线

本轮使用已有 `MetadataPG` 可丢弃 fixture，在 PostgreSQL 17.6 + ICU 上读取 runtime 的实际目录。该 fixture 使用真实 001–007、3b74 的 009 和既有角色授权。仅用已有可选 009 空回退复核两种形状。两种均为 UTF8、块大小 8192。`project` 与 `release_batch` 的 RLS 均开启且未 FORCE。两种中 runtime 的 `project` 表级/任意列 UPDATE 均为 false，`release_batch` 表级 UPDATE 为 true，`wb.lock_scope_admission(text,text)` 不存在。base 只有 `release_batch.batch_update` permissive PUBLIC UPDATE 策略。009 另有 `project.metadata_project_update`，也是 permissive PUBLIC UPDATE。实际 base 上 v2 MATCHED_AS_OF、009 profile UNQUALIFIED，装 009 后结果相反，均保持 `admission_authorized=false`。

物理来源用 `wb.project(project_id)`、`wb.release_batch(project_id,batch_id)` 及现有项目、批次、BRV/BRVS/SST 复合键。日期版本为 `release_batch.revision`，关系版本为 `release_batch.relation_revision`，授权版本为 `project.access_scope_revision`。009 的 name、metadata_revision 和命名域治理不进入快照。当前 `acl_revision_changed` 必须更新 project 行才能完成 ACL 事务，`relation_row_changed` 必须更新 batch 行才能完成 membership/BRV/BRVS 插入。现有源身份与已验证 link 为 append-only。任何后续修改来源身份或绕过版本触发器的迁移须重新核锁证明。

B06 Preview 仅共享已验证的来源 SQL 构造和 V3 codec。正式完整选择一次包含 project/batch/date/三版本、所有覆盖计数和五类来源 tag。合法 BRV 有 BRVS 时仅产生真实 SST 边，UNSPLIT 限合法 BRV 没有 BRVS。不得用分页、标签、R1 模型输出或现有 ScopeStore 的另起事务接口组成正式快照。

## 2. 精确表、约束与审计

以下物理候选均在 `wb`。K 列顺序固定为 `(formal_authority_ref,actor_ref,project_id,creation_key)`，引用 K 的所有约束完整包含四列。所有普通列 NOT NULL，明确标为可空的除外。外键 `ON UPDATE NO ACTION ON DELETE NO ACTION`，正常写路径立即检查。新的正式/引用 ID 用 `text COLLATE "C"`，项目和批次 FK 列与现有对应列同类型及排序规则。仅批准 UTF8 且业务键确定性比较的数据库。所有 ID 不 trim、normalize 或改写。数据库先拒空及超过 384 UTF8 字节的索引身份值，端口另用 V3 校验拒 Unicode 空白和非法 Unicode。PG text 不可存 NUL，边界返回明确拒绝。限制是本合同候选的存储上限，纯 codec 可解析的超长旧键并不自动获得 008 持久化资格。实库 SQL 评审必须用不可压缩多字节值证明 8 KiB B-tree 可承载最大复合键，含索引开销，超限 HOLD。摘要列 `text COLLATE "C"` 恰好 64 个 ASCII `[0-9a-f]`。时间 `timestamptz` finite，默认 `clock_timestamp()`，用于诊断。正版本 `bigint CHECK(value>0)`。数据库 schema 整数用 `smallint CHECK(value=1)`。

| 表 | 精确候选列及键 |
|---|---|
| `scope_snapshot` | `project_id,batch_id,snapshot_ref` 为 PK，`(project_id,batch_id)` FK 到 release_batch。`schema_version,canonical_bytes bytea,scope_digest,release_date date,date_revision,relation_revision,access_scope_revision,edge_count integer,created_at`。`UNIQUE(project_id,batch_id,scope_digest)` 可去重。`UNIQUE(project_id,batch_id,snapshot_ref,scope_digest)` 为 intent 完整外键目标。日期限 `0001-01-01..9999-12-31`，edge_count 1..10000，canonical_bytes 1..4194304 字节为首版候选。DB 检查 `scope_digest=encode(sha256(convert_to('dsh.scope-snapshot.v1'||chr(10),'UTF8')||canonical_bytes),'hex')`。受控端口解析、重编码、逐字段核日期版本、边数与列值，读回复验。哈希冲突且 bytes 或列不等时 HOLD。 |
| `mission_create_intent` | PK K。`batch_id,snapshot_ref,scope_digest` 组成 `(project_id,batch_id,snapshot_ref,scope_digest)` 完整 FK。另有 `selection_bytes bytea,selection_digest,request_schema_version,request_bytes bytea,request_digest,original_context_ref,mapping_schema_version,mapping_policy,mapping_ref,runtime_release_id,mission_id,binding_ref,creation_operation_ref,prepared_at`。`mapping_policy='ALLOCATE_NEW_RELEASE_V1'`。authority 内分别唯一 `mapping_ref,runtime_release_id,mission_id,binding_ref,creation_operation_ref`，同批次可多个 Mission。两组 bytes 各 1..65536，持久原规范 bytes 供冲突及恢复核验。 |
| `mission_create_receipt` | PK K，同时 FK K 到 intent。仅加 `receipt_ref,event_ref,receipt_hash,verified_at`。`UNIQUE(formal_authority_ref,receipt_ref)`、`UNIQUE(formal_authority_ref,event_ref)`，以及供 journal 完整 FK 用的 `UNIQUE(K,receipt_ref)`。原正式身份与 request_digest 从 intent 关联核对。`receipt_hash` 来自已审原权威回执字节协议，由适配器核 K、digest、operation 和所有预留身份后追加。 |
| `mission_create_journal` | PK `(K,journal_seq bigint GENERATED ALWAYS AS IDENTITY)`，FK K 到 intent。`journal_event_ref,phase,observed_result,attempt_ref,receipt_ref,observed_at`，仅 attempt_ref 和 receipt_ref 可空。`UNIQUE(K,journal_event_ref)` 给相同诊断写重试，`FK(K,receipt_ref)` 到 receipt，空引用允许。sequence 可有空隙，也不表明提交顺序或正式事件序号。 |

Journal 允许的 phase/result 对为 PREPARE/PERSISTED，SUBMIT/PROVED_PRE_APPEND_REFUSAL，SUBMIT/UNKNOWN，LOOKUP/UNKNOWN，LOOKUP/PROVED_NOT_FOUND，RECONCILE/RECEIPT_CONFLICT，RECONCILE/RECEIPT_LINKED，INITIALIZATION/HOLD_OBSERVED。RECEIPT_LINKED 必须持有效同 K receipt_ref，其余组合的 receipt_ref 为空。原权威证据不足时仅能写 UNKNOWN。attempt_ref 仅标识一次调用。阶段、观察时间和 journal 结果均不可转为 R1 的创建、运行、失败或放行状态。事务性审计以这张 append-only journal 承担，PREPARE 和回执写入各带本事务审计。原 `wb.audit` 和 `request_log` 的旧唯一域缺 authority，不能拿来给正式 K 判重。拒绝发生在 intent 存在前时走独立受控安全日志，只留必要原因和受限关联，避免通过 FK 先造 intent。008 不含通用正式动作 E03 outbox 或执行 dispatcher。

各表 ENABLE/FORCE RLS。拒绝 UPDATE/DELETE 的 append-only trigger 与拒绝 TRUNCATE 的 statement trigger 全覆盖。运行角色无表 DDL、trigger 切换、TRUNCATE、owner/代理角色成员、BYPASSRLS 或变更 replication mode 的能力。声明约束与 trigger 均纳入固定目录 profile。业务引用、键、原 bytes 与摘要在一条 durable intent 生命周期保持不变。

### K、映射及正式编解码

K 的 actor_ref 由可信 Host 主体映射为事务 `wb.principal`。V1 写入口要求审核后的映射结果与 PG actor_ref 精确相等。原 context 是受控服务引用，拒绝跨主体重包。authority 也由原服务配置选择，恢复须向同一 authority 发出。batch 放在不可变 payload，换 batch 或同 K 换请求选择为 409。不同 authority 的 K 独立，自动切换会改变权威域，须拒绝。

`selection_bytes` 是 PG 内部首次分配前的稳定选择记录。对象键为 `schema_version,formal_authority_ref,actor_ref,project_id,creation_key,batch_id,filters,mapping_policy`，filters 用 V3 规范的三个已排序数组。沿 V3 JSON 字节规则，`selection_digest=SHA256(UTF8('dsh.mission-prepare-selection.v1\n')||selection_bytes)`。同 K 复用前同时比较规范 bytes、digest 及原 context。选择记录排除实时 Scope 重读和易变 token。重试相同选择但真实 Scope 已变时保留原 intent，最终复验返回 HOLD。显式换批次、filters 或其他已签选择才判 409。正式请求 digest 由 E/D/A 另签版本化 wire，须绑定 V3 K、batch、scope_digest、mapping、mission_id、binding_ref 和永久 creation_operation_ref。`request_bytes` 保存已签的规范字节。SQL 校验必须在 wire 域、前缀及向量冻结后加入。当前纯 codec 仅有 scope digest 和 K，不能假装已有正式请求摘要或生成创建可用 intent。`U+001F` 等控制字符按 V3 字节规则保留在 bytes 中，传到 text 标识域按本合同上限校验。

E245 另提议由同一创建事件描述 `runtime_release_batch_id`，并验证其与 Mission、运行 release 的正式三元组。它是待另签的物理字段和唯一域 `(formal_authority_ref,runtime_release_batch_id)`。可在冻结 008 SQL 前纳入同一 intent，或以随后显式依赖 008 的不可变一对一 reservation 表按 K 完整外键纳入，选择须另审。无论选择，权威须在同一次 durable PREPARE 预留并绑定正式摘要。两种配置的生产创建在映射字段、digest 和正式事件协议核准前均 HOLD。核心候选保留原紧凑 mapping 的七键，PG `batch_id` 和 `runtime_release_id` 不能冒充正式 `runtime_release_batch_id`。历史无描述数据维持未解析。

[D263 实际源码与临时 R1 探针 4587b0c1](https://github.com/TongAITech/opencode-test-digital-employee/pull/263) 显示 `CanonicalRC72Repository.persist` 可用同一 runtime batch ID 写入 v2 并更换 Mission/release。冷投影只返回一个已漂移的当前行。正式 reader 必须核原始 creation 事件唯一、绑定及映射逐字段一致、相关 canonical Batch 全历史三元组稳定，即使更换后改回也拒绝。008 保存三个独立身份的预留及永久 operation 和原回执引用。映射成立以原权威事件与经核的完整历史为准。

## 3. 权限和锁端口

迁移/表 owner 与应用执行隔离。物理角色名在部署清单固定，下列是职责。所有服务池使用独立受控连接。不可由用户指定 role、principal、scope SQL 或可信 receipt。

| 职责 | 受控范围 |
|---|---|
| 普通 WB runtime | 保持既有权限。无 008 表访问或新增函数 EXECUTE。既有 ScopeStore、preview、B06 仍走原 IDLE/RR READ ONLY 接口。 |
| PREPARE 服务与执行端 | 经审批的服务入口执行内部 `prepare` 事务。执行端只 SELECT/INSERT snapshot、intent 与 PREPARE journal 所需列，按原 actor 和当前 `can_write`。完整来源查询使用白名单来源和 RLS。不能 INSERT receipt 或更新预留身份。 |
| 最终 admission 服务 | 独立服务入口持当前 Host 原主体与 create 许可。读取原 intent 及完整 Scope，执行专用锁函数。无 INSERT snapshot/intent 或任意源表 UPDATE。 |
| receipt 校验/lookup 服务 | 按当前许可、原 actor/context 和同一 authority 查询原结果。校验适配端仅 INSERT receipt/受限 journal。普通原主体查询需当前 `can_write`。异 K、同 K 异 digest、未核 authority、权限撤销均不泄漏回执。原回执只读不暗转 submit。 |
| 行政维护 | 停写迁移与备份对账。若需全表只读断言，显式专用角色与 FORCE RLS 策略，只能由受审维护入口执行并留审计。普通 Host/session 不获得此权限。 |

每张 008 表的角色策略、GRANT 和函数依赖必须列在实现 PR。snapshot 共享同 project/batch/digest 的规范记录，只供受控端读；其策略使用当前项目 can_write。intent、receipt、journal 使用原 `actor_ref=wb.principal` 且 `wb.allowed(project_id,true)`，写检查匹配服务职责与 stage。若将来需要不具当前权限的后台对账，另签 authority 委托角色。当前撤权时只能保留未对账状态并交正式 authority 管理，服务不切换 Bob、migration owner 或 Captain 来补行。 正常回执追加经受控适配入口在已持锁的最终连接完成，端口只接原权威可查证结果。适配入口的发行者认证和 SQL 授权必须在实现审查证明，任何自报 verified、缺权限或失败均进入按原权威对账的分支。

候选 `wb.lock_scope_admission(project,batch)` 为 `VOLATILE SECURITY DEFINER`，固定 `search_path=pg_catalog,wb`，无动态 SQL。owner 专用 NOLOGIN/NOINHERIT、无成员边、无登录、BYPASS、replication 或表所有权。只授这个 owner 锁所需 `SELECT` 及 `UPDATE(project.access_scope_revision)`、`UPDATE(release_batch.relation_revision)` 列权限。SELECT 行锁在真实 PG 需要至少一个 UPDATE 列权限，已在 009 fixture 验证。只给 admission 服务 EXECUTE，撤 PUBLIC 和普通 runtime。PG 008 实库必须证明该权限组合只允许锁行，任何对这些列的实际 UPDATE 失败。

对锁 owner 的两个表新增角色专属 permissive UPDATE `USING(wb.allowed(project_id,true))` 与 **restrictive** UPDATE `USING(wb.allowed(project_id,true)) WITH CHECK(false)`。SELECT 仍走既有可读 RLS。单独的 permissive `WITH CHECK(false)` 会与 base `batch_update`、009 `metadata_project_update` 做 OR，不能约束实际 UPDATE。限制策略仅针对专用锁 owner，旧角色和 009 executor 继续各自既有策略。若实库发现行锁也被限制策略拒绝，保持 HOLD，重新审最小授权机制，不能通过宽授权限解决。

锁函数先核已映射 principal 和当前 can_write，按 project→release_batch 锁指定行。物理候选采用 **FOR NO KEY UPDATE**，与 V3 文本 FOR UPDATE 的差异须显式签署。该模式与旧 request/audit FK 的 KEY SHARE 兼容，同时与项目 ACL 更新、批次日期更新和关系版本更新冲突。009 已有同类 project 锁与旧资产/批次 claim 并发实库证据。该证据不能替代 008 锁函数实证。拿到两行锁后再查当前权限、身份、日期和三版本，避免用拿锁前快照。专用角色禁止改 key，相关 DDL 和源身份变动由另签配置围栏控制。其他路径因 FK、后台维护或锁序可能死锁，明确做两连接失败/回收测试。

## 4. Durable PREPARE 与最终事务

PREPARE 自持 IDLE autocommit 连接和 READ COMMITTED READ WRITE 事务。按原权限验证可信主体、mutation、context、`mission.create` 和 `can_write`。原 K 先取事务级 claim lock，候选用固定命名域与 K 规范 bytes 的哈希组成两参数 PG advisory xact lock。哈希碰撞只增加等待，不能代替完整 K PK。锁后用新语句读原 intent 以看见已提交竞争者。已有原 intent 先比选择 bytes/原 context，不重复分配。同 K 仅一个受控 PREPARE 写入口。完成选择所需的范围数据、epoch、完整来源和 can_write 由同一条 SQL 语句的快照捕获，超预算拒绝。commit 前再核当前 ACL 和 RLS INSERT。后续真正创建依赖最终锁内新鲜度与权限复验。

原 K 确无 durable intent 时，原 authority 的分配器才可取 reservation。分配器按 K 及稳定选择/Scope 摘要持久幂等，返回原 operation/mission/runtime release/binding/mapping 等预留身份。分配器 timeout 后先查原 authority 的 reservation。若外部分配已发生而 PG PREPARE 失败，重试须验证完全相同的预留身份和原 Scope，恢复不到原快照则 HOLD。不能借 PG 无行假定 authority 没有分配，也不能在新 Scope 下沿用旧预留。外部调用有硬期限，PREPARE 期间不持最终源行锁，不等待模型、人或任务。预留身份与 snapshot、intent、PREPARE journal 同一 PG 事务持久提交。使用同步持久化设置并等明确 commit 结果，主从提升后仍须有批准的持久性/查证语义。提交响应未知按原 K 查 PG，未确认 durable 原意图前禁止调用正式 append。

最终顺序为 `原 authority 排他 writer → 已批准目录/角色变更围栏 → 独占 IDLE PG 连接 → project 行锁 → batch 行锁 → 原 intent 与完整来源重读 → HostAdmissionFence → R1 最新重读/CAS/单事件 durable append → 校验及登记 PG 回执 → 结束 PG 事务`。独立 READ COMMITTED READ WRITE，设置 `SET LOCAL wb.principal`，不嵌套调用 `_scope`、`ScopeStore` 或 RR READ ONLY profile 的 public probe。若需锁内目录复核，提取纯目录查询并在已审围栏下执行。单次 profile 匹配描述观察时点，不能替代禁止 DDL/GRANT/角色变更穿越临界区的权威围栏。权限撤销、Scope/版本/摘要变化或配置漂移即拒绝/HOLD。锁内重编码需精确比 PREPARE canonical_bytes、digest、日期和三版本。最终事务只读核 durable intent，可追加已校验原 receipt 与 journal，不首次 PREPARE 或换预留。

候选 `lock_timeout=2s`、`statement_timeout=5s`、`idle_in_transaction_session_timeout=10s`，整个提交临界区最多 5s。外部 authority/Host 回调使用剩余绝对期限，开始前无法保证期限就不调用。跨库期间 PG 后端异常退出可能先释放行锁。最后一次 ping 或客户端计时无法证明 PG 锁活到了 R1 durable append。D/E/B 必须在生产准入前证明真实运行拓扑的保护时序，并测试 PG backend kill、断线、撤权与 append 交错。若无法证明完整时序，生产保持 HOLD。发现锁丢失且可能已 append 时按未知对账，保存正式证据并隔离状态，不能声称事务回滚撤回 R1。

## 5. 跨库未知与原回执

| 切点 | 恢复与可验证事实 |
|---|---|
| PG PREPARE 未确认 | 按原 K 查 PG durable intent 及原 authority reservation。PG 不可查则 HOLD。确认无 intent、无正式调用才可同 K 重新 PREPARE，继续同一原 reservation。 |
| PREPARE 已提交，最终锁失败 | 原 intent、snapshot、身份和摘要保留。按原 K/digest 在原 writer 域 lookup，当前权限和所有锁须重新获取。 |
| Host 可证明未 append 拒绝/过期 | 保留原 intent 与诊断。原权威证明 NOT_FOUND 后仅明确重新 submit 才可再取全套创建许可。 |
| 55P03/40P01/40001/57014、连接断开、未知 Host、尾部损坏 | 中止 PG 当前事务，禁止自动重放 append。查原 authority/K/digest。UNKNOWN 和不可证明零副作用的 CAPABILITY_UNAVAILABLE 持续 HOLD。 |
| 正式事件已 durable，PG 写回执失败或回包丢失 | 从原权威核唯一 K/digest、永久 operation 及所有 ID，再 INSERT 原回执引用与审计。已有同 K 逐字段一致则复用，异值或其他 K 占正式 ref 则 HOLD 并留冲突证据。保留 R1 原事件。 |
| 原事件有据，图初始化部分完成 | 返回原 Mission/receipt 和 INITIALIZATION_HOLD。正式 writer 按既有确定性 ID 补缺，冲突停止。PG receipt 不代表图完成。 |

实际跨库证据是单列退出条件。需要真实 PG、两个正式 writer 进程、原权威持久事件与经审 Host fixture，对 PREPARE commit 回包丢失、PG kill 前后、Host 撤权前后、正式 append 后 PG 故障和 writer 冷恢复逐点验证。通过 PG 与纯 codec 测试不能抵扣。当前 E typed copy 缺陷修复及其同源独立结果继续等待。

## 6. 迁移组合和回退

008 与 009 独立依赖 001–007，均采用显式节点。当前 009 runner 会拒绝已应用 008，原 prefix runner 只认识 1..7。不能用两个旧 runner 假装已支持组合。物理实现须另审统一显式 graph，固定源码哈希、实际 applied 节点及角色模板，采用既有 PG 迁移 advisory lock `684091210`。两种安装顺序分别跑实库，核最终目录一致和依赖叶子回退。组合清单不能跳已应用校验、伪造空节点或以最大版本推断前缀。

| 已应用集合 | 当前批准 profile 或所需新批准 |
|---|---|
| 001–007 | 现 v2 原模板 |
| 001–007 + 009 | 已接受显式 009 目录观察，仍无 admission |
| 001–007 + 008 | 需新固定模板，新增 FK、RI、角色及策略均参与 |
| 001–007 + 008 + 009 | 需独立组合模板及排序/授权实证，不沿用两个单扩展结果 |

停入口、停正式 writer、证实无未决 append 并持部署维护围栏后，空 008 可按依赖叶子回退。用同一 DDL 事务获得相关表排他锁并在具有全表可见性的受审维护角色下检查四表，避免 FORCE RLS 把隐藏行算成空。严格拒绝任何有 snapshot/intent/receipt/journal 或原权威引用、未决状态的破坏性 down。停写导出全 K、摘要、复合引用、来源哈希及权威回执对账，再审保留数据的 forward 修复。禁止 CASCADE、checksum 改写或删除 R1/Evidence。撤销 008 专用授予，009 及其治理历史按原独立约束维护。

SQL 实施工单的评审退出包含真实新迁移两顺序及空 down/up、非空/UNKNOWN down 拒绝、超长复合键和跨项目/authority FK 拒绝、append-only/FORCE RLS 与维护空检查、角色确实可锁却不能更新、ACL 和关系提交先后、原 PG 同 K 并发和有/无 009 兼容。实际正式映射、跨库时序与 Host 资格由后续联合工单完成。本文的实库数据仅为已有 schema 和权限观察，不把尚无的 008 SQL 或正式运行路径计作通过。
