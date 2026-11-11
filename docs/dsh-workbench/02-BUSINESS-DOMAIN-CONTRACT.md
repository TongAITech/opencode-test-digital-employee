# 投产日期—需求—系统版本—SST 领域契约
状态：W0_DESIGN_IN_PROGRESS / W0_NOT_FROZEN；W0 候选合同待 A01/A03/F00 正式签署；W1–W4 实现与现场 QA 未运行；A02 BLOCKED_LICENSE

## 不可变业务语义
投产批次就是投产日期，例如 2026-11-12。一个项目下多个日期；一个日期下一个或多个需求及参与投产的系统版本；同一需求在该日期下关联一或多个系统版本；同一需求与同一系统版本关联一或多个 SST。不同需求允许共享同一系统版本，但 SST 关联不能自动互认。
推荐在同一项目内 UNIQUE(project_id,release_date)，保存隐藏稳定 batch_id 以支持日期修订、历史审计及不断链引用。投产计划修改必须留历史，不能静默移动已有 Attempt/Evidence 的原始事实。

## 规范化对象
Project(project_id)
ReleaseBatch(batch_id,project_id,release_date,release_date_history,status)
Requirement(requirement_id,source_ref,...)
System(system_id,...)
SystemVersion(system_version_id,system_id,version_label,...)
SST(sst_id,source_ref,...)
BatchRequirement(batch_id,requirement_id)
BatchSystemVersion(batch_id,system_version_id)
BatchRequirementVersion(batch_id,requirement_id,system_version_id)
BatchRequirementVersionSST(batch_id,requirement_id,system_version_id,sst_id)

最后一张关联表中：(batch_id,requirement_id,system_version_id) 必须存在于 BatchRequirementVersion；同一 batch 中 version 必须属于 BatchSystemVersion；同一 batch 中 requirement 必须属于 BatchRequirement。对于复合关联唯一性、SST 是否被多需求复用，应依照来源系统真实语义明确并测试，不能推测为全局一对一。

## 统一范围选择
Scope={project_id,batch_id,release_date,requirement_ids[],system_version_ids[],sst_ids[]}
联动依赖：选批次→合法需求/版本；选需求→合法版本；选需求+版本→合法 SST。跨十个分区保留 Scope；失效的选择必须可见提示并清理。多选使用关联集合查询，不进行需求与版本的任意笛卡尔组合。

## 用例与证据
测试义务、测试用例、变更代码、WorkItem、Attempt、Evidence、缺陷及报告按正式关联表保存 trace links，不复制源对象。多 SST 共用用例只表示覆盖关系，不能让一次执行虚构多次执行；是否满足某条义务必须检查版本、环境、Oracle 与证据。

## 反例验收
T1 同需求三版本各有多 SST；T2 两需求共享相同系统版本但 SST 不同；T3 多系统相同 version_label；T4 跨日期重名需求/SST；T5 未拆分 SST 显示“待拆分”；T6 关联不存在/跨批次必须阻断；T7 同一用例覆盖多 SST 不重复计数；T8 日期调整引用不断链；T9 重启后 Scope 恢复合法；T10 权限不足不能越权查另一项目。

## WB-A03 v0.3：待签收的领域约束
- 稳定 batch_id 保留历史 R1 关系，用户可见的 release_date 是业务日期而非 UTC 日期。BUSINESS_TZ 必须由业务责任人批准；缺失或冲突的旧 ReleaseBatch 进入 MIGRATION_HOLD，不得默认时区或静默合并。
- 同项目有效批次唯一键 (project_id, release_date)。BatchRequirement PK(batch_id, requirement_id)，BatchSystemVersion PK(batch_id,system_version_id)，BatchRequirementVersion PK(batch_id,requirement_id,system_version_id)，通过双复合外键关联前两表；BatchRequirementVersionSST PK(batch_id,requirement_id,system_version_id,sst_id)，复合外键指向要求版本关联，另核对 SST 来源系统和版本身份。
- 未拆分 SST 以合法要求版本关联的 UNSPLIT 状态呈现，不插入假 SST 主键。多需求共用版本不等于共用 SST。跨批次相同 ID 不继承连边。
- 写入须同一事务、验证主体项目 Scope、expected_relation_revision、稳定 request_id；非法关联 422 完整回滚，已有 Evidence 的关联删除做审计停用，不物理擦除历史。
- 旧 RC7.2 ReleaseBatch 迁移先 dry-run 计数、冲突隔离、来源映射、双向审计及回滚演练；原始 Mission/Attempt/Evidence 不重写，迁移前后分母和对象可追溯。
- 责任和复合关系例子见 [WB-A03-CROSS-GROUP-SIGNOFF.md](WB-A03-CROSS-GROUP-SIGNOFF.md)。上述只是合同，未执行 SQL 迁移。

