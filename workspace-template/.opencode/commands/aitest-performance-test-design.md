---
description: 设计接口性能测试 Profile/SLO/Safety Contract，不在设计命令中运行压测
agent: aitest-director
---

注册 `API_PERFORMANCE_TEST_REQUEST` TestIntent。必须明确 SLO、load model、并发/速率/时长、资源限制和 stop_conditions；不得发明 SLA/SLO。本命令只建立 G3 governed profile；后续只能由 G4 Router-bound Performance Executor 执行，缺少任一必需 contract 时 fail closed。
