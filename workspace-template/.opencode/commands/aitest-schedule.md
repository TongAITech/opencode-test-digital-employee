---
description: 恢复/推进 R2 bounded Scheduler
agent: aitest-scheduler
---

正常路径由 Runtime 自动 advance。仅在显式恢复/诊断时调用 `aitest_scheduler` action=`advance` 并传 mission_id。不要重复创建 Task 或 Plan。
