# E 正式 Mission 绑定分阶段设计候选

本候选以 W0 `27fb6cc70a60a024d885dd6952ca44f70204a738` 为源码基线，承接 V3 `04ca971676509da9379ed53a29b495d2a32c325c`、紧凑 wire `3266cb2d814c8f2233733ba4b53642940a7892a0` 与 D 闭包调查 [PR242](https://github.com/TongAITech/opencode-test-digital-employee/pull/242) 的 `19be4aacc53e7a21a334e40fced7b9b27d1e61fd`。第一阶段请求 A/B/D/F 对精确源审阅运行域表示及保真行为。批次映射、正式 reader、writer、008 与 Host 适配分别保留实现准入条件。

## 1. 第一阶段的最小 typed 表示与缺省保真

`Mission` 当前只声明旧运行字段，`to_payload` 使用 `asdict`。在本基线用临时子类添加 `scope_binding=None`，实际得到 `scope_binding` 存在于 `vars`，`to_payload` 输出 null，现有 `reject_reserved` 返回 `MISSION_SCOPE_NOT_ADMITTED`。原 `Mission('  M1  ', '  R1  ', ...)` 则仍将 ID 处理为 `M1/R1`，序列化没有三个保留键。该探针只构造内存对象。

候选使用运行域内部 `Mission._scope_state`，默认值为内部枚举单例 `ABSENT`，字段 `init=False`，保持现有构造签名。另一个合法状态是由严格结构解码构造的不可变紧凑绑定，持有脱离输入的规范字节。内部字段永不进入 wire，枚举单例支持深拷贝后仍保持身份。第一阶段的解码和序列化在隔离入口验证，生产 `Control._mission` 对任何已带 Scope 的原始行继续返回 HOLD。正式绑定对象的 clone 需经明确保留内部状态的路径，避免默认 `dataclasses.replace` 将 `init=False` 状态重置为缺省。覆盖的调用点依据 D 的源码索引逐项核对。

| 输入状态 | 运行域及 wire | 当前可执行结果 |
|---|---|---|
| raw 三个保留键均缺省 | 内部 `ABSENT`。序列化保持旧 wire，省略内部字段、`scope_binding` 及两个镜像 | 旧 bootstrap、更新、恢复继续。Workbench 正式绑定查询返回未解析 |
| raw 有显式 null、单边/双边 flat、partial 或内部身份冲突 | 保留原日志及分类诊断。解码拒绝形成可写 Mission | 受保护入口 HOLD。历史回放照旧加载旧事实 |
| raw 完整 15 字段及精确镜像 | 隔离解码得到结构有效的不可变值。隔离序列化输出原 15 字段及两个确定性镜像 | 默认 `MISSION_SCOPE_NOT_ADMITTED`。正式来源和写权独立核验 |
| `Mission` 输入被动态附加任一 raw 保留键，或内部状态被置为 null/未知值 | 结构拒绝。动态字段优先检测 | 首个副作用前 HOLD |

具体协同规则如下。

- raw 行继续用 `project_id`、`batch_id`、`scope_binding` 键存在性判断，显式 null 始终触发保护。对象入口先检查这三个动态键。对于正式 `Mission` 类型，再要求内部状态恰为 `ABSENT` 才能走既有负向 guard 的 legacy 通路。完整 typed 对象和内部未知状态均 HOLD。已存在的派生类型如需接受内部缺省字段，先逐个列出兼容调用和原 serializer 行为，避免通用 `getattr` 接受任意用户对象。
- 对旧运行 payload 显式移除内部字段。隔离的 typed serializer 返回独立字典，原 ID/镜像必须精确一致。当前模型 `_required`、`truth_overlay._base` 和 `_r1_payload` 会处理空白或覆盖 `release_id`。bound 解码在进入这些旧规范化步骤前比较原始身份。首版正式分配 ID 须满足旧运行 ID 原样往返，任何 trim 会造成变化的 bound ID 或参数 `release_id` 不一致都拒绝。旧无 Scope 路径原有 strip 语义照旧。
- 保留紧凑对象 15 键、K 4 键和 mapping 7 键。共享纯校验如需迁入运行包，另审 stdlib 叶模块、Python 3.8/3.11、离线源归档及与现有 codec 的一致性。运行域禁止依赖 `tools/dsh_workbench`。既有 `ScopeIdentity` 仅作结构数据，无法凭其签发任何权威。
- 历史 `TruthRuntime.rebuild_projection` 保留既有日志解析语义。严格 raw JSON 在新版本正式 creation 入口和受控绑定解码处应用，历史中的旧额外字段、null/partial 行保留供诊断。严禁将这些行处理为 `ABSENT` 后写回，也不以新解析规则整本拒绝旧日志。版本化正式回放及不可变历史校验另属第 4 节。

### 通用序列化、直接持久化及复制的保真边界

D 对首版 `ff98337d1b97da68082dbb96e262057a817aa0b5` 的 P1 保留在 [PR247](https://github.com/TongAITech/opencode-test-digital-employee/pull/247) `cb7a9ae`。实际临时 R1 探针在同基线复现两条路径。第一条把动态 `scope_binding` 和模拟内部值附在精确 `Mission` 上，`reject_reserved` 拒绝，直接 `append_entity` 却持久化无 Scope 行。第二条在临时旧行 v2 注入 Scope，随后用普通无绑定 `Mission` 调 `append_entity` 写入 v3。当前目标行的 Scope 消失，R1 bytes 改变。两条都发生在现有 `append_entity`，首版仅靠 Control guard 或移除内部字段会遗漏它们。

阶段一将以下规则作为精确实现与验收条件。

| 入口 | 强制行为 |
|---|---|
| `models.to_payload` 的 Mission 分支 | 在 `asdict` 或深拷贝、字段丢弃前核 Mission 实际类型和状态。动态三个保留键、派生 dataclass 声明的同名 wire 字段、非 ABSENT 内部状态，包括 null、完整绑定和未知对象，统一 `MISSION_SCOPE_NOT_ADMITTED`。只有合法旧 `ABSENT` 进入既有 `asdict` 和顶层 Enum 转换，并从输出移除内部字段。其他实体继续原通用路径。 |
| `truth_overlay.append_entity` 的 Mission 分支 | 在 durable acceptance、`_r1_payload` 和 append 前执行相同对象拒绝。对通过的精确旧 Mission，按既有 canonical ID 定位本次实际写入目标，核当前投影旧行。旧行带任一保留键或目标不唯一时拒绝，防止 ABSENT 输入覆盖有 Scope 的现存目标。新无旧行或旧行完全无保留键沿原旧路径。该检查只覆盖当前可见目标，跨进程陈旧投影及 raw writer 残余照旧。 |
| `truth_overlay._r1_payload` | 既有精确 `_MODEL_EVENT` 类型分派保留。通用 serializer 自身拒绝 Scope，防止直接调用 payload 构造丢字段。旧无 Scope 的 release 参数处理保持既有规则。 |
| `append_rc72_entity` | 精确类型映射继续拒绝 RC7 `Mission` 为 `UNSUPPORTED_RC72_ENTITY`，早于 RC72 的 `asdict` 序列化。 |
| 隔离 serializer | 仅输出 detached 的紧凑作用域 DTO。阶段一不从该 DTO 转换到现有 `append_entity`、`append_rc72_entity`、`append_atomic` 或 Control 重建路径。绑定保真由该隔离输出验证。 |

真实构造分母为 D242 所列八处：bank、N1、五个 qualification 和 Control 重建均使用精确 `Mission`。源码搜索未发现正式运行、交付、管理路径的 Mission 派生类调用者。通用 serializer 如遇真实派生 dataclass，保持原无 Scope 子类的字段输出，但须先以真实继承关系识别，拒绝动态或声明的保留键和任何内部状态覆盖。缺省必须来自可信 `Mission` 的基类声明或真实实例的内部 `ABSENT` 单例，不能以 duck type、任意 getter 或 `vars().get(..., ABSENT)` 推定。`init=False` 默认字段可能仅存在于基类声明，D 的实际探针已确认这一点。派生类若遮蔽缺省字段或提供异常 descriptor，在进入 `asdict` 前拒绝，禁止试运行 getter。`append_entity` 对无 Scope 派生类继续沿既有精确分派的 unsupported 行为。

绑定对象的隔离 clone 和 `deepcopy` 必须保留同一规范绑定和身份，脱离可变输入。旧无绑定复制保持缺省及旧 wire。默认 `dataclasses.replace` 不可用于 bound，因为 `init=False` 字段会回到缺省。调用点清单、显式保真 clone 和回归共同约束该边界。未经审阅的直接 `asdict/replace` 不能作为 writer 或绑定恢复入口。历史原始记录照旧回放，现有 `TruthRuntime.append_atomic` 和 `JsonlEventStore.append` 仍是未封闭的通用端口。

第一阶段可审代码范围限运行域内部表示、隔离解码及 serializer、原局部 guard 的缺省兼容适配，以及上表通用入口的局部保真拒绝。实际模型改动须此文档精确评审后另开实现 PR。生产 bound 路由继续 HOLD。

## 2. 正式批次身份由创建事实固定

当前 `E02Service.graph` 把 PG `batch` 传给 `validate_lineage`，后者用它比较 ETU/Obligation 的 `release_batch_id`。RC72 `ReleaseBatch.release_batch_id` 是独立运行身份，其正式行同时具有 `mission_id` 和 `release_id`。紧凑 mapping 已有 `runtime_release_id`，它对应正式行的 release，仍缺正式 `release_batch_id`。PG `batch_id`、runtime release 与 runtime release batch 三者都需精确核对。

拟议在同一不可分割的正式 Mission 创建事件内携带单独版本化的批次映射描述，保持紧凑 15/4/7 wire。描述固定记录 `schema_version=1`、`formal_authority_ref`、`mapping_ref`、`project_id`、`batch_id`、`runtime_release_id`、`runtime_release_batch_id`、`mission_id` 和 `creation_operation_ref`，并与同事件紧凑绑定逐字段核对。创建事件及描述的实际 event schema 和索引由正式 writer 增量签署。`mapping_ref` 在同 authority 内唯一，首版每次新建预留全新的 runtime release 与 runtime release batch。`(formal_authority_ref,runtime_release_batch_id)` 唯一，绑定/批次/任务同域冲突即 HOLD。多个 Mission 可对应同一 PG 批次，各自仍具不同正式运行身份。

正式分配器在 durable PREPARE 中固定该 ID 和操作引用。008 可保存预留意图和正式回执引用，正式事件负责确认映射。后续完整 request digest 的版本化规范需覆盖该描述与永久操作引用。旧 K 结果恢复不得更换任何预留身份。运行批次暂缺 canonical row 时，绑定创建事实仍可作为原回执查询依据，图与执行保持 `INITIALIZATION_HOLD`。受控的 canonical ReleaseBatch 注册及后续 Q7/Field-start/N1 路线要逐步审定，查到 canonical row 后核 `release_batch_id/mission_id/release_id` 三元组。已有 launcher 依赖预先存在的 canonical 批次，不能假定它会为此自动分配或为新批次授 Q7。

旧 compact 数据缺该正式描述，即使结构完整或字符串巧合相等，也保持批次未解析。禁止回填、猜测、重算旧摘要或自动重分配。若历史上存在经正式来源绑定的旧数据，单独做来源治理与兼容评审。本轮不扩充紧凑 15 字段。

## 3. 正式 reader 与首个副作用边界

正式读取先做当前 Host/PG 项目及合法 Scope 授权，再对同一 R1 快照最小读取 Mission identity、紧凑镜像、受控 creation 索引及批次映射。以原 authority/operation/K/request_digest 核唯一创建事件和完整身份，以复合 `(project_id,batch_id,snapshot_ref,scope_digest)` 核历史 PG 快照，E02 另核 canonical ReleaseBatch 三元组。通过后才取任务、执行、Evidence 和图明细，并在返回前重核当前授权及读取修订。E02 lineage 接收已证 `runtime_release_batch_id`，对外业务响应仍用 PG `batch_id`。现有 temp replay 可读取整个日志以建立投影，这个限制和明细查询顺序分别说明。缺事实、重复、损坏、无当前权限均失败关闭，Workbench 禁用 unscoped fallback。历史快照与当前权限分开，改期不改历史绑定，缺新 Scope 策略不得派发。普通已授权读取与原创建主体 lookup 分属两套权限。

D 的临时 R1 实测中，supervisor reset 在后续 Control HOLD 之前已写恢复 Evidence 并把 Task 置 READY，Session.prepare 也能写 PREPARED handoff。下列是接通正向 bound 运行前的首个副作用条件。逐入口核真实目标、当前 actor 和适用 writer capability，任何未覆盖的 bound 路线默认 HOLD。

| 路径 | 必须在下列动作前完成检查 |
|---|---|
| bank `start_or_resume`、Control bootstrap、graph install 及普通更新 | 首个 Mission/Task/attestation 写之前。任务、Gap、Evaluation 与其他受管对象保留实际目标及整批预检 |
| native CLI、release driver、Field launcher、N1 dispatch/assignment、后续各阶段 | 首个预算配置、ReleaseBatch/Field-start 写、Task/dispatch receipt、Worker/资源分配之前。保留 package/source、Q7/mirror、Captain、lease、Human 与 NodeGate 原先验 |
| supervisor `handle`、`_reset_unstarted_lease`、`_human_side_effect_boundary` | recovery Evidence、Gap、Task 变更之前。直接进入私有恢复路径也要检查实际对象归属 |
| Worker `resume_active` 及 Session `prepare`/`activate` | `_assign` 和 worker 启动之前，以及 PREPARED/ACTIVATED handoff、Task lease-owner 更新之前。按真实 task/handoff/原新 lease 所属核权限，Session 找回不授主体或新副作用资格 |
| Captain/worker takeover、N7 执行与 Attempt/Evidence、N8/N9/N10 和外部 adapter | 首个真实租约、模型/工具/SUT 执行、文件/对象存储写或正式事实之前。未经审查的 adapter 不进入 bound 可运行范围 |

受控单 writer 需覆盖 D 索引中的正式路径及动态入口，对目标 ledger 在进程、文件写权限和插件边界落实 owner 模式。已有 OS ledger lock 只保护参与者。通用 `append_entity`、`append_rc72_entity`、`TruthRuntime.append_atomic`、`JsonlEventStore.append`、direct scheduler/planner/session 和外部进程仍须审计封闭。局部 guard 的当前投影、上游已发生效果及 bank mtime 限制照实保留。正式 Scope 创建、后续派发和 N10 发布是独立授权步骤。

## 4. 008、PREPARE、HostFence 与实施依赖

008 以现 001–007 的业务身份/关联约束为前置。009 项目元数据也显式依赖 001–007，保留 008 编号且两者无需互相依赖。009 的名称及 metadata_revision 不进入绑定身份或 Scope 快照。将来需增依赖时先审显式 manifest、应用及回滚拓扑。009 和 008 产生的 DDL/RLS/角色变化按实际部署组合核固定 profile，新 profile 独立审批，未知组合为 `UNQUALIFIED`。任何已有 profile 匹配都不授创建许可。

008 预留 V3 snapshot/intent/receipt/journal。完整快照及规范 bytes 留 PG，保留复合 FK 和 append-only/RLS 分权。intent 固定 K、request_digest、snapshot、原主体 context、紧凑身份和批次描述，先查原 K 再分配，冲突取原分配并核同请求。PREPARE 独立提交后才能进入最终事务。只读或未知结果禁止自动升级 submit。最终顺序沿 V3 为 writer 排他及最新 R1 重读、B 独立锁定快照事务、Host 最终撤权围栏、CAS 与 durable 单事件 append。旧 `ScopeStore` 的 IDLE 入口保护保留，旧 scope 查询不能嵌入最终锁事务。具体 PG 锁权限、交叉迁移组合、快照新鲜度、复合约束与回滚另单审真实 SQL。

HostFence 需 D 核可信当前动作、主体、scope/request digest、永久 operation、writer epoch、预期 cursor 与撤权/append 全序。缺真实适配器持续 HOLD，真实能力在行内验证。COMMITTED 必须返回可查原回执，拒绝/过期需可证明零 append。UNKNOWN、网络断开或 PG 后续失败先以原 authority/K/digest lookup，保留原 ID 与快照，禁止重分配。重交须明确的新 submit 请求及当前完整创建许可，不能由 lookup 隐式发起。后续部分初始化按原操作和确定性身份补齐，冲突则 HOLD，未完成不派发。任何模型、writer、008 或 Host 适配实现按各自精确增量另审。

## 5. 验收与恢复测试

- 第一阶段对象测试覆盖三键缺省、显式 null、partial、flat-only、完整 15/4/7、内部未知状态、动态键、错镜像、trim/覆盖 release、深拷贝及 clone。对旧构造签名和序列化逐字段比对。隔离绑定往返保持内容，旧运行 guard 对完整绑定依旧 HOLD。旧日志冷回放保留原字段与 bytes，现有 legacy bootstrap/qualification、task 更新、恢复及离线源导入回归通过后才可集成。
- 直接入口测试用真实临时 R1。分别给精确 Mission 注入每个动态保留键、内部完整值、null、未知值和伪造缺省对象，调用 `to_payload` 与 `append_entity`，断言同一 HOLD。给 `asdict`、未知字段 getter、durable acceptance、append 放置 tripwire，确认拒绝先于这些动作。另给目标旧行置 Scope，再传 ABSENT Mission，检查正确目标定位、R1 bytes/投影及原行不变。无 Scope 新建和更新需真实成功并与旧 wire 比对。旧干净派生 dataclass 保留通用序列化字段，派生保留键与遮蔽状态被拒绝，直接 append 的精确类型拒绝保留。验证 `append_rc72_entity` 的旧拒绝、隔离 serializer 无写端调用、clone/deepcopy 不丢绑定、bound 调用点没有默认 replace 路径，以及历史 raw 记录冷回放不改写。
- 正式 reader 测真实 PG 与正式 creation writer，使用三个互不相等的 ID 验证映射。错误 PG 批次、错误正式批次、同名巧合、重复事件、篡改映射/摘要、缺快照和缺 canonical row 都有拒绝测试。拒绝时以 spy 验证零任务/执行/Evidence 明细查询，旧无绑定仍按既有 legacy 兼容。成功图验证使用正式 `runtime_release_batch_id` 并返回正确业务 batch。
- 首个副作用前测试覆盖 supervisor reset/human boundary、`resume_active._assign`、Session prepare/activate、CLI budget、Field-start、N1 assignment 和直接底层 writer 尝试。断言原 R1 bytes/投影、Task/lease、预算、日志/证据目录及 Worker 调用计数保持不变。合法旧无 Scope 恢复回归同时运行，已有上游事实作为测试基线保留。
- 真实 PG + 两进程正式 writer + Host 合同 fixture 覆盖 PREPARE 断开、未 append 超时、append 后响应丢失、PG 回执失败、日志尾部损坏、同 K 异 payload、撤权前后、跨主体拒绝、原 K 唯一回执和部分图恢复。无真实 Host 时 fixture 只核协议行为，行内 DSH/Windows 保持待验证。最终还须真实 PG→正式 factory/R1→HTTP 链路，禁止用手工 payload 代替正式事实。

本次提交候选设计。内存探针复核旧 Mission strip、旧 wire 省略及 Optional 默认值冲突。临时 R1 探针复现直接写入丢 Scope 的两条旧路径。supervisor 与 Session 的观察引用 D 精确报告。实现后的拒绝及保真证据须对新源码独立取得。
