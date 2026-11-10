# F B/C 实现修复独立复验

F未参与被测实现。分别在两个精确源隔离worktree运行；不将两分支结果当作A联合HEAD结果。

B PR124源175efda6c070010b64cbc5136de35c7b1d8cbe4c：真实PostgreSQL原13/13独立执行PASS，F追加explicit BEGIN拒绝/身份清理/回滚后恢复1/1 PASS。非owner隔离数据库/运行角色每测试创建销毁；检查_scope在每次入口要求事务IDLE且closed映射503，不再由autocommit布尔推测无外层事务。F-B01-01/P1在此源关闭。原61763642真实失败保留。GitHub同源postgres-identity SUCCESS：https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42782947241/job/129717130236；w0-contracts SUCCESS：https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42782946823/job/129717123000。接受B01/B02仓储数据库组件增量：B01_B02_POSTGRES_COMPONENT_ACCEPTED。此处没有Host派生principal、HTTP权限或B03–B06完整关系链的验收；连接由可信后端服务持有的限制仍适用。生产数据迁移与现场备份恢复不由一次性测试DB回滚抵扣。

C PR122源785c5a3c90baf17476966bec2dc16f32d1d4872f：Node3/3、真实product_server socket+Chromium1/1 PASS；F独立反例重新访问/workbench及/workbench/均5导航/非空标题，键盘Enter导航后焦点仍BUTTON。F-C01-01/P1与F-C01-02/P2在此源关闭，旧98292caf缺陷保留。浏览器测试迁入独立依赖workflow，没有以移除测试制造通过。GitHub同源c01-product-browser SUCCESS：https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42783159523/job/129717826012；w0-contracts SUCCESS：https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42783159330/job/129717825994。接受C01导航骨架组件：C01_NAVIGATION_COMPONENT_ACCEPTED，不等于完整产品50项/F02验收。

结论：两个修复源在本轮组件验收范围无剩余P0/P1，可由A集成后对新的精确联合HEAD做集成回归；不得把当前分支PASS挪给联合SHA。正式DSH宿主、B06合法Scope/业务API、R1/人审/租约、实际并发、Windows/离线和银行现场、许可证仍为独立门禁，不能记最终产品或交付PASS。F未改08/09/10、实现或R1事实。
