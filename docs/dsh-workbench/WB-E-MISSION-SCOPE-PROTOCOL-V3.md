# 正式 Mission Scope 协议 V3：可实施增量候选

状态：B_D_F_EXACT_SHA_REVIEW_REQUIRED / IMPLEMENTATION_NOT_AUTHORIZED。A 为架构集成 owner。本文件单独新增于 W0 `aa533c21c215970d4eea4760946d6d1881277afc`，参考 V2 `957874d6d24b78b6c61b243f3c952d57bc33a0b2`、B `2f6313316237240ac41290bdc4a0b4b00284ae67`、D `29df505104321e71b662e77851a736359994c1a3`；不把它们的父提交或条件性审阅当签署。全部新类型、表和端口均为待实现要求。没有修改冻结合同、008、正式模型或 R1，没有现场通过证据。

## 1. 实际来源与规范字节（B P1-1）

以当前 migrations/001–005 及 business_scope.py 为依据；source_revision/verified_source_revision 是非空 text，不是数字。顶层仅允许 schema_version、project_id、batch_id、release_date、date_revision、relation_revision、access_scope_revision、filters、edges。schema_version 固定整数 1；域名 dsh.scope-snapshot.v1。date_revision 来自 release_batch.revision（不是 B06 已有字段）；两个其他 revision 来自同名列，整数范围 1..9223372036854775807，拒绝 bool、浮点及指数表示。日期固定合法 YYYY-MM-DD。所有 ID 与来源 text 原样保留，不 trim、不归一化、不用 label 联结；拒绝空白串、未配对 surrogate、未知键、重复 JSON 键。

filters 固定 requirement_ids、version_ids、sst_ids；version_ids 显式映射现有 B06 参数 system_version_ids。每数组按 UTF-8 无符号字节序排序，重复输入拒绝；[] 表示不限。此规则只用于新创建，不改变 B06 查询的现有去重语义。edges 每行固定 requirement_id、system_id、version_id、sst_id、requirement_source、version_source、brv_source、sst_source、brvs_source；结构如下，尖括号仅是文档变量，不是可接受值：

| 来源字段/tag（kind） | 恰好允许的其余键及真实 SQL 来源 |
|---|---|
| requirement_source / REQUIREMENT_IDENTITY | source_system,source_namespace,source_object_id,source_revision,source_ref；wb.requirement 同名列 |
| version_source / SYSTEM_VERSION_IDENTITY | source_system,source_namespace,source_object_id,source_revision；wb.system_version 同名列；**无 source_ref 键** |
| brv_source / VERIFIED_REQUIREMENT_VERSION | source_link_ref,source_revision；wb.verified_requirement_version 同名列 |
| sst_source / SST_IDENTITY | source_system,source_namespace,source_object_id,source_revision,source_ref；wb.sst_identity 同名列 |
| brvs_source / VERIFIED_SST_LINK | source_link_ref,verified_source_revision；wb.verified_sst_link 同名列 |

来源身份由所在 edge 的业务键限定：requirement=(project,requirement)，version=(project,version,system)，SST=(project,version,sst)，BRV=(project,batch,requirement,version)，BRVS 加 sst；不虚构 source_system/namespace/object_id 给 link，也不把结构化 version 身份伪装成外部链接。system_id 从 system_version 的复合 FK 获得，不从标签猜。最终查询必须连结 batch_requirement_version→verified_requirement_version→batch_requirement/batch_version→requirement/system_version，以及 BRVS→verified_sst_link→sst_identity，校验所有复合键同 project/batch/version。UNSPLIT 只在该合法 BRV 没有 BRVS 时产生一行，sst_id/sst_source/brvs_source 三者为 null；有 SST 则仅实际 BRVS 行，绝不跨需求笛卡尔积。过滤 SST 时不得补虚拟 UNSPLIT 行。选择须覆盖所有请求 ID，空集/缺来源/矛盾同身份来源拒绝。

