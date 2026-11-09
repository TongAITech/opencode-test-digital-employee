# 投产日期—需求—系统版本—SST 领域契约
状态：W0 候选冻结（需核对现场数据源与 RC7.2 兼容映射）

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
