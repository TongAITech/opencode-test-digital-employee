---
description: 设计指定页面/UI测试；真实执行由 G4 governed Executor 完成
agent: aitest-director
---

注册 `UI_TEST_REQUEST` TestIntent，通过 canonical Plan/Task/Router 生成 G3 策略、标准案例和 CaseValueLink。本命令只负责设计；评审/ready 后由 G4 Router-bound Browser/UI Executor 在受控 browser context 中执行。AUTH 需要人工时必须走 canonical HumanGate/BrowserLease Takeover；DOM_SCAN_IS_NOT_PAGE_MODEL。