边按 (requirement_id,system_id,version_id,sst_id) 的 UTF-8 字节排序，null 在字符串之前；重复逻辑边拒绝。对象键按 ASCII 升序；UTF-8 无 BOM、空格、终止换行；非 ASCII 原字节，不转义 /；双引号编码为 \"，反斜杠为 \\；U+0008/0009/000A/000C/000D 分别固定为 \b/\t/\n/\f/\r，其他 U+0000..001F 固定小写四位 \u00xx；其他字符不转义（包括 U+007F、U+2028/2029）。整数十进制无前导零，null/true/false 为 JSON 小写，schema 内除 null 不接收布尔值。规范解析拒绝重复键后再验证和排序，不对任意原始 JSON 直接摘要。黄金字节向量：对象 {z:换行,a:中文} 的规范字节 hex 为 `7b2261223a22e4b8ade69687222c227a223a225c6e227d`；含反斜杠、双引号、U+0001 的字符串字节 hex 为 `225c5c5c225c753030303122`。后续 codec 必须固定完整快照黄金向量及跨进程结果。

scope_digest=SHA256(UTF8("dsh.scope-snapshot.v1\n")||canonical_bytes)，小写64 hex。标签、语言、时间、分页、游标不入摘要。B06 全页预览使用 next_page_cursor，不称 next_cursor；它不提供完整身份来源/date_revision，因此**不能成为最终快照来源**。最终快照由第3节独立端口一次完整构造，分页预览仅辅助 UI。预算不足不截断签名，返回 HOLD。

## 2. 显式正式域、映射与 PG 持久约束（B P1-2）

V3 选择完整 authority 域：K=(formal_authority_ref,actor_ref,project_id,creation_key)，batch_id 是不可变 payload 而非 key。同 actor/project/key 在同一 authority 下换 batch 或任何 payload 必须 409；不同 authority 是显式不同权威，不自动切换、重试或搬移旧 key。服务器保存原 authority/context，缺原权威可查询能力 HOLD。actor_ref 必须与可信 Host principal 及事务 SET LOCAL wb.principal 的已审核映射一致；V1 不接受代理主体。请求摘要域 dsh.mission-create.v1 包含 schema_version=1、K、batch_id、scope_digest、mapping、mission_id、binding_ref；排除易变 Host fence token、会话时间和 HTTP 重试编号。

mapping 固定 {schema_version:1,formal_authority_ref,project_id,batch_id,runtime_release_id,mapping_ref,mapping_policy:"ALLOCATE_NEW_RELEASE_V1"}。runtime_release_id 由该正式 authority 的受控分配器预留全新身份，mapping_ref 同时预留；它不等于 PG batch_id 的假设。PG 保存的是分配意图；R1 单个不可分割创建事件确认这个映射才成为正式事实。authority 内 UNIQUE(runtime_release_id)，禁止与其他批次复用；同批次可有多个新 release/Mission。旧 release 的复用另案，不猜名称、日期或 release_id 映射。

拟议008须 B 另审 SQL，不在本 PR 实施：

| 表 | 最小不可变列、键与限制 |
|---|---|
| scope_snapshot | PK(project_id,batch_id,snapshot_ref)；FK(project_id,batch_id)→release_batch；UNIQUE(project_id,batch_id,scope_digest)；schema_version=1、canonical_bytes bytea、scope_digest、release_date、date_revision/relation_revision/access_scope_revision、edge_count；digest校验及 bytes 重编码比对由受控写端校验，不仅 jsonb |
| mission_create_intent | PK K；batch_id,snapshot_ref,scope_digest,request_digest,mapping_ref,runtime_release_id,mission_id,binding_ref,original_context_ref；FK(project,batch,snapshot_ref)→snapshot；额外 UNIQUE(project,batch,snapshot_ref,scope_digest) 在 snapshot 并对应完整 FK；UNIQUE(authority,mission_id)、UNIQUE(authority,binding_ref)、UNIQUE(authority,runtime_release_id)、UNIQUE(authority,mapping_ref) |
| mission_create_receipt | PK K 且完整 FK K→intent；仅 receipt_ref、event_ref、receipt_hash、verified_at；不重复 mission/release/binding/digest，正式身份从 intent 读取；UNIQUE(authority,receipt_ref)。受控适配器核 R1 回执中 K、完整 request_digest 及 intent 所有身份后才可 INSERT |
| mission_create_journal | PK(K,journal_seq)，FK K→intent；阶段、attempt_ref、observed_result、receipt_ref可空、发生时间；仅诊断，不是提交事实，不用最新状态覆盖 intent |

