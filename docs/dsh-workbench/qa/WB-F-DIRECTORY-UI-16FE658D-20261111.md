# F 目录界面两项P2修复独立复验

日期：2026-11-11。精确被审源：`16fe658db6e7b52aceb685e1301d22c9dbcc66e6`，PR174。独立worktree `f-directory-ui-fix`，未参与实现或修改08/09/10。原01676a8d报告/失败提交`c6aea8da9ec5e16e15a3da2ae0d0243484c5a28e`保留为历史，不覆盖原失败。

## 本地真实执行

| 范围 | 结果 |
|---|---|
| 六套现有Chromium浏览器测试，含真实PG/HTTP目录与资产链路 | 6/6 PASS |
| C01/Scope/typed drafts/directory四套Node | 43/43 PASS |
| 原F键盘卡片反例原样重跑 | 1/1 PASS |
| 原F撤权目录驱逐反例原样重跑 | 1/1 PASS |
| F新增未知提交期间Scope403、恢复授权后同请求核对 | 1/1 PASS |

使用本地隔离PostgreSQL临时数据库、非owner角色和loopback服务，明确fixture Host/CSRF；系统Python加载本地Playwright和隔离psycopg。没有访问真实Host、银行网络或生产R1，没有构建Windows包。

## 缺陷关闭依据

P2-01：项目卡片focus后Enter导航进入详情，焦点同步落在可程序聚焦的heading；随后Tab到项目入口，异步目录render不再夺走详情焦点。原F只断言非BODY的反例已通过，当前C测试还覆盖heading及后续Tab。

P2-02：真实撤权后日期HTTP403或Scope HTTP403都清空已失效项目目录、卡片及目录选择，目录显示ERROR，明确日期拒绝后禁用的项目控件焦点转到可重载按钮；Scope自身错误保留。显式重载及重授后可恢复。原F撤权P1 option仍1的反例转为0并通过。此问题原分级P2状态清理/可用性，不改称服务端ACL绕过。

F新增恢复组合：Alice实际提交后丢响应，asset_root=1；接着撤销P1权限并触发Scope403，目录和可选P1清空，原retry仍存在但禁用、记录仍1；恢复Alice权限、目录及原Scope后同key核对，retry结束且asset_root/outbox各1。未丢pending或换主体context，未创建重复资产。原全套也继续覆盖Alice/Bob切换、两语身份、102项目全分页、DATE/batch改期、空目录/日期、503及迟到响应。

## 观察与限制

两个旧F反例重跑中的一个预期fetch abort场景在服务端stderr产生非致命BrokenPipe：客户端主动取消旧请求后，服务端写响应遇断开，又进入统一错误分支尝试写503。页面无错误、测试成功且没有额外业务写入。记录为P3传输日志健壮性观察，不隐去日志，不作为本次两P2未修复的证据；后续若清理该日志需另精确源测试。

C提供了该源三CI成功的run/job引用，F本轮仅本地复验，远端同SHA结果由A另核，不挪用016旧CI。

## 裁决

`READ_ONLY_DIRECTORY_UI_COMPONENT_ACCEPTED_AT_16FE658D`。两项P2在该精确源关闭；本次组件范围未发现剩余P0/P1/P2。只接受只读目录、项目选择与Scope联动切片，不授完整首页/看板、项目CRUD、C03/C04/F01/F02或现场资格。FIELD_NEEDS_BANK_TRANSFER保持，后续联合HEAD不继承本源数字。
