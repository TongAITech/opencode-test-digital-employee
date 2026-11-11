# C03/C02 只读目录界面纵向切片

基线7586a80c0d8f5cd5205a78ca735b1ca15e12a4b2；独立worktree c-directory-ui。仅授权项目/日期目录→稳定batch→真实Scope，不新增项目写权限、看板阶段或质量指标。

首页提供真实授权项目卡片；全局项目与投产日期选择消费目录所有页直到next_page_cursor=null，选择日期后按真实project_id/batch_id/DATE加载现有Scope。原手动ID输入保留为调试备用；更改手输值会清除不再匹配的目录选择。项目切换/目录重载立即清空旧Scope与资产显示，不更改唯一资产控制器内的未知pending或原subject context。目录状态只读深冻结，拒绝重复记录、游标环、修订漂移、错误日期/foreign project及迟到响应；无权限/503清空，合法空目录不伪造记录。

新Node目录10/10，旧草稿/Scope/C01合计43/43通过。真实PostgreSQL+非owner运行角色+同源HTTP+Chromium新增1/1，通过102个授权项目（P1、P_EMPTY和100个Z项目；P2只授权Bob）跨页读取、项目卡片进入详情、DATE与稳定batch匹配、P_EMPTY空日期、延迟旧项目响应、改期、撤权403、DB503与恢复、空授权目录、英语身份稳定。DB作为目录数量/日期/Scope连边Oracle。另实测Alice提交成功丢响应→目录切Bob（同项目合法写权）→原context409、资产数仍1→目录恢复Alice→同key核对、asset_root/outbox仍各1，旧payload不显示。

集中浏览器六套6/6通过；现有33 Node与新增10项共43通过；ci_admission13通过。首次浏览器模块直接导入Milestone TestCase，unittest额外收集继承的41项（42/42通过）；已改为模块别名避免重复收集，最终新增仅1项、全浏览器6项，未将重复用例计作新增功能。

命令：

```bash
node --test tests/test_dsh_workbench_draft_forms.mjs tests/test_dsh_workbench_c01.mjs tests/test_dsh_workbench_c02_scope.mjs tests/test_dsh_workbench_directory_client.mjs
PYTHONPATH="$PWD/../pg-environment-venv/lib/python3.9/site-packages" WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' python3 -m unittest discover -s tests/browser -p 'test*.py'
```

Host/CSRF仍为明确fixture，仅组件证据；FIELD_NEEDS_BANK_TRANSFER。不授完整首页/看板、C03/C04整体、正式R1结果或现场资格。未改R1/08/09/10。远端同SHA CI与F独立验收待执行。


## F 对01676a8d的两项真实反例与修复

F新增真实键盘回归发现：卡片Enter进入详情后重绘移除原按钮，焦点退BODY。现卡片动作同步导航后聚焦详情heading（tabIndex=-1），后续Tab到项目详情入口；目录异步重绘只恢复仍属于可见卡片的稳定按钮，不用timer或抢占已移动到页面其他位置的焦点。卡片按钮accessible name包含项目名。

F另发现日期请求403后旧项目仍在项目select中。现日期目录或Scope加载的明确403均使整个项目目录缓存与选择失效，Scope/资产显示清空、保ERROR和显式重载入口；如果焦点原位于被失效的目录控件，移到加载按钮以便键盘恢复。其他页面焦点不被异步抢占。它修复过期可选状态，不声称原后端授权被绕过。不触碰资产控制器private pending/request_id/write-context。

新增真PG/Chromium断言覆盖卡片focus→Enter→heading→Tab、撤权403后无P1选项/无卡片/选择器禁用及恢复焦点；原分页、迟到、改期、两语、503和Alice/Bob/Alice未知提交恢复例全部保留。定向1/1与Node43/43通过；固定新源仍须六browser及F独立复验，不将旧源通过转移。

修复后本地六套真实PG/HTTP/Chromium6/6通过（27.01秒），包括原分页/主体恢复与新增键盘/双403路径；Node43/43通过。新提交后的同SHA CI与F独立复验仍待核对。