所有 K 分量 NOT NULL/非空，digest 固定64小写hex，revision正bigint、schema整数固定1；禁止跨 authority 的 FK 省列。snapshot FK 路径保留 project/batch，来源规范 bytes 内有完整复合业务身份。PG intent/reservation/journal 不授 R1 创建许可，PLANNED/UNKNOWN 不能投影 RUNNING。表 append-only、FORCE RLS；迁移 owner、普通 runtime、受控 snapshot 写端、receipt 适配端分离，无 BYPASSRLS。actor 创建日志须 current can_write 且原主体，通用已授权 Mission 读取另投影不泄漏 creation_key/context。无 UPDATE/DELETE/CASCADE；down 遇正式引用或 UNKNOWN 先拒绝，停写导出清单后另审，不删除正式 R1/Evidence。

## 3. 独立锁定快照事务端口（B P1-3）

拟议 server-only LockedScopeAdmissionTransaction 独占一条空闲 autocommit 连接；入口仍检查 IDLE。它自持 READ COMMITTED 事务，设置本次可信 principal 的 SET LOCAL；不调用 ScopeStore.scope 或 BusinessStore._scope，不删除或放宽它们的 IDLE 保护。共享纯 SQL 选边/DTO 组装函数可提取，但事务所有权必须分离。不能让浏览器选择 principal、role 或 lock SQL。

新受控锁函数 wb.lock_scope_admission(project,batch) 仅专用 admission role 可 EXECUTE，PUBLIC/runtime 禁止；SECURITY DEFINER owner 非 superuser/无 BYPASSRLS，固定 search_path=pg_catalog,wb、无动态SQL；仅锁定两个指定行，不授普通 runtime 任意 UPDATE。函数内核当前 can_write 后按 project→release_batch 固定顺序 SELECT FOR UPDATE；取锁后再核 can_write、actor/context、batch 身份。FORCE RLS 保留，专用 role 的锁必要权限及策略由B单独评审，禁止用开放 project UPDATE 代替。函数不可回传不受权明细。当前 runtime 实际无 project FOR UPDATE 权限，此端口**尚不存在**。

PREPARE 已独立 durable commit 后，正式 writer 围栏→该最终 PG 事务→project 锁→batch 锁→读取核验既存 intent 唯一域→完整来源 SQL/规范化并与既存摘要精确比较→Host admission fence→R1 最终重读/CAS/append。最终事务不得首次插入 intent 或重新分配身份。PG 事务和两行锁必须跨最后验证至 durable append/Host fence释放；只提交回执引用后结束。连接不得交其他请求、不得在锁内等模型/人。READ COMMITTED 取锁后各语句看到已提交最新版本；project ACL AFTER 触发器要更新 project、关联 AFTER 触发器要更新 batch，因此对手若先提交，本次见新 revision；若本次先锁，对手无法完成提交直到本次结束。提交之前来源身份不可变；将来允许来源更新必须扩展相应 revision/锁协议，不能沿用本证明。

默认候选预算：lock_timeout=2s、statement_timeout=5s、idle_in_transaction_session_timeout=10s，整个提交围栏≤5s（Host适配可要求更短），超时不得 append；跨网调用有本次剩余硬期限。55P03/40P01/40001/57014/连接丢失均中止事务，**不得自动重试 R1 append**；先在原 K 做正式 lookup。若确认尚未开始 append 才允许重新取得全部许可。append 后 PG 失败时保留正式事实，查正式回执再补 PG 引用；不可用 PG rollback 声称 R1 未发生。真实两连接须覆盖 ACL/关系已修改但触发器等待、反向锁死锁、连接终止与 append 各切点；未证明之前该端口不能上线。

