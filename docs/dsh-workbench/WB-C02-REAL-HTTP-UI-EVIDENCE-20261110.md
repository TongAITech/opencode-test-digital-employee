# C02 真实B06/PG/浏览器联调与Scope选择增量

实现基线：B06 f144f1a1492d457f0121dd77e23fdd8c474e4268（F138独立接受），客户端为已修不可变快照版本。新正式UI提供项目ID/稳定批次ID/业务DATE输入，真实GET读取B06，不提供虚假项目/日期目录。需求→系统版本→SST为实际返回关联多选，父选择改变清理下游；十区共享同一Scope面板；切语言保留业务身份，改项目/日期/批次立即abort+清理，错误与重试明确。

真实宿主未挂接业务API时仅报告未就绪，不fallback旧R1接口，不展示样例记录。product_server仍不内置Host身份provider，生产DSH挂接需要D/E/A集成审查；客户端READY只是业务关联读取，不是执行/质量门禁PASS。

独立浏览器测试tests/browser/test_c02_real_scope_browser.py：真实Chromium→真实B06 HTTP→独立PostgreSQL数据库/非owner运行角色，注入显式测试Host provider。DB查询BRV行和relation_revision作Oracle；SPLIT/UNSPLIT真实读取，DB撤权→403/清空→恢复ACL再读；正式UI填范围、选择R2不继承R1 SST、十区导航和英文不改批次/需求、改批次清空/404/恢复。

本地真PG+HTTP+浏览器1/1、C01浏览器1/1、Node24通过。最初系统python缺psycopg导致明确FAIL，使用独立PG环境site-packages后真实运行成功，无跳过。新增远端Postgres16 service浏览器job，必须取得新精确源结果。测试Host/token为合成测试资料，不是银行现场资格。真实DSH/Windows/F01仍未完成，C02不自报IMPLEMENTATION_QA_PASS。未改08/09/10或R1。
