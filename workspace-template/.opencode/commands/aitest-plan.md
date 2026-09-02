---
description: 提交并冻结 AI 生成的 bounded Plan
agent: aitest-planner
---

基于 Planner Session 的 durable Mission/Goal context 形成 task/dependency candidate，调用 `aitest_planner` action=`propose_plan`。R2.3 PASS 后 Runtime 自动 handoff Scheduler 并 dispatch 首个 READY Task，不再手工切 Scheduler。