### 3.1 PREPARE 与最终提交分离：精确阶段和恢复矩阵

PREPARE 是独立 PG 事务：重新核可信原主体/当前创建动作、mutation 证明及 can_write，构造受控完整快照，按 K 查重，固定 request_digest、snapshot_ref（scope_ref）、scope_digest、mapping_ref/runtime_release_id/mission_id/binding_ref 和 original_context_ref，并提交 snapshot/intent 成功。**必须确认该事务 durable commit 后才允许任何正式 R1 提交**；不能把首次分配的 intent 放进跨 append 的最终 PG 锁事务，否则 append 后回滚会丢失原身份。PREPARE 不产生 R1 事实。既存同 K 同 digest 仅复用原 immutable intent；异 payload（含换 batch/Scope/映射）409，不覆盖、不重新分配。

最终锁定事务只读取、核验该既存 intent；重读完整 Scope/来源/日期/双 revision 后必须与 PREPARE 固定快照及摘要相等。权限撤销拒绝，Scope/映射/代次变化 HOLD，不在同 K 下重算 request_digest 或替换 snapshot_ref。需要新业务意图时另行明确新 key，禁止故障恢复自动换 key；旧 UNKNOWN 必须先查清原权威结果，不以新 key 绕开。

| 阶段/故障点 | 唯一允许的恢复 |
|---|---|
| PREPARE 未提交或提交响应丢失 | 先按原 K 在 PG 重读确认；PG 结果不明 HOLD，不进入正式 submit、不重分配；确认无 intent 且从未允许正式调用，才可在同 K 重新 PREPARE |
| PREPARE 已提交、未进入最终 submit | 读取原 intent；重新取得全部当前权限和锁，快照精确相等才继续；变化 HOLD |
| 最终 PG 事务在 append 前失败/回滚 | 原 durable intent 保留；按原 K/digest 正式 lookup；确认未 append 后也必须重新取得当前 create、mutation、can_write 和围栏，不直接重放 |
| append 已发生但 PG 回执提交失败或响应丢失 | 不回滚/重分配正式身份；原 K/digest 向原 authority 查原事件回执，核一致后只补 PG receipt 引用；图不全仍 INITIALIZATION_HOLD |
| append 是否发生不明、Host UNKNOWN 或无零副作用证明 | HOLD + 原 K/digest lookup；超时/日志尾部问题不等于 NOT_FOUND |
| 查到原回执 | 验证原 K/digest/所有预留身份，返回原 Mission；不得新建 |
| 权威证明 NOT_FOUND | lookup 不暗转 submit；显式再次 submit 才重新取得全部创建许可，且始终使用原 intent/身份/digest；权限或快照已变保持拒绝/HOLD |

## 4. 动作矩阵和原主体恢复（D P1-1）

动作名是新抽象合同，不宣称真实 DSH 已存在。所有操作都需可信 Host 当前主体=原 actor、相同 authority/project/K/context，未知映射 HOLD；Bob 不能重包 Alice 的 key/context。

| 操作 | 必须具备 | 能否产生正式副作用 |
|---|---|---|
| 首次 submit | mission.create、可信 mutation/CSRF+Origin 或已审核原生证明、当前 B can_write、完整锁定快照及提交围栏 | 仅通过正式 writer 后可创建 |
| 再次 submit / NOT_FOUND 后重交 / 部分初始化继续 | 与首次完全相同；同K同digest及原预留身份；重新验证映射/Scope，不复用旧许可 | 可继续同一创建；绝不分配新身份 |
| lookup_creation | mission.creation.lookup、当前 B can_write、原主体/context；纯读调用无需 CSRF mutation 证明 | **绝不隐式转 submit**；返回原回执/权威 NOT_FOUND/UNKNOWN/HOLD |
| 普通 Mission read | 既有读取合同与 Scope 授权 | 无创建或恢复权，不暴露原创建key |

