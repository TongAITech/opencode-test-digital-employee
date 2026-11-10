# HTTP 客户端断连响应 P3 修复候选

状态：CODE_COMPLETE / A_LOCAL_TEST_PASS / F_REVIEW_REQUIRED。基线7586a80c；原施工子任务额度中断后由A接手检查和实测。此报告不代表独立F接受，不能提前合入或记现场通过。

F目录修复报告777b8bd7记录：客户端主动Abort旧请求时，JSON响应写入触发BrokenPipe/ConnectionReset，外层错误处理可能再次向已断开的连接写503并产生重复堆栈。业务/页面回归通过，属非阻断P3。

最小修改仅在business_http.Handler.respond捕获实际连接断开异常并close_connection；不捕获数据库/授权/序列化等其他业务异常，不进行再次响应，不重执行已提交写入。正常已连接客户端仍收到真实503，不把它改成成功。该变更不处理所有静态/legacy传输路径，也不改变R1或Host权限。

A在本地真实loopback socket测试4/4：成功响应体断连、错误响应体断连、发送头前断连，均只有一次响应尝试、没有server错误回调，随后新连接请求仍成功；数据库错误仍为503且无内部配置泄漏。使用受控线程同步和真实SO_LINGER reset，非仅mock writer。

A在真实PostgreSQL/HTTP恢复测试1/1：资产创建事务已提交后响应断连，原request_id+context重放返回原revision，asset_root/revision/outbox各仍为1，无重复写入。

命令：

```bash
python3 -m unittest discover -s tests -p test_dsh_workbench_http_transport.py -v
WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' ../pg-environment-venv/bin/python -m unittest discover -s tests -p test_dsh_workbench_b_transport_postgres.py -v
```

专用PG路径仅为行外隔离环境。真实Host与Windows现场FIELD_NEEDS_BANK_TRANSFER。独立F因子任务额度不可用尚未复验；源固定后CI另核，不把本地自测当独立QA。
