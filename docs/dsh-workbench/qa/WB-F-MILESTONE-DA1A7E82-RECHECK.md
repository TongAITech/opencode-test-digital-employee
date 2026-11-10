# F milestone UI 不确定提交恢复复验

精确源da1a7e82c6d6cf90923624b8acdddd1b32934b56，PR156。独立F worktree/真实临时PG/同源HTTP/Chromium，未参与实现。

新版真实milestone browser1/1及原F刷新恢复断言1/1独立PASS；原断言保留，仅在完成恢复断言后停止，避免继续原旧流程创建新请求。Node24/24 PASS。真实链路覆盖详情/日历同资产ID、版本2/退役3/恢复4及DB outbox数量，403/409/422/503、UNSPLIT合法BRV与R1字节不变。

F-C-MILESTONE-01/P1在本源关闭：未知提交pending跨刷新/语言/分区保留，同一request_id只在原Scope重新授权后重试核对；切批次清空DOM表单/列表，旧payload只留私有闭包、不发送到新Scope，未就绪及撤权拒绝时保持HOLD。源码确认submit同时验证当前READY原project+batch，unknownPending只在核对成功后清除，不再因列表读取解除未知副作用。测试实际commit丢响应后刷新保retry/禁新UUID、切Scope与撤权清空/恢复同key核对DB不重复。

后续主体切换攻击发现新阻断，本结论为MILESTONE_UI_REVIEWED_WITH_SUBJECT_SWITCH_HOLD，未签组件接受，不是完整C03/C04、正式R1资产/全50产品或真实Host现场验收；CSRF/provider为fixture，FIELD_NEEDS_BANK_TRANSFER。A集成后须新联合HEAD回归。未改功能、08/09/10或生产R1事实。

F-C-MILESTONE-02/P1（额外真实边界）：fixture provider切Alice→Bob，Bob同项目合法can_write；Alice未知提交的pending只绑定project/batch，重试把旧private payload提交为Bob的新幂等键，DB资产由2变3。随后旧权限水位使列表ERROR并不撤销已提交副作用。独立真实浏览器tests/browser/f_milestone_subject_attack.py 1/1 FAIL3!=2；不是服务端ACL绕过。应以可信主体/session epoch绑定待核对请求，主体改变禁止旧payload重放，缺可验证主体生命周期时保持禁重试/需重新确认；实际DSH现场仍未接。旧刷新P1已关闭，但新主体边界阻断C组件无保留接受。
