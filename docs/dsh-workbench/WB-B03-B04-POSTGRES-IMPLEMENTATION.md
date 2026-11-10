# B03/B04 PostgreSQL 关联工单

基线cf115018（A联合真PG与W0回归成功后启动），独立分支work/dsh-wb-b03-b06。B03与B04分别提交，F独立验收待执行，B05/B06尚未实施。

B03：migration002新增来源限定Requirement、BatchRequirement/BatchVersion复合PK/FK、批次独立relation_revision；RelationStore以事务、项目ACL、修订锁、幂等负载哈希、audit维护成员关联。改期自动推进relation_revision，保持B01日期revision和历史门禁；会员变化不触发错误的日期历史要求。相关对象append-only，撤销/supersession须后续受评审实现，禁止静默改历史。

B04：migration003新增verified_requirement_version权威白名单与BRV复合FK。仅受控来源导入owner能写白名单，runtime仅SELECT；导入函数必须在上游证明已验证后使用，写入来源ref/revision并同事务审计；不开放客户端“verified=true”接口。数据库拒绝有BR+BV但无权威连边的笛卡尔组合。白名单/BRV禁止UPDATE/DELETE。真实银行来源尚未接入，本地明确使用受控测试来源，不伪称SOURCE_FIELD_VERIFIED。

迁移runner显式migrate(target=2/3)，保留001校验和/锁/幂等；downgrade(target=1/2)仅允许增量表为空，非空必须备份对账恢复。空表降级保留现存B01项目/批次，改期功能继续正常；不改R1任何事实。

运行角色执行002/003 runtime.sql授权。trusted backend角色及事务IDLE约束继承F128已接受B01，不接受客户端principal。B03/B04服务入口为business_relations.py，B06真实HTTP另单实现；无Scope API/分页/真实Host验收声明。

真实PG测试入口：

```sh
WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' ../pg-environment-venv/bin/python -m unittest discover -s tests -p 'test_dsh_workbench_b*postgres.py' -v
```

使用PostgreSQL17.6，逐测试独立DB与非owner runtime角色；覆盖授权/撤权/外层BEGIN防串扰、合法BR/BV、跨项目FK、CAS/重放、audit失败零副作用恢复、权威来源缺失/非法组合拒绝、来源不可改写、增量降级重建与B01继承负向/恢复。真实PG CI专属workflow已纳入两份测试，不能以无DSN的明确SKIP代验收。

历史CI：337bc30e真PG专属45/45 PASS；W0轻量环境无Psycopg时新测试模块错误导入可选sql导致ImportError，已修正为可发现的明确SKIP。专属PG工作流仍强制安装驱动、配置真实DSN，并通过通配路径包含关联测试；不以SKIP替代真PG。修复后本地轻量308 tests OK/45明确SKIP；真实PG源验收另计。