lookup 当前动作许可不能从 read 或 mutation_authorized boolean 推出。Alice 撤去 create 但保留 lookup/can_write 时可以查原回执；NOT_FOUND 仍不能提交。撤去 lookup 或项目写权时拒绝且不泄漏原对象。write-context 是原主体关联线索，不是当前动作许可。同K异digest恒409，UNKNOWN/超时不是 NOT_FOUND。NOT_FOUND 必须来自原权威在正式writer围栏内重读完整日志并证明无该K事实；lookup 本身不创建。每次再次 submit 都重新获取 create 许可。

## 5. HostAdmissionFence 所需抽象能力（D P1-2）

这是 D/E 必须实现并行内资格验证的语义，当前 HostIdentity(principal,mutation_authorized)、write-context HMAC、CaptainDispatchFencer、资源锁不能自动满足它。接口可以适配既有真实权威，不能虚构 SSO/JWT/Cookie 字段。

输入 Acquire：server-derived host_authority_ref、formal_authority_ref、principal/actor_ref、action=mission.create、project_id、batch_id、K、request_digest、original_context_ref、可信 mutation/native proof 的权威引用，以及本次 writer_epoch/预期R1 cursor/operation_ref/硬期限。证明由 Host 服务端读取，不接受 HTTP 自报 verified。结果严格区分 DENIED、CAPABILITY_UNAVAILABLE、EXPIRED_OR_INVALID、UNKNOWN、HELD；HELD 含不透明 fence_ref、持久 authority/session_generation、范围摘要和截止，不是调用方可自签 DTO。

CommitWithinFence(fence_ref,operation_ref,scope_digest,request_digest,writer_epoch,expected_cursor,正式append回调) 是所需线性化协议，而非“检查一次再写”。Host 适配器必须证明撤权和该回调 durable append 之间存在全序：撤权先线性化则回调不得执行；append先线性化则返回包含同operation/digest/事件引用的 COMMITTED，之后撤权不删除该事实。允许实现为持有权威撤权读锁贯穿回调，或经审查的等价原子提交协议；单次签发短期token/时间戳不满足要求。PG锁、R1 OS锁不代替这个Host全序。结果 COMMITTED、DENIED_BEFORE_APPEND、EXPIRED_BEFORE_APPEND、CAPABILITY_UNAVAILABLE、UNKNOWN；COMMITTED 必须包含可由原 K/request_digest 查询核实的正式原事件回执（operation_ref、event_ref、receipt_ref 和 digest），不是零 append 结果。仅 DENIED_BEFORE_APPEND、EXPIRED_BEFORE_APPEND 表示有可靠零 append 证明；UNKNOWN 及无法证明零副作用的 CAPABILITY_UNAVAILABLE 均先原域 lookup/HOLD，不重分配身份。缺少可查回执的所谓 COMMITTED 按 UNKNOWN 处理。

Release 必须幂等，释放不得撤销已durable事件。过期/会话代次变化/权威重启使旧 fence_ref 不能进入回调；检查过期必须位于受保护提交临界区，不能与append间留撤权窗口。若无法保证回调执行期间不会超期失效，则不得启动回调；正在执行回调的期限处理必须由适配器与writer共同证明，不允许仅本地计时自证。崩溃会释放持有锁；持久 operation/K/digest 使新进程可查唯一事件。Host返回 UNKNOWN、回调成功但响应丢失、会话状态不可读都先HOLD+原域lookup，绝不重分配。不存在真实可证明适配器时生产默认 CAPABILITY_UNAVAILABLE/HOLD，零R1副作用；fixture只测抽象协议，真实Host继续 FIELD_NEEDS_BANK_TRANSFER。

## 6. 正式 writer 选择、初始化与精确影响路径

