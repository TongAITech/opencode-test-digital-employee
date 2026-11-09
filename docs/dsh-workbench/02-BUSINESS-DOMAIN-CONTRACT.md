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
