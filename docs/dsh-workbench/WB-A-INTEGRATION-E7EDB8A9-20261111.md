# A 集成实库回归

精确源：`e7edb8a99cc48d5a30975f6f3e0689631c8b7852`。本轮已合入Gates/默认原生fetch修复、PG来源profile及独立失败报告；未合入PR223受阻实现或PR225需求界面候选。

真实本机PostgreSQL17.6，Psycopg3.2.13，Python3.9.6：`WB_PG_TEST_DSN`指向已有隔离Unix socket测试库；运行`../pg-environment-venv/bin/python -m unittest discover -s tests -p 'test_dsh_workbench*.py'`。

结果：**632/632，150.198秒，0跳过**。输出HOST_INTEGRATION_REQUIRED仍是fixture就绪声明，不能当真实DSH宿主通过。此轮覆盖工作台Python合同/业务/API/来源profile等仓内自动化，不含完整RC7/RC7.2、真实银行Host/SSO/Windows离线/实际Teams并发资格。

此前精确2b94d236的Node120、浏览器9与纯模块20单列保留，不转签本轮源。F226只读profile窄范围接受也不扩展成admission或DDL/role围栏资格。

F229对1b85493f的callable身份P1、F228对26257eae的窄屏P2均真实保留在本源，候选功能未因作者或CI通过而绕过独立门禁。发布保持NOT_APPROVED。