## WB-B-A03 领域签署附录（W0，仅设计）
B 组签署源 80efa1bfa585fe29a5939c889d5b5a08e4f742ed 的设计可实现性；规范详见 [WB-B-A03-DESIGN-SIGNOFF.md](WB-B-A03-DESIGN-SIGNOFF.md)。project_id 参与 BR/BV/BRV/BRVS 复合主外键；BRVS 需 source_verified_link；来源身份为 source_system + source_namespace + source_object_id + source_revision，禁止以版本标签或 SST 名称 join。业务日期 UNIQUE(project_id,release_date)，改期留同事务历史，稳定 batch_id 不变；BUSINESS_TZ 未批准的 legacy timestamp 迁移进入 MIGRATION_HOLD。签署不代表 Postgres 迁移已实施，也不关闭 F 的真实验收缺口。

### WB-B A03 原型红测纠正：BRV 来源白名单
仅 BR(batch,requirement)+BV(batch,version) 两张表的复合外键不足以拒绝将一个合法需求与另一个合法版本任意配对。**BRV 必须另加 FK(project_id,batch_id,requirement_id,system_version_id) → source_verified_requirement_version 的相同复合 PK**，而该表每行必须带独立权威源 link_ref 和 revision。BRVS 还需独立经过 source_verified_link；此双级来源白名单禁止笛卡尔积写入污染。参见 B 组签署及负向 SQL 测试。

<!-- A integration: B source 704c86a; FG18 witness corrected in tests; B reconfirmation pending. -->


## WB-FG18 SST 原始身份作用域修订

F 组已实证同一个 source_system 的 SST 原始 source_object_id 可以在同项目两个系统版本中重复出现。内部稳定 sst_id 必须与原始 source_object_id 分离；源标识唯一性限定为 (project_id,system_version_id,source_system,source_namespace,source_object_id)，同时内部 sst_id 在项目内唯一。若重复出现，生成独立内部 SST ID、保留两个原始 source_ref 与 source_revision。BRVS/Scope 仍以 project_id、batch_id、requirement_id、version_id、sst_id 和 source_verified_link 关联，决不按 raw ID/版本显示标签跨版本串联。此段是 W0 设计纠偏，不是 PostgreSQL W1 验收。


## PostgreSQL 正式业务库增量决策（待 B/E/D 与 F 精确源审查）
正式工作台业务数据库采用 PostgreSQL；SQLite 设计见证不能替代真实 PostgreSQL 验收。Redis 仅用于缓存、临时状态和协调，丢失后必须从权威存储恢复。

项目、投产日期、需求、系统、系统版本、SST、BR/BV/BRV/BRVS、测试用例、缺陷、里程碑、报告、知识、会议纪要及审计记录持久化至工作台独立 schema。所有项目内实体及关联以 project_id 参与复合主外键，BRV/BRVS 必须引用权威来源连边；禁止按显示名称连接。投产日期以 DATE 保存，稳定 batch_id 改期不变并记录历史。已有来源见证不可静默覆盖或删除。

