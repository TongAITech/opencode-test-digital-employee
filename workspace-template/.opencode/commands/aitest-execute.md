---
description: 通过 G4 执行当前 Router-bound 标准案例/步骤
agent: aitest-executor
---

只执行当前 G2/G2.1 已绑定的 Mission/Task/ExecutionAttempt/Session，不创建或管理 Session。根据 governed StandardTestCase 和 capability binding 调用 `aitest_executor` 的 G4 actions：先恢复/记录 Step Cursor，再执行 Browser/API/DB/CAT/Manual/Security/Performance capability，并记录 Oracle/Evidence。缺少 Provider/Auth/Approval/Safety/SLO 时 fail closed。需要 4A/验证码/短信/人脸等人工动作时必须创建 canonical R2.6 HumanGate + BrowserLease Human Takeover 并结束当前 AI turn；不得长期阻塞 tool call。TEST_FAIL != CONFIRMED_DEFECT，G5 继续 HOLD。
