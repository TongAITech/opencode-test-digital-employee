# F 里程碑UI恢复独立缺陷

精确源a7fd08278404f0754147eb2ea72910ad10807914，PR156；独立真实PG/HTTP/Chromium，原测试1/1 PASS。

F-C-MILESTONE-01/P1：创建提交已成功、响应丢失时pending保存原request_id，原请求重试可恢复；但刷新按钮处理无条件pending=null，未重放对账便丢失未确定提交身份，隐藏重试并重新启用以新UUID保存。读取列表不等于以原request_id确认提交响应，重复保存可能制造第二业务资产。

F复用真实测试完整链路仅替换丢响应后的操作为刷新，并断言原请求恢复按钮仍可用，真实1/1 FAIL：uncertain committed request identity lost on refresh；数据库已提交第二资产。独立反例tests/browser/f_milestone_uncertain_attack.py。应保留pending跨读取刷新，或先同key对账再解除未知副作用状态，不应无提示清空恢复身份。F不参与实现。

已通知C与A，当前MILESTONE_UI_REVIEWED_WITH_BLOCKERS，不接受此源。后续须新精确SHA复验原失败与正常CRUD/幂等恢复；真实Host仍FIELD_NEEDS_BANK_TRANSFER。未改功能、08/09/10或生产R1。
