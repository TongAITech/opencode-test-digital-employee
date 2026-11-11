# 008 PostgreSQL 结构与 PREPARE 实库候选

本候选落实 B #265 的隔离 SQL 验证范围，参考 D #267 与 E #272。仅在 disposable 测试库显式安装 `tests/fixtures/workbench_scope_008/{up,down}.sql`。默认迁移、009 runner、HTTP、Host、R1 和打包入口无接线。真实权限分配、正式请求字节及回执校验均待独立施工。

- 四表使用全 K 和来源复合外键。intent 在同一行保留非空的业务批次、运行 release 与正式运行批次身份。正式运行批次在 authority 内唯一。Scope 和选择摘要按候选前缀校验。正式请求摘要字段目前仅验证形状，测试值使用独立 fixture 字节域。
- 隔离测试连接以专用 NOLOGIN、NOINHERIT、NOBYPASSRLS 角色运行。测试端仅可读写当前主体的候选 snapshot、intent 与 PREPARE 日志。缺少同 K 的 PREPARE 日志时，延迟约束阻止意图提交。运行角色无 008 访问。测试角色无 receipt 读写与更新、删除或清表权限。回执表外键用受控测试行验证，未接发行者或生成正式回执。
- 同 K 事务级 advisory claim 的正确性以全 K 主键为准。并发测试用第三连接确认两位等待者均到达 PostgreSQL。两请求最终复用同一持久意图、运行批次及日志。冷连接测试覆盖提交后重查，另验证已开启事务拒绝、缺审计回滚与恢复、换批次或选择冲突、撤权与跨 K 回执拒绝。
- 两种 008/009 DDL 次序仅在隔离库演练，比较候选表 RLS 和策略形状并验证移除 008 后 009 保留。008 没有登记生产迁移节点。空表回退锁住四表，关闭策略过滤以保证有权完整读取或明确失败，非空拒绝。另验证 8 KiB PostgreSQL 的全长四列多字节 K 及超限拒绝。
- 实库结果为 PostgreSQL 17.6、UTF8、8 KiB 上 10 项通过，零跳过。可用 `python -m unittest discover -s tests -p 'test_dsh_workbench_b_scope_008_prepare_postgres.py'` 复验，需用 `WB_PG_TEST_DSN` 指向具备创建临时库与角色权限的测试实例。

最终 append 保持 HOLD。E #272 已验证 PG 会话中止后并发撤权可提交。本候选仅覆盖 PG 事务，正式 allocator、目录准入 profile、源行锁端口、组合迁移 graph、实际 Host 与跨存储排序另审。
