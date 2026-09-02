---
description: 设计指定接口测试；真实执行由 G4 governed Executor 完成
agent: aitest-director
---

注册 `API_TEST_REQUEST` TestIntent，通过 canonical Plan/Task/Router 生成 G3 策略、标准案例和 CaseValueLink。本命令只负责设计；评审/ready 后由 G4 Router-bound API Executor 使用精确 endpoint/method/auth/data binding 执行，不得猜 URL、认证、环境或数据。