业务写入在一个 PostgreSQL 事务内完成授权、expected_relation_revision 比较、关联校验、业务变更、幂等记录、审计和事务 outbox；冲突或非法关系完整回滚。运行角色不得拥有 schema/迁移权限；宿主可信主体通过服务端上下文授权，连接池每事务设置并清理身份，RLS 及 API 授权共同隔离项目，撤权后旧游标失效。审计保留主体、动作、请求ID、对象、前后修订、时间与来源，业务角色不可改写。

R1 继续是 Mission、Attempt、Evidence、NodeGate 正式运行事实来源。工作台数据库只保存业务关系与 R1 引用/投影，不直接更新这些正式事实。读取时先取最小 Mission 身份，校验 project+batch，再读关联明细；禁止 unscoped fallback。跨 PostgreSQL/R1 不假设分布式原子事务：命令以持久幂等状态、正式 command_ref 和对账恢复处理，未知副作用进入 HOLD；outbox 投递不等于 R1 已执行或 PASS。缓存与投影必须带来源修订及新鲜度，R1 不可用返回明确缺口。

证据大文件放受控文件或对象存储，数据库只保存元数据、哈希、访问控制与引用；上传暂存、哈希验证、元数据提交和孤儿清理须可恢复，不将缺文件或哈希失败视为有效证据。

迁移使用有序版本与校验和、专用迁移角色、备份及 dry-run；先核对来源映射、冲突隔离、行数和历史分母，再切换。回滚必须实测恢复旧应用与数据库兼容状态，不删除正式 R1 或已有证据；不可逆步骤须先备份并明确恢复方案，失败停止切换。

W1 验收必须在真实 PostgreSQL 执行：迁移与回滚、同需求多版本多SST、共享版本不共享SST、跨项目/批次复合FK拒绝、并发修订冲突、幂等重放/异负载、事务中断零部分写、连接池身份串用、撤权、重启、outbox重复/故障恢复、R1不可用和证据缺失。记录服务器版本、源SHA、命令、日志与数据Oracle；当前均 NOT_RUN。

本增量状态 PG_INCREMENT_REVIEW_PENDING；历史 B/D/E 设计签署不覆盖本增量，须分别绑定完整提交 SHA 提供意见；F 接受最新设计 HEAD 前禁止 W0_DESIGN_FROZEN。

## B07 业务草稿资产增量（待职责评审，不改变R1边界）
新增草稿Case/Obligation、缺陷说明、报告草稿、知识、会议纪要和里程碑的统一合法Scope/版本化资产设计，见[WB-B07-DRAFT-ASSET-API-CONTRACT.md](WB-B07-DRAFT-ASSET-API-CONTRACT.md)。业务保存/退役/恢复不能形成正式Case、Defect、报告或R1执行结论；精确源B/E/D评审后才实现新增CRUD。

## M1 已治理根项目名称增量（2026-11-11，隔离实施候选）

按[D211](WB-D-PROJECT-METADATA-BOARD-INCREMENT.md)、[B230](WB-B-PROJECT-METADATA-M1-NAMESPACE-CANDIDATE-20261111.md)与[A决策](WB-A-PROJECT-METADATA-M1-DECISION-20261111.md)执行有界M1：只允许完整行政治理并激活命名域中的已有根PROJECT改名；project_id不变、project.name单一文本事实、独立metadata_revision、规范UTF8精确字节唯一键。未知legacy域/旧冲突保持只读，不按可见列表判重，不授创建/成员/目录/父子能力。完整名称规则及治理分母以被审B230精确a21b82fe+A9a41b145为准。

D235/E233/F234已接受该有界设计进入隔离候选施工，并非新SQL或产品验收。009候选显式依赖001–007，008留正式绑定；禁止空008、隐式跳checksum或部署自动学习profile。具体runner/SQL/列权限/RLS/一致性/history/result/outbox及新固定profile须另审实库精确源。metadata不改DATE/batch/BRV/BRVS或R1正式事实。历史均NOT_RUN/REVIEW_PENDING文字仅追溯其原提案检查点，当前资格按08–10精确源证据核对，不向本增量转签。
