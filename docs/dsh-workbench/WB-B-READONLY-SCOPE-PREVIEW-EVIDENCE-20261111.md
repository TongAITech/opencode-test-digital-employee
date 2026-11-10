# B：真实PG完整来源只读预览组件

状态：CODE_COMPLETE / B_LOCAL_REGRESSION_PASS / F_REVIEW_REQUIRED。基线`b6d93e41b98796e82650645c019fe1e883030862`；实现与测试源`fdd39c6ba564d2cfe9792438f12a932664668801`。本组件不是正式创建、admission或可信verifier，不核销008/正式Scope绑定/Host/现场门禁。

## 实际接口与边界

新增内部`tools.dsh_workbench.business_scope_preview.ReadOnlyScopeSnapshotPreview(connection).preview(principal,project,batch,release_date=...,requirement_ids=...,version_ids=...,sst_ids=...)`。principal必须由受控服务端身份适配提供；没有新增HTTP、浏览器principal参数、迁移、表、权限或正式命令。

通过组合复用BusinessStore事务保护，不继承create_batch/reschedule等写方法。入口要求空闲autocommit连接，自持REPEATABLE READ READ ONLY，使用原有`wb.allowed`及RLS；外层事务拒绝，不改变调用者主体。只SELECT业务资料并使用SET LOCAL配置本次主体/statement_timeout，没有业务写、审计写、分配ID、R1导入/路径/读取/修改。返回固定`preview_state=READ_ONLY_SNAPSHOT_NOT_ADMISSION`与`snapshot`，不返回digest、verified=true、正式回执或创建许可；每次返回独立资料而非共享缓存。

snapshot按V3形状包含同一数据库快照的release_batch.revision（date_revision）、relation_revision、access_scope_revision、system_id与五类实际来源tag。BRV/BRVS按精确复合键连接，UNSPLIT三个SST字段为null；version_source不伪造source_ref。按UTF-8排序filters和边；请求重复ID、非法/空关联、未完整覆盖的筛选、缺来源/隐藏成员全部拒绝，不签部分成功。

此处是读权限允许的**as-of预览**，不是提交瞬间的权限或来源围栏。读事务开始后并发提交的改期/关系不会与本次快照混合；下次读取得新版本。正式创建仍须已签协议中的独立durable PREPARE、受控锁定快照、当前Host/创建动作及正式writer围栏；绝不把本预览转成admission certificate，也不删除/放宽既有B06保护。

预算为服务端内部配置：默认最多10000边、snapshot普通JSON序列化UTF-8最多4MiB、每条受控数据读取语句statement_timeout=5000ms；各filter至多100个非空ID。行/来源原始字节在取资料前检查，完整序列化再核实际字节；超限413，不截断。statement_timeout是PG语句预算，不宣称整个网络/连接建立或调用恰好5秒。真实取消后回滚、归还IDLE并恢复会话设置；缺读取权限/来源schema返回503，绝不走无Scope fallback。

## 实际测试及失败修复

环境：本地官方源码PG17.6，Psycopg3.2.13，Unix socket `/tmp/dsh-pg-371f43f0` 端口55432；每例独立临时数据库与非owner/NOBYPASSRLS runtime角色，不使用SQLite，不接触生产数据库。

| 范围 | 本次实际结果 |
|---|---|
| 新只读预览真实PG测试 | 17/17，5.975秒 |
| 全B真实PG集中回归 `test_dsh_workbench_b*postgres.py` | 240/240，89.800秒，无跳过 |
| 轻量 `test_dsh_workbench*.py`，未设置PG DSN | 583发现，273执行通过、310明确跳过，6.414秒；不能写583实测通过 |
| 编译/差异检查 | py_compile及git diff --check通过 |

新17例覆盖：真实来源字段Oracle、两需求共享版本但SST不串、多版本相同raw SST不同内部身份、UNSPLIT及全ID覆盖、跨项目相同业务ID不串源、普通reader不获创建权、ACL撤权/恢复、8类来源/成员RLS隐藏拒绝、真实SELECT权限缺失、外层事务不串主体、事务READ ONLY/隔离级别与临时配置归还、边数和精确字节预算、真实pg_sleep触发statement取消/恢复、并发日期与关系提交不混快照、闭连接拒绝/重连恢复、Unicode/控制字符原样保留、结果脱离缓存，以及读取过程中禁止Python文件访问仍成功（无R1/文件依赖）。

首轮14例有1个测试夹具错误：Observe闭包类无构造参数却传入raw连接；纠正夹具后增加跨项目/文件零访问/DB读取权限等边界，最终17/17。没有删除或跳过失败测试，没有更改产品以伪造PASS。实施过程中改用组合而非继承，避免让只读端口意外暴露BusinessStore写方法；测试明确核验没有create_batch/reschedule入口。

命令：

```sh
WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' ../pg-environment-venv/bin/python -m unittest discover -s tests -p test_dsh_workbench_b_scope_preview_postgres.py -v
WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' ../pg-environment-venv/bin/python -m unittest discover -s tests -p 'test_dsh_workbench_b*postgres.py'
python3 -m unittest discover -s tests -p 'test_dsh_workbench*.py'
```

没有新依赖或许可证变更，未改08/09/10、既有HTTP/API、现有ScopeStore、迁移或R1事实。尚需最新完整PR HEAD的独立F验收；本地B自测不代签F或现场。真实DSH/Windows继续FIELD_NEEDS_BANK_TRANSFER，最终发布未批准。
