# B 可选 009 Scope 来源 profile 验证

候选基线 `12989ad4`。模板从本机 PostgreSQL 17.6 + ICU 的可丢弃数据库生成。该数据库通过现有测试 fixture 执行 001–007 及已审 009 `3b74d5e00edb6c2c0304074bdc2699481309c52c`，配置现有的最小 runtime 授权和独立 NOLOGIN executor。模板绑定 009 manifest，并由代码固定内容哈希 `f5e8629399b6b9f97f8480407b10495470e885b5518b60b99a8229dfc0f5a828`。两个独立数据库及不同角色名得到同一组规范化摘要。F 独立实现审查待完成。

调用方通过 `ReadOnlyScopeSourcePolicyQualification009(connection, admin_role=..., executor_role=...)` 显式选择。角色名来自受控部署配置。探针使用自己的只读 REPEATABLE READ 事务，固定搜索路径。返回结果含数据库观察时点、固定 profile 哈希、目录摘要与拒绝原因。默认 `ReadOnlyScopeSourcePolicyQualification` 仍选原 v2，原 artifact 和接口保持兼容。在 009 环境显式运行 v2 得到 UNQUALIFIED。空 009 回退后显式 009 也得到 UNQUALIFIED，默认 v2 恢复匹配。

模板核对 22 张来源及关联表的定义、所有 RLS 策略、索引、约束、普通触发器与 140 条关联 RI 执行记录。它绑定项目治理和元数据函数体哈希、声明属性、所有者和有效执行权限，核对 WB 对象及列的直接 ACL、grant option、有效列访问与列排序规则。独立 executor 的登录及高权限属性、跨库所有权、参数能力、角色边和 runtime 可 SET 的权限均纳入比较。WB schema 所有者须为指定行政角色。扩展观察对未知目录内容仅输出分组摘要。安装迁移版本行依赖行政迁移管道验证，探针通过目录定义核验部署形状。

实测新旧 profile 套件 37 项，17.750 秒，零跳过。其中 9 项真实 PG 009 测试和 1 项固定模板测试，原 profile 27 项实际回归通过。另有原 v2 artifact 2 项通过。真实 PG 用例覆盖角色属性漂移、现有授权撤销和恢复、治理触发器及函数变化、009 复合外键内部触发器停用和恢复、RLS 漂移与回滚、连接状态和两种 profile 切换边界。所有权限变更局限于已有本地 fixture 并清理，测试验证只读观察的拒绝行为。源码路径只查询目录和 session 设置，实际项目改名及审计行变化后 profile 摘要相同。

每个结果都为 `admission_authorized=false`。生产资格仍依赖独立审核、受控 DDL/角色锁与锁内复验，连接身份之外的业务主体由 Host 边界验证。模板只接受已观察并固定的形状，额外配置差异需另审。现有 PostgreSQL CI 将运行新增测试，结果登记到本 PR。
