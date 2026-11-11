# WB-F｜可选 009 Scope 来源 profile 独立验收｜7d7c3fcd

结论 `ACCEPTED_EXACT_INTERNAL_CATALOG_OBSERVER`，适用于 PR #255 的 `7d7c3fcdc1449491ea3dea90aa1bd9be0c5591ca`，2026-11-11。验收范围是显式选择、基于批准模板的 PG17 只读目录观察，输出限内部诊断。P2 记录了旧事实字段仍含目录定义文本的边界。[候选 PR #255](https://github.com/TongAITech/opencode-test-digital-employee/pull/255)

## 固定模板与观察边界

- F 核对 009 artifact 的固定内容哈希 `f5e8629399b6b9f97f8480407b10495470e885b5518b60b99a8229dfc0f5a828`、固定来源提交 `3b74d5e00edb6c2c0304074bdc2699481309c52c`，以及原始 009 迁移 manifest 哈希 `ee96a0f590190766d891eb84b6fed22782b11dae8e43fa7b0de8c645f198cac5`。从批准 fixture 的实际只读目录独立计数，扩展定义为 22 张表、140 条关联 RI 执行记录，九组规范化摘要逐一匹配。模板的基础定义段另有 13 张表、100 条 RI 记录。probe 根据固定摘要比较实际目录，读取动态对象列表用于发现漂移，未用其改写模板。固定 artifact 同 ID 篡改在数据库读取前被拒绝。
- 显式 009 observer 核对受控 admin/executor 名称、schema 所有者、executor 的 NOLOGIN/NOINHERIT 等角色属性、相关角色边、参数权限、有效列与函数权限、直接 ACL/grant option、函数体摘要、全策略、索引、普通触发器和 RI。继承的 v2 守卫继续核对 current/session/backend 身份、origin 及参数权限、RLS 和来源 ACL，默认选择保留 v2 artifact 与接口。现有 fixture 验证未知配置拒绝，恢复后重新匹配，且实际项目改名和审计行变动不改变该目录摘要。
- 默认 v2 在 009 环境返回 UNQUALIFIED，空 009 下迁后 v2 恢复 MATCHED_AS_OF，显式 009 此时拒绝。只读观察用独占的 REPEATABLE READ READ ONLY 事务及局部设置，拒绝外层事务，结束后恢复原设置。每条结果 `admission_authorized=false`，不签发授权。迁移账本由迁移管道验证，当前 probe 的证据来自目录形状与连接身份。

## P2｜扩展摘要与继承诊断文本

F 复用已有隔离 fixture 的两种目录变更，未新增角色或权限探针。009-only 的 `observed_restrict` 出现在 `wb.project_name_binding` 时，返回 UNQUALIFIED，序列化结果中无该策略名，扩展只返回摘要。已有 v2 测试的 `unknown_reader` 出现在基础 `wb.batch_requirement_version` 时，用 009 observer 也返回 UNQUALIFIED，但继承的 `facts.policies` 含策略名及 `using_expr=true`，移除回滚后仍可观察到。标准匹配态还从基础 `wb.project` 的 `facts.triggers` 返回一条已批准 009 治理触发器 DDL。现有 009 函数体哨兵测试通过，未复现函数体回显，未使用真实敏感数据。

扩展分组的摘要约定得到验证，整个 009 返回值仍包含基础目录表达式和 DDL，适用于已有目录访问权限的内部诊断。若下游需要完整结果可外发或落入共享证据，应先收敛 009 诊断字段并独立复验。基础表达式可含 SQL 文本这一事实不改变拒绝判定。

## 独立回归与 CI

```sh
WB_PG_REQUIRE_ICU=1 \
WB_PG_TEST_DSN='host=/tmp/dsh-pgicu.DL7Eav/socket port=55439 dbname=postgres' \
  ../pg-environment-venv/bin/python -m unittest discover -s tests -p 'test_dsh_workbench_b*postgres.py' -v
../pg-environment-venv/bin/python -m unittest discover -s tests \
  -p 'test_dsh_workbench_scope_profile_artifact.py' -v
```

F 独立实测 PostgreSQL 17.6 ICU、Psycopg 3.2.13，318 项通过、零跳过，其中新旧 profile 37 项（旧 27、新 10），旧 artifact 另有 2 项通过。37 项含固定模板测试，新模板的正常两库复现、版本选择及下迁、配置身份、目录漂移与恢复等实库覆盖。权限行为仅审源码及现有拥有 fixture。

PR 检查 42971655429 执行合成提交 `a53eabe` 的 318 项。F 发起独立 workflow_dispatch 42972532376，checkout 日志 `git log -1 --format=%H` 输出本报告完整候选 SHA，318 项通过、零跳过，ICU 用例实际通过。[合成 CI](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42971655429) · [精确源 CI](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42972532376)

生产 Host 资格、锁内复验、DDL/角色围栏、正式 admission、银行现场和发布门禁仍需各自证据。报告 PR 只增加本文件。
