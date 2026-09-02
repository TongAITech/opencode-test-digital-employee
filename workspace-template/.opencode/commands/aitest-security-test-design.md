---
description: 设计接口安全测试 Profile/Oracle/Safety Contract，不在设计命令中运行扫描
agent: aitest-director
---

注册 `API_SECURITY_TEST_REQUEST` TestIntent。必须明确 authorized_scope、target_environment、oracle、rate/safety limits、stop_conditions，destructive=false by default。本命令只建立 G3 governed profile；后续只能由 G4 Router-bound Security Executor 执行，缺少任一必需 contract 时 fail closed。
