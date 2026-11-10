# B01/B02 PostgreSQL 工单实现与证据

基线 `e255c9cd`，W0冻结后独立施工；状态 CODE_COMPLETE / INDEPENDENT_F_QA_PENDING。本工单仅项目、投产日期、系统与版本，不包含B03–B06、真实Host/API或R1写入。

实现：`business_store.py` 使用参数化SQL与显式事务。`business_migrations.py` 带迁移锁、版本/校验和、幂等升级与非空数据库回滚拒绝。001迁移包含项目ACL、DATE唯一、稳定batch ID、revision、系统/版本来源namespace身份、复合FK、append-only历史/审计、幂等负载哈希。并发改期FOR UPDATE后检查expected revision，变更、审计、历史与请求记录同事务；PG deferred trigger拒绝无历史/审计直接改期。运行角色不拥有schema、DDL或审计历史UPDATE/DELETE权限。

可信边界：BusinessStore仅接受已在服务端认证的principal，禁止直接映射HTTP body/query。数据库service role属于可信后端，可设置事务局部上下文；客户端不得获得该角色连接。RLS防止遗漏project谓词导致越域；它不声称防住被攻陷的可信服务。每次事务SET LOCAL，提交/回滚清理；Host middleware接入由D/后续API工单完成。项目及ACL首次配置由独立管理员`provision_project`执行并审计，运行角色无创建项目/授权权限。

部署：专用迁移owner执行migrate(connection)，管理员创建`wb_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS`后执行001_identity.runtime.sql，再配置其连接给BusinessStore。凭据不进入源码。运行时Python>=3.9、Psycopg3.2.13；这是独立工作台数据库组件，未更换RC7.2运行时。Windows/离线驱动载荷后续需D/F实测。依赖Psycopg LGPL-3.0-or-later、libpq/PostgreSQL PostgreSQL License，未复制受限产品源码。

本地真实PostgreSQL17.6固定官方源码`7885b94dd81b98bbab9ed878680d156df7bf857f`，隔离数据库与非owner LOGIN角色逐测试生成/销毁。命令：

```sh
WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' ../pg-environment-venv/bin/python -m unittest discover -s tests -p test_dsh_workbench_b_postgres.py -v
```

覆盖：有效闰日/非法日期、项目同日唯一/跨项目合法、改期历史与CAS、同键重放/异负载拒绝、审计故障全回滚和恢复、并发仅一胜、backend终止未提交写回滚、重连、撤权/只读/无Scope、schema与审计权限拒绝、同标签多系统/来源namespace、跨项目FK拒绝、checksum篡改、空库降级重建、非空库禁止自动回滚、项目管理员原子配置。

回滚：空schema用rollback(connection)实测；已有业务数据时拒绝自动DROP，须管理员备份恢复并核对新增资产与引用，不能直接执行原始down SQL。无旧R1迁移或生产来源导入；缺来源/业务时区仍HOLD。本工单不记录实施QA_PASS或现场验收。

GitHub `.github/workflows/dsh-wb-b-postgres.yml`用真实postgres:17服务执行同一测试；远端CI结果须以当前完整源SHA另查。缺PG/驱动时独立测试会明确SKIP，不得视为PG验收。

最终本地实测：真实PG **12/12 PASS**，包含外层事务上下文拒绝与关闭连接503；使用autocommit连接，每次repository操作自建显式事务，避免嵌套事务导致身份残留。此前纯合同回归273 tests OK，其中10个明确无DSN跳过；该回归不充当PG证据。远端首提交w0-contracts已成功，postgres-identity尚运行，最终HEAD须另验。

历史真实红灯与修复：61763642的GitHub PG run42781440846为12 ERROR（owner重连未携带密码，不能视为PG通过）；修复为从原始DSN解析保留认证参数，并为隔离runtime角色生成独立随机密码。F126另外真实发现P1：autocommit连接显式BEGIN后_scope使用savepoint导致主体残留；原本12/12未覆盖该场景。现每次_scope先要求连接事务状态IDLE，存在外层事务直接拒绝且不改调用者事务，新增F等价BEGIN/零身份/零越域读取/ROLLBACK后正常恢复反例。新HEAD仍需F独立核销，不继承旧绿。
