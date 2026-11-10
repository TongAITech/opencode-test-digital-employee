# F 只读目录界面独立复验与两项P2

精确被审源：`01676a8d8118e4d54618ce10f6bfce5f94561ace`，PR174。独立worktree `f-directory-ui`，未参与产品实现，未改08/09/10。仅本地隔离PostgreSQL/nonowner角色、loopback HTTP和Chromium；不访问银行网络或生产R1。

原六套浏览器6/6、Node43/43独立通过。真实102项目全分页、稳定batch/DATE、改期、空目录/日期、403/503恢复、两语身份及Alice/Bob未知写恢复主线均通过。该事实不覆盖下面新增反例。

## P2-01 键盘打开项目卡片后焦点丢失

`f_directory_keyboard_card.py`：对P1项目卡片按钮focus，按Enter打开详情后，heading已为Project details，但`document.activeElement.tagName`实测为BODY，断言失败。`chooseProject()`同步render重建卡片，随后`openDetail()`的通用update找不到原活动元素，导航没有稳定焦点目标。需程序性聚焦详情语义目标，且后续异步日期render不能再丢失焦点。

## P2-02 明确403后仍展示已撤权项目可选项

`f_directory_revoke_eviction.py`：真实PG删除Alice对P1的ACL，选择P1后日期HTTP403，目录ERROR、日期和Scope行已清空；但授权项目select中P1 option实测仍为1，断言期望0失败。项目目录缓存仍READY，使已明确拒绝的项目看似仍可选。应失效该目录或受控重载，并保留错误提示及未知pending的原身份。

本项不是服务端ACL绕过，也未观察到新的越权数据响应；后端正确返回403。分级为目录可用性/授权状态清理P2，不夸大成P1数据泄漏。

## 结果与限制

`REVIEWED_WITH_UI_P2_FINDINGS`。原6浏览器和43Node通过，新增2项真实浏览器反例均FAIL；不报告完整组件无缺陷接受。已通知C修复，需新完整SHA独立重跑。既有主体context/未知提交恢复逻辑不得因清目录而丢失。

FIELD_NEEDS_BANK_TRANSFER；不授完整首页、C03/C04、F01/F02或现场资格，未改R1或实现。
