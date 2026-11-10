# B05 PostgreSQL SST与可信关联工单

基线6dc36e2fd92919a469003d97662f5c72ace02b19（B03/B04独立接受且A集成后启动）；独立worktree wb-b05、分支work/dsh-wb-b05。状态CODE_COMPLETE / F_INDEPENDENT_REVIEW_PENDING。B06真实Scope HTTP与分页仍未实施；本工单不写R1或共享08/09/10。

migration004新增版本限定SST身份、verified_sst_link与BRVS。SST PK(project,version,sst)、UNIQUE(project,sst)、UNIQUE(project,version,source_system,source_namespace,source_object_id)；同raw SST来源ID可以跨版本对应独立内部ID，同版本重复或跨版本复用内部ID拒绝。identity强制非空source_revision/ref，不能独立导入无来源trace的SST。

verified_sst_link同时复合FK到合法BRV和该版本SST，BRVS复合FK到精确(project,batch,requirement,version,sst)白名单。共享版本或rawID不继承SST连边；不存可写split_state，后续Scope按真实BRV LEFT JOIN BRVS推导UNSPLIT/SPLIT。

runtime角色只能SELECT来源身份/来源白名单，不能提交verified=true或创建来源证明；受控导入owner在外部来源证明已核验后调用import_sst_identity/import_verified_sst_link，来源与审计同事务。真实银行来源未接入，测试来源明确为工程fixture，不伪称现场来源已验证。来源身份、证明、BRVS均append-only；合法supersession/撤销保留后续评审工单，不能静默UPDATE/DELETE。

attach_sst继承可信服务端主体、IDLE事务隔离、ACL先行、relation_revision锁/CAS、幂等负载哈希、审计同事务；来源拒绝/审计故障时关系、revision、请求记录完整回滚，同键修复重试可恢复。migration runner支持显式target4，空增量downgrade到3保留B03/B04数据；已有SST/来源/关联时自动回滚HOLD，须备份对账方案。

部署：专用迁移owner执行migrate(connection,target=4)，管理员执行004_sst.runtime.sql。可信导入连接不能暴露给客户端。沿用Psycopg/PostgreSQL许可证，未添加第三方依赖或受限源码。

真实PG验证：PostgreSQL17.6，逐测试独立数据库和非owner runtime角色。测试文件test_dsh_workbench_b_sst_postgres.py继承B01–B04回归17项，新增SST确切关联、rawID复用、来源不可伪造、事务故障恢复、空增量降级、三版本各多SST共6条真实连边。命令：

```sh
WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' ../pg-environment-venv/bin/python -m unittest discover -s tests -p 'test_dsh_workbench_b*postgres.py' -v
```

专属真实PG CI继续使用postgres:17与上述通配，涵盖B05新增文件。轻量环境缺驱动/DSN仅明确SKIP，不构成PG验收。最终同SHA CI与F独立复验结果需另记；无UI/Host/API/银行现场/最终包完成声明。
