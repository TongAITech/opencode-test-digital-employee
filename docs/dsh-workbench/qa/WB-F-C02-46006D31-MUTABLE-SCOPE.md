# F C02 准备组件独立审查

精确源46006d3170e2ff01dfd54d775ae261f33c4b2c51，PR131。原Scope18+C01三项Node=21/21 PASS；同源c01-product-browser和w0-contracts SUCCESS。不将这些结果当C02产品UI或B06 API验收。

F-C02-01/P1客户端隔离：load内部校验用scope快照与公开state.scope共用同一引用；LOADING期间外部写c.state.scope.project_id='foreign'后，foreign响应被接受为READY。真实独立Node输出accepted=true,state=READY,project=foreign；初始请求project=p。port也收到同一可变引用，嵌套filter数组有相同风险。服务器ACL并未由本反例证实绕过，但组件宣称的跨Scope迟到响应拒绝/不可变查询边界不成立。

独立负例tests/f_c02_mutable_scope.mjs执行node --test，原源应FAIL。应隔离私有验证快照与公开状态/port参数，覆盖项目/批次/数组变异与重叠请求；F不参与实现。已通知C修复，当前C02_COMPONENT_REVIEWED_WITH_BLOCKERS；后续必须固定新源独立复验。C02依旧BLOCKED_B06，未连产品app、不宣称真实API/UI/Host通过。未改08/09/10。
