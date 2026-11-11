# C03/C04 milestone真实纵向切片

基线B07首片4906366132147ec59db75112e58cf70c2736ae93（F153接受）。本增量仅milestone，不包括其余kind或完整C03/C04。

正式/workbench中项目详情里程碑与日历共用同一资产面板、同一API与Scope；日历当前为带计划日期的资产列表，不宣称完整月/年日历体验。详情创建、日历查看同asset_id、编辑改期新revision、退役/恢复均调用真实B07。需求/版本/SST过滤仅来自已验证Scope；BATCH_WIDE不伪造连边，选UNSPLIT需求生成真实BRV链接。改Scope立即丢旧列表和未提交上下文，语言切换不改业务身份。

Host须通过受控页面元数据提供会话绑定CSRF token；客户端只回送X-CSRF-Token，不能自报principal/mutation_authorized。无token写按钮禁用；真实provider仍须校验会话、Origin和token及项目写权限。测试注入meta与cookie只是显式fixture，不是DSH接口实现。真实DSH/Windows统一FIELD_NEEDS_BANK_TRANSFER。

错误403/409/422/503不显示保存成功、清空旧记录；原请求保存在当前页面内存，未知提交可显式“重试原请求”保持request_id/payload。刷新列表放弃本地编辑并重新读当前源；浏览器崩溃后未实现自动恢复未知命令，必须通过服务端记录对账，不能声称该恢复已验收。

真实浏览器tests/browser/test_milestone_product_browser.py：实际product_server同源HTTP、独立真PG/非owner运行角色，DB asset_root/revision/outbox作Oracle。详情建→日历同ID→两语→改期rev2→退役rev3→恢复rev4，DB版本和outbox各4；错CSRF403、强制旧CAS409、篡改BRVS422均未新增版本；真实DB故障503清空及恢复。拦截真实已提交响应造成网络丢失，原request_id重放后asset_root不重复；UNSPLIT R2精确Scope落真实asset_brv_link且不继承SST。R1空测试文件字节始终不变，不创建正式运行事实。

本地Node24/24、真实浏览器四项4/4（C01/C02/milestone/同源）、CI admission13通过。最初退役浏览器测试未填必需reason真实失败，补齐用户输入后通过，未弱化后端审计要求。远端精确源CI与F独立审查须另取，不以本地绿代替。截图不作为业务Oracle，未修改08/09/10或R1。

## F156未知提交恢复P1整改

F对a7fd0827真PG/HTTP/Chromium发现：提交已成功但响应丢失后，“刷新里程碑”无条件清pending，使新UUID写入重新可用；原浏览器成功未覆盖此负例。保留历史缺陷，不用旧绿灯转移。

修复为未知请求维持HOLD：读刷新/切语/切分区不能清原request_id/payload或启用新提交；Scope变化/撤权清显示列表与表单，原请求只在私有闭包隔离，不显示旧payload，不向新project/batch发送。仅重新授权的原project+batch可重试；已不确定的请求再遇403不能据此推断旧提交未发生。只有同键重放取得明确结果后解除HOLD。首次明确4xx拒绝可通过刷新重新编辑，网络/503不确定性不作同等处理。

真浏览器新增：已提交丢响应→刷新仍保留retry且禁新保存→切语/切分区仍HOLD→改batch清私密表单/禁原重试→原批次撤权Scope403仍禁重试→恢复ACL重新加载合法Scope→原key重放，DB资产仍2而不重复。页面崩溃持久恢复仍未实现，保持此前限制；FIELD_NEEDS_BANK_TRANSFER不变。