选择每ledger单一正式写端 FormalMissionWriterPort，而非多个实例RLock：持久ledger policy固定authority及writer模式；服务所有者独占跨进程OS owner锁，操作再采用已有rc72_ledger_lock同名互斥、重建projection/重扫next_seq并以预期cursor CAS。该模式下原始append入口对绑定Mission/创建事件必须拒绝未持有效writer能力；未覆盖legacy进程不可并存写该ledger。这里的owner能力/策略检查尚未实现，现有OS锁仅保护参与路径；不能把方案当已覆盖所有writer。若无法封闭全部入口，正式创建 HOLD。

必须改造/审计路径：bank_mission.start_or_resume；rc72_mission_factory.create_mission_driver；ClosedLoopControlPlane.bootstrap/_mission/_persist_mission/_sync_mission/refresh_ready/register_task及状态更新；MissionTaskGraphCompiler.install/恢复；TruthRuntime append与JsonlEventStore写端；各CLI/恢复入口及所有RC7_MISSION_UPSERTED调用点。Captain/lease/Human/NodeGate特定围栏继续独立生效，新绑定不授权执行。typed绑定保存可以拆第一步但不能向legacy补来源，也不等于真实创建已接通。

端口 submit(K,digest,immutable intent,admission callback) / lookup(K,digest) 都在原authority writer域；创建采用一个不可分割正式创建事件包含K、digest、mapping、typed Scope、原身份。校验后写一个完整带换行事件并fsync才返回回执；崩溃尾部损坏需正式日志恢复协议确认，不能当NOT_FOUND。单事件是绑定/幂等线性化点，后续图初始化不伪装原子多事件。事件发生但graph不全返回 INITIALIZATION_HOLD，禁止派发；新ensure_initialization逐项验证确定性ID/内容、仅补缺项、冲突HOLD，完成结构校验后另写READY_FOR_ADMISSION，仍非执行/PASS。旧resume图断言不放宽。正式typed模型/重建/普通更新/cold恢复必须保留不可变绑定，改绑拒绝；原无绑定Mission保持HOLD，不自动迁移。

## 7. 可独立施工范围、合同影响与退出

本次只交设计。B/D对本文件精确SHA接受后，可先实现纯canonical codec、带tag DTO/schema验证、K/摘要纯函数、缺能力HOLD适配器（不打开正式提交）；必须正向/负向/边界/恢复测试，且零R1/PG写副作用。锁定快照原语需B签SQL/实库测试后另PR。正式模型/factory/writer/008须B/D/E/F对各精确增量认可再施工；不能因纯函数PASS解除正式缺口。

冻结影响待A正式增量：工作台02数据模型（typed来源、mapping、008复合域），05交互/API（动作矩阵、HOLD/UNKNOWN/初始化中），06控制面/事实边界（writer/Host/PG围栏），A03跨组签署；RC7.2模型/工厂/序列化/恢复/正式事件合同及00–03相关事实边界需所有者审核。此文件不覆写冻结文本，不授新事实所有权给工作台。

| 评审责任 | 本V3精确复审点 |
|---|---|
| B | 第1真实来源tag及字节、第2完整authority PK/FK、第3专用角色/锁端口/SQLSTATE/触发器竞争，不代签Host |
| D | 第4所有重交当前create、第5抽象能力可测试与真实能力缺失HOLD，不能把fixture当Host资格 |
| E/RC72 | 第6封闭writer入口、原子事件/日志故障、typed全程保留、graph恢复，不把RLock当跨进程 |
| F | 最新完整SHA独立判定，前次审查不转移 |

正式退出证据必须包含：真实PG迁移/回滚及跨项目复合FK/角色拒绝；最终锁定来源与摘要黄金向量；真实PG→正式factory→原R1→HTTP（不手塞payload）；两个进程同键/异payload、authority换代、同key改batch409；ACL/关系/日期与Host撤权先后全序；每个append前后崩溃/响应丢失/PG失败；Alice未知→Bob拒绝→Alice lookup原回执、create撤权后lookup不重交；普通更新至少三次及cold重建保留绑定；partial graph恢复且无重复事实；旧无来源持续HOLD。真实DSH/Windows必须搬运行内取得证据；无证据不授现场、F验收或最终交付资格。
