# A：02ae2d80 完整工作台实库自动回归

精确源02ae2d806f5ef61965d2d9fc5230ebb3d571c920。测试开始时工作树干净，测试期间未改该工作树；角色A，不代替F或现场验收。

- 开启真实PostgreSQL DSN与Psycopg后，test_dsh_workbench*.py **594/594执行通过，0跳过**，133.767秒。此前无DSN时跳过的数据库用例这次实际执行；不能把这一结果叫作真实DSH、正式任务创建或完整发布门禁通过。
- Node全部test_dsh_workbench*.mjs：117/117。
- Playwright真实PG/HTTP浏览器test*.py：8/8，39.307秒。Host仍显式fixture，R1绑定仍有synthetic构造的组件前提。
- PostgreSQL17.6、Psycopg3.2.13，隔离本机Unix socket；不是SQLite。

```sh
PYTHONPATH="$PWD/../pg-environment-venv/lib/python3.9/site-packages" WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' python3 -m unittest discover -s tests -p 'test_dsh_workbench*.py'
node --test tests/test_dsh_workbench*.mjs
PYTHONPATH="$PWD/../pg-environment-venv/lib/python3.9/site-packages" WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' python3 -m unittest discover -s tests/browser -p 'test*.py'
```

本阶段集成纯codec8618676e及F9e654047/#201，严格结构错误与筛选UNSPLIT两次真实失败分别保留#197/#200；当前源已独立复验。精确861直接head workflow_dispatch 42873392914已确认checkout完整SHA，实际Python3.8.18/3.11.18各11/11 SUCCESS。PR merge预检不是直接head证据，不能混淆。

只读来源预览026ddff9及F1e223b8b/#202已集成，仅COMPONENT_QA_ACCEPTED_PROJECT_ONLY_APPROVED_SCHEMA。F真实加入额外RESTRICTIVE关系级策略时看到物理SPLIT被读为UNSPLIT，这个诊断保留、不计通过。当前冻结迁移只支持project-wide wb.allowed；未知/漂移RLS不在组件资格内，也没有获得部署或正式admission资格。最终创建前必须有独立schema/策略资格与最终受控锁端口；禁止BYPASSRLS绕过。纯preview与codec均不验证Host、来源真实性、正式创建回执，不授创建或执行权。

f1b6b24e的完整ABCD-v4 run42870053745继续单独跟踪，各结果仅属于该精确源，不转签02ae2d80。正式Mission生产绑定、E03控制API、完整业务页面与真实Host/Windows/实际并发/离线/许可证门禁仍未完成，RELEASE_NOT_APPROVED，无最终交付ZIP。
