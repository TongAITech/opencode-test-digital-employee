# F B01/B02 真PostgreSQL独立验收缺陷

精确源617636424877f24a582d1c55e374553131c3d85a，PR124。独立F数据库及nonowner运行角色，psycopg3.2.13，复用本机PG服务但未操作B数据。B原真库12/12独立执行通过。

F-B01-01/P1：仅检查connection.autocommit不能保证事务隔离。autocommit=True连接仍能显式BEGIN；_scope使用connection.transaction进入已有外层事务的savepoint，set_config(...,true)在方法返回后仍有效。复现：创建P1批次；runtime.execute('BEGIN')；store.batches('alice','P1')；current_setting('wb.principal',true)得到alice、无作用域直接SELECT count(*) FROM wb.release_batch得到1。期待作用域退出身份为空且行数0，实际F负向1/1 FAIL。随后ROLLBACK清理。

独立复现代码tests/f_b01_transaction_attack.py，可在配置WB_PG_TEST_DSN后以PYTHONPATH=. pg-environment-venv/bin/python -m unittest discover -s tests -p f_b01_transaction_attack.py -k test_f_manual -v运行。此缺陷使上层事务/池误用保留授权身份，应在作用域入口校验真实事务状态或实现严格独立事务边界，并验异常恢复/重复调用。F仅报告，不参与实现。

结论B01_B02_REVIEWED_WITH_BLOCKERS；已通知B修复。A另发现此源GitHub真PG CI失败，仍须新源修复/新源真库CI与F复验。没有业务API、Host/R1、迁移生产数据、完整B03–B06或产品QA通过结论。未改08/09/10。
