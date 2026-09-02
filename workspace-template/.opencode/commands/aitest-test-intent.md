---
description: 提交 G3 自主/聚焦 TestIntent，并进入同一 canonical Planner/Scheduler/Router 流程
agent: aitest-director
---

把用户请求规范化为 G3 TestIntent，先确保存在/恢复对应 durable Mission，再调用 `aitest_g3_director` action=`register_intent`。把返回的 `recommended_plan` 交给既有 Planner `propose_plan`；不得直接创建 specialist Session，不得绕过 Scheduler/G2.1 Router。
