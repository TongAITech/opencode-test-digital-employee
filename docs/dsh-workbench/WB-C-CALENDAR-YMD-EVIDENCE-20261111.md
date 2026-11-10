# C 日历年／月／日组件候选

状态：CODE_COMPLETE / A_LOCAL_REGRESSION_PASS / F_REVIEW_REQUIRED / NOT_INTEGRATED。
基线：8a0393913aa1b60e20ae910b32fa079e47a57228；实现与测试源：810660377dbe5852711722527edadc03f7d1cc7d。原C任务额度中断后由A在独立c-calendar worktree施工，不是C或F独立签署。本文是追加证据，不修改08/09/10。

## 已实现范围

- P04-01里程碑年／月／日视图、上一期/下一期、日期跳转；年按月计数、月按真实公历日定位，点选日期进入日视图并预填新建日期。项目详情与日历复用同一已授权、全分页读取后的资产集合和asset_id/revision，不建第二份事件资料。
- 导航日期仅改变日历视口，不改变全局投产日期、稳定batch或关联Scope。初始视口来自当前Scope投产日期；选Scope、改期或撤权会清空旧事件并重置。读取未就绪/失败显示未知数量，不把缺数据写成零事件成功。
- 公历DATE计算不使用浏览者本地时区；覆盖闰年、世纪年、0001–9999、跨年及月底截断。zh-CN默认与en-US；周一开头。键盘操作后保留导航焦点；日期上限/下限禁止越界导航。
- 继续复用现有PG资产事务、CAS、退役/恢复、CSRF、原主体write-context和原请求幂等恢复。未知提交期间视图导航不能抹掉待恢复请求或开放新写入。坏日期响应整体拒绝，迟到旧Scope响应不能恢复旧事件。标题使用文本，不按HTML插入。
- 没有新依赖、正式R1写入或许可证变动。

## A 实测与失败修复记录

| 验证 | 结果与含义 |
|---|---|
| Node test_dsh_workbench_calendar.mjs | 18/18；日期正反边界、三个时区、去重拒绝、事件身份/排序、不变输入 |
| Node全部test_dsh_workbench*.mjs | 91/91 |
| 新真实PG/HTTP/Playwright用例 | 1/1，4.746秒；在Los Angeles/Kiritimati浏览者时区核对闰日；真实资产ID、创建/编辑版本、outbox计数、提交丢回执重试不重复、ACL撤权403、坏日期整体拒绝、迟到响应清空；原临时R1字节不变 |
| 全tests/browser/test*.py | 7/7，31.249秒；真实PG17.6、Psycopg3.2.13和真实Chromium，显式fixture Host |
| 既有tests/browser/f_*.py由A复跑 | 5/5，27.764秒；不是新独立F接受 |
| Python test_dsh_workbench*.py无PG环境 | 561发现，269执行通过、292明确跳过；不能记561项实测通过 |

首轮新用例的迟到响应测试超时：页面挂载时已捕获fetch，事后替换window.fetch未拦截实际请求。将可控延迟夹具安装于页面初始化后，用真实HTTP响应延迟交付复跑通过，未修改产品以迎合测试。首轮全7项回归有1错误：旧Scope浏览器测试的显式静态白名单漏了两个新增模块，补齐精确模块名后7/7通过；未删除或跳过旧测试。两个失败不作为通过证据。

命令（本地隔离PG路径，不是银行环境）：

```sh
node --test tests/test_dsh_workbench*.mjs
PYTHONPATH="$PWD/../pg-environment-venv/lib/python3.9/site-packages" WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' python3 -m unittest discover -s tests/browser -p 'test*.py'
PYTHONPATH="$PWD/../pg-environment-venv/lib/python3.9/site-packages" WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' python3 -m unittest discover -s tests/browser -p 'f_*.py'
python3 -m unittest discover -s tests -p 'test_dsh_workbench*.py'
```

## 明确保留的未完成项

P04-01仅里程碑组件代码完成，F尚未验收，不记完整C03完成。P04-02独立日程管理、P04-03临期/逾期提醒、P04-04提测/冻结绑定仍未实现；没有权威BUSINESS_TZ时不按浏览者“今天”编造逾期。通用项目编辑/看板状态、正式Mission绑定/控制、R1资产来源映射仍待完成。F与C独立任务额度目前不可用，后续必须基于最新完整PR HEAD复验；A自测及旧F报告不能代签。真实DSH/SSO与Windows仍FIELD_NEEDS_BANK_TRANSFER，最终发布未批准，没有构建最终银行ZIP。
